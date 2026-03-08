"""Skill outcome resolver — session-end hook logic.

Reads active_skills from hook_state for a session, determines the session
outcome from its frustration level, and updates SkillProvenanceTracker
records from outcome='unknown' to the resolved outcome.

Called by the session-end hook (session-memory-consolidation-async.py)
after the session summary is generated.

Outcome mapping:
    frustration_level "low" | "unknown"  →  "success"
    frustration_level "medium" | "high"  →  "partial"

Records already set to "success" or "failure" are not overwritten,
preserving any manual or prior resolution.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Outcomes considered already-resolved (will not be overwritten)
_RESOLVED_OUTCOMES = frozenset({"success", "failure"})

# Frustration levels that map to "partial"
_PARTIAL_LEVELS = frozenset({"medium", "high"})


def resolve_session_outcomes(
    session_id: str,
    db_path: str | None = None,
    state_file=None,
) -> dict:
    """Update provenance outcomes for all skills used in this session.

    Args:
        session_id: The session being resolved.
        db_path:    Path to intelligence.db.
        state_file: Path to hook-state.json.

    Returns:
        dict with keys: session_id, outcome, updated (count of rows updated).
    """
    result = {"session_id": session_id, "outcome": "success", "updated": 0}

    try:
        active_skills = _get_active_skills(session_id, state_file)
        if not active_skills:
            return result

        frustration = _get_frustration_level(session_id)
        outcome = "partial" if frustration in _PARTIAL_LEVELS else "success"
        result["outcome"] = outcome

        updated = _update_provenance(session_id, active_skills, outcome, db_path)
        result["updated"] = updated

    except Exception:
        logger.debug("skill_outcome_resolver: resolution failed", exc_info=True)

    return result


# ── Private helpers ────────────────────────────────────────────────────────────

def _get_active_skills(session_id: str, state_file) -> list[str]:
    """Read active_skills list from hook_state for this session."""
    try:
        from memory_system.hook_state import get_session_state
        state = get_session_state(session_id=session_id, state_file=state_file)
        return list(state.get("active_skills", []))
    except Exception:
        return []


def _get_frustration_level(session_id: str) -> str:
    """Read frustration_level from the persisted session summary.

    Returns "unknown" if the summary doesn't exist or can't be read.
    """
    try:
        from memory_system.session_summary import load_summary
        summary = load_summary(session_id)
        if summary:
            return summary.frustration_level
    except Exception:
        pass
    return "unknown"


def _update_provenance(
    session_id: str,
    active_skills: list[str],
    outcome: str,
    db_path: str | None,
) -> int:
    """Update provenance rows for active_skills in this session.

    Only rows with outcome='unknown' are updated — already-resolved
    records ("success", "failure") are left unchanged.

    Returns the number of rows actually updated.
    """
    from memory_system.config import cfg
    path = str(db_path) if db_path else str(cfg.intelligence_db_path)

    try:
        conn = sqlite3.connect(path)
        try:
            total = 0
            for skill_name in active_skills:
                cur = conn.execute(
                    "UPDATE skill_provenance"
                    " SET outcome = ?"
                    " WHERE skill_name = ? AND session_id = ? AND outcome = 'unknown'",
                    (outcome, skill_name, session_id),
                )
                total += cur.rowcount
            conn.commit()
            return total
        finally:
            conn.close()
    except Exception:
        logger.debug("skill_outcome_resolver: DB update failed", exc_info=True)
        return 0
