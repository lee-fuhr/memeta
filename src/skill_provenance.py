"""Skill provenance tracker — records which sessions invoked which skills and why.

Maintains an audit trail of every skill invocation: session ID, outcome,
context snippet, and notes. Supports history queries, co-invocation analysis,
and outcome summaries.

Usage:
    from memory_system.skill_provenance import SkillProvenanceTracker

    tracker = SkillProvenanceTracker()
    tracker.record_invocation("my-skill", session_id="abc123", outcome="success")

    history = tracker.get_history("my-skill")
    co = tracker.get_co_invocations("my-skill")
    summary = tracker.outcome_summary("my-skill")
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from memory_system.config import cfg

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS skill_provenance (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name       TEXT    NOT NULL,
    session_id       TEXT    NOT NULL,
    invoked_at       TEXT    NOT NULL,
    outcome          TEXT    NOT NULL DEFAULT 'unknown',
    context_snippet  TEXT    NOT NULL DEFAULT '',
    notes            TEXT    NOT NULL DEFAULT ''
)
"""

_IDX_SKILL = "CREATE INDEX IF NOT EXISTS idx_sp_skill ON skill_provenance (skill_name)"
_IDX_SESSION = "CREATE INDEX IF NOT EXISTS idx_sp_session ON skill_provenance (session_id)"
_IDX_AT = "CREATE INDEX IF NOT EXISTS idx_sp_at ON skill_provenance (invoked_at)"


@dataclass
class ProvenanceRecord:
    """One recorded invocation of a skill."""

    id: int
    skill_name: str
    session_id: str
    invoked_at: str
    outcome: str
    context_snippet: str
    notes: str


class SkillProvenanceTracker:
    """Record and query skill invocation provenance.

    Each invocation is stored as a row in `skill_provenance` (SQLite). The
    tracker supports history queries, first-use detection, session membership,
    co-invocation analysis, and outcome summaries.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ── Setup ─────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_IDX_SKILL)
        self._conn.execute(_IDX_SESSION)
        self._conn.execute(_IDX_AT)
        self._conn.commit()

    # ── Public API ────────────────────────────────────────────────────────

    def record_invocation(
        self,
        skill_name: str,
        session_id: str,
        outcome: str = "unknown",
        context_snippet: str = "",
        notes: str = "",
    ) -> ProvenanceRecord:
        """Record a skill invocation and return the persisted ProvenanceRecord."""
        invoked_at = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO skill_provenance"
            " (skill_name, session_id, invoked_at, outcome, context_snippet, notes)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (skill_name, session_id, invoked_at, outcome, context_snippet, notes),
        )
        self._conn.commit()
        return ProvenanceRecord(
            id=cur.lastrowid,
            skill_name=skill_name,
            session_id=session_id,
            invoked_at=invoked_at,
            outcome=outcome,
            context_snippet=context_snippet,
            notes=notes,
        )

    def get_history(self, skill_name: str) -> list[ProvenanceRecord]:
        """Return all invocations for skill_name in chronological order."""
        rows = self._conn.execute(
            "SELECT * FROM skill_provenance WHERE skill_name = ?"
            " ORDER BY invoked_at ASC, id ASC",
            (skill_name,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get_first_use(self, skill_name: str) -> datetime | None:
        """Return the datetime of the earliest recorded invocation, or None."""
        row = self._conn.execute(
            "SELECT invoked_at FROM skill_provenance WHERE skill_name = ?"
            " ORDER BY invoked_at ASC, id ASC LIMIT 1",
            (skill_name,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["invoked_at"])

    def get_sessions_for_skill(self, skill_name: str) -> list[str]:
        """Return deduplicated session IDs that invoked skill_name (oldest first)."""
        rows = self._conn.execute(
            "SELECT session_id FROM skill_provenance"
            " WHERE skill_name = ? GROUP BY session_id ORDER BY MIN(invoked_at) ASC",
            (skill_name,),
        ).fetchall()
        return [r["session_id"] for r in rows]

    def get_skills_for_session(self, session_id: str) -> list[str]:
        """Return deduplicated skill names invoked in session_id (first use order)."""
        rows = self._conn.execute(
            "SELECT skill_name FROM skill_provenance"
            " WHERE session_id = ? GROUP BY skill_name ORDER BY MIN(invoked_at) ASC",
            (session_id,),
        ).fetchall()
        return [r["skill_name"] for r in rows]

    def get_co_invocations(self, skill_name: str) -> list[str]:
        """Return deduplicated skill names that appeared in the same session as skill_name.

        Excludes skill_name itself.
        """
        rows = self._conn.execute(
            """
            SELECT DISTINCT p2.skill_name
            FROM skill_provenance p1
            JOIN skill_provenance p2 ON p1.session_id = p2.session_id
            WHERE p1.skill_name = ?
              AND p2.skill_name != ?
            ORDER BY p2.skill_name ASC
            """,
            (skill_name, skill_name),
        ).fetchall()
        return [r["skill_name"] for r in rows]

    def outcome_summary(self, skill_name: str) -> dict[str, int]:
        """Return a dict mapping outcome → count for skill_name."""
        rows = self._conn.execute(
            "SELECT outcome, COUNT(*) as cnt FROM skill_provenance"
            " WHERE skill_name = ? GROUP BY outcome",
            (skill_name,),
        ).fetchall()
        return {r["outcome"]: r["cnt"] for r in rows}

    def invocation_count(self, skill_name: str) -> int:
        """Return the total number of recorded invocations for skill_name."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM skill_provenance WHERE skill_name = ?",
            (skill_name,),
        ).fetchone()
        return row[0]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _row_to_record(row: sqlite3.Row) -> ProvenanceRecord:
    return ProvenanceRecord(
        id=row["id"],
        skill_name=row["skill_name"],
        session_id=row["session_id"],
        invoked_at=row["invoked_at"],
        outcome=row["outcome"],
        context_snippet=row["context_snippet"],
        notes=row["notes"],
    )
