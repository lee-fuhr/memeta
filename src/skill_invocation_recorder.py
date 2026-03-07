"""Skill invocation recorder — PreToolUse hook logic.

Extracts skill invocations from Claude Code PreToolUse hook payloads,
records them via SkillProvenanceTracker, and appends the skill name
to active_skills in the hook state file.

The thin hook script at hooks/skill-invocation-recorder.py calls
process_tool_event() with the raw stdin payload. All testable logic
lives here; the hook is just a wrapper.

Usage (from hook):
    from memory_system.skill_invocation_recorder import process_tool_event
    result = process_tool_event(payload)

Returns:
    skill_name (str) if a Skill invocation was recorded, None otherwise.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def process_tool_event(
    payload: dict,
    state_file=None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Process a PreToolUse payload and record any Skill invocation.

    Args:
        payload:    The JSON payload from Claude Code's PreToolUse hook.
                    Expected keys: sessionId, toolName, toolInput.
        state_file: Path to hook-state.json. Defaults to ~/.claude/hook-state.json.
        db_path:    Path to intelligence.db. Defaults to cfg.intelligence_db_path.

    Returns:
        The skill name that was recorded, or None if this was not a Skill call.
    """
    if not payload:
        return None

    tool_name = payload.get("toolName")
    if tool_name != "Skill":
        return None

    tool_input = payload.get("toolInput")
    if not tool_input or not isinstance(tool_input, dict):
        return None

    # Extract skill name — try "skill" key first (matches hook_events.jsonl format),
    # fall back to "name" key.
    skill_name = tool_input.get("skill") or tool_input.get("name") or ""
    if not skill_name:
        return None

    session_id = payload.get("sessionId") or "unknown"
    context_snippet = str(tool_input.get("args", ""))

    _record_provenance(skill_name, session_id, context_snippet, db_path)
    _append_active_skill(skill_name, session_id, state_file)

    return skill_name


# ── Private helpers ────────────────────────────────────────────────────────────

def _record_provenance(
    skill_name: str,
    session_id: str,
    context_snippet: str,
    db_path: Optional[str],
) -> None:
    """Write a provenance row with outcome='unknown' (resolved later by session-end hook)."""
    try:
        from memory_system.skill_provenance import SkillProvenanceTracker
        tracker = SkillProvenanceTracker(db_path=db_path)
        tracker.record_invocation(
            skill_name=skill_name,
            session_id=session_id,
            outcome="unknown",
            context_snippet=context_snippet,
        )
    except Exception:
        logger.debug("skill_invocation_recorder: provenance write failed", exc_info=True)


def _append_active_skill(
    skill_name: str,
    session_id: str,
    state_file,
) -> None:
    """Add skill_name to active_skills for this session (no duplicates)."""
    try:
        from memory_system.hook_state import get_session_state, update_session_state
        state = get_session_state(session_id=session_id, state_file=state_file)
        active = list(state.get("active_skills", []))
        if skill_name not in active:
            active.append(skill_name)
            update_session_state(
                {"active_skills": active},
                session_id=session_id,
                state_file=state_file,
            )
    except Exception:
        logger.debug("skill_invocation_recorder: hook state update failed", exc_info=True)
