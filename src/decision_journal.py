"""Decision journal — Feature 47: Track decisions and outcomes.

Provides DecisionStore (SQLite-backed) for persistent decision tracking,
plus legacy module-level wrapper functions for backward compatibility.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class Decision:
    """A recorded decision with optional outcome."""
    id: int
    decision_text: str
    options_considered: str  # JSON string of list
    chosen_option: str
    rationale: str
    files_affected: str  # JSON string of list
    session_id: str
    outcome: Optional[str] = None
    success: Optional[bool] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DecisionStore:
    """SQLite-backed store for tracking decisions and their outcomes."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Create decisions table if not exists."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_text TEXT NOT NULL,
                options_considered TEXT NOT NULL,
                chosen_option TEXT NOT NULL,
                rationale TEXT NOT NULL,
                files_affected TEXT NOT NULL DEFAULT '[]',
                session_id TEXT NOT NULL DEFAULT 'unknown',
                outcome TEXT,
                success BOOLEAN,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at)"
        )
        self._conn.commit()

    def record_decision(
        self,
        decision_text: str,
        options_considered: list[str],
        chosen_option: str,
        rationale: str,
        files_affected: list[str] | None = None,
        session_id: str = "unknown",
    ) -> int:
        """Record a decision. Returns decision ID."""
        cursor = self._conn.execute(
            "INSERT INTO decisions (decision_text, options_considered, chosen_option, "
            "rationale, files_affected, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision_text,
                json.dumps(options_considered),
                chosen_option,
                rationale,
                json.dumps(files_affected or []),
                session_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def record_outcome(self, decision_id: int, outcome: str, success: bool) -> bool:
        """Record outcome for a decision. Returns True if found and updated."""
        cursor = self._conn.execute(
            "UPDATE decisions SET outcome = ?, success = ? WHERE id = ?",
            (outcome, success, decision_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_decisions_for_session(self, session_id: str) -> list[Decision]:
        """Get all decisions from a specific session."""
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def get_decisions_for_file(self, file_path: str) -> list[Decision]:
        """Get decisions affecting a file. Exact match + prefix match (directory)."""
        rows = self._conn.execute(
            "SELECT * FROM decisions ORDER BY id"
        ).fetchall()
        results = []
        for row in rows:
            files = json.loads(row["files_affected"])
            for f in files:
                if f == file_path or f.startswith(file_path) or file_path.startswith(f):
                    results.append(self._row_to_decision(row))
                    break
        return results

    def get_recent_decisions(self, days_back: int = 30) -> list[Decision]:
        """Get decisions from last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE created_at >= ? ORDER BY id",
            (cutoff,),
        ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    def learn_from_decisions(self) -> dict:
        """Analyze decision patterns.

        Returns dict with keys: total, successful, success_rate, pending_outcome.
        Maintains same shape as old stub for backward compat (total, successful, success_rate)
        plus new key pending_outcome.
        """
        rows = self._conn.execute("SELECT outcome, success FROM decisions").fetchall()
        total = len(rows)
        successful = sum(1 for r in rows if r["success"] is not None and r["success"])
        pending = sum(1 for r in rows if r["outcome"] is None)
        return {
            "total": total,
            "successful": successful,
            "success_rate": successful / total if total else 0,
            "pending_outcome": pending,
        }

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        """Convert a database row to a Decision dataclass."""
        return Decision(
            id=row["id"],
            decision_text=row["decision_text"],
            options_considered=row["options_considered"],
            chosen_option=row["chosen_option"],
            rationale=row["rationale"],
            files_affected=row["files_affected"],
            session_id=row["session_id"],
            outcome=row["outcome"],
            success=bool(row["success"]) if row["success"] is not None else None,
            created_at=row["created_at"],
        )


# BACKWARD COMPAT: Keep module-level wrapper functions


def record_decision(decision, options_considered, chosen_option, rationale):
    """Legacy wrapper -- returns dict (not persisted, matches old API)."""
    return {
        "type": "decision",
        "decision": decision,
        "options": options_considered,
        "chosen": chosen_option,
        "rationale": rationale,
        "timestamp": datetime.now().isoformat(),
        "outcome": None,
    }


def track_outcome(decision_id, outcome, success):
    """Legacy wrapper."""
    return {
        "decision_id": decision_id,
        "outcome": outcome,
        "success": success,
        "recorded_at": datetime.now().isoformat(),
    }


def learn_from_decisions(decisions):
    """Legacy wrapper -- works on list of dicts."""
    successful = [
        d for d in decisions
        if isinstance(d.get("outcome"), dict) and d["outcome"].get("success")
    ]
    return {
        "total": len(decisions),
        "successful": len(successful),
        "success_rate": len(successful) / len(decisions) if decisions else 0,
    }
