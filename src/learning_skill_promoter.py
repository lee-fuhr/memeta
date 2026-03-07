"""Learning-to-SKILL.md pipeline.

Tracks which learnings appear in session-start briefings.
When a learning surfaces in 3+ distinct sessions, generates a proposal
to promote it as a permanent note in the relevant SKILL.md.

Closes the loop: experience (memory/briefings) → capability (skill docs).
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_DEFAULT_MIN_APPEARANCES = 3


class ProposalStatus(Enum):
    PENDING = "pending"
    APPLIED = "applied"
    DISMISSED = "dismissed"


@dataclass
class LearningAppearance:
    learning_id: str
    skill_name: str
    appearance_count: int
    latest_content: str = ""


@dataclass
class PromotionProposal:
    proposal_id: int
    learning_id: str
    skill_name: str
    proposed_text: str
    status: ProposalStatus = ProposalStatus.PENDING


_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_briefing_appearances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    briefing_date TEXT NOT NULL,
    learning_content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(learning_id, session_id)
);

CREATE TABLE IF NOT EXISTS learning_promotion_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    proposed_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(learning_id)
);
"""


class LearningSkillPromoter:
    """Track learning briefing appearances and generate SKILL.md promotion proposals."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            from memory_system.config import MemorySystemConfig
            db_path = MemorySystemConfig().intelligence_db
        self._db_path = Path(db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # record_appearance
    # ------------------------------------------------------------------

    def record_appearance(
        self,
        learning_id: str,
        skill_name: str,
        session_id: str,
        briefing_date: Union[str, date],
        learning_content: str = "",
    ) -> int:
        """Record that a learning appeared in a session's briefing.

        Deduplicates on (learning_id, session_id) — the same learning
        can only be counted once per session.

        Returns the row id (or existing row id if already recorded).
        """
        date_str = briefing_date.isoformat() if isinstance(briefing_date, date) else briefing_date
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO learning_briefing_appearances
                        (learning_id, skill_name, session_id, briefing_date, learning_content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (learning_id, skill_name, session_id, date_str, learning_content),
                )
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Duplicate (learning_id, session_id) — return existing id
                row = conn.execute(
                    "SELECT id FROM learning_briefing_appearances WHERE learning_id=? AND session_id=?",
                    (learning_id, session_id),
                ).fetchone()
                return row["id"]

    # ------------------------------------------------------------------
    # get_promotion_candidates
    # ------------------------------------------------------------------

    def get_promotion_candidates(
        self, min_appearances: int = _DEFAULT_MIN_APPEARANCES
    ) -> list[LearningAppearance]:
        """Return learnings that have appeared in >= min_appearances distinct sessions
        and have not yet been proposed for promotion.

        Sorted by appearance_count descending.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.learning_id,
                    a.skill_name,
                    COUNT(DISTINCT a.session_id) AS appearance_count,
                    a.learning_content AS latest_content
                FROM learning_briefing_appearances a
                LEFT JOIN learning_promotion_proposals p
                    ON a.learning_id = p.learning_id
                WHERE p.id IS NULL
                GROUP BY a.learning_id, a.skill_name
                HAVING appearance_count >= ?
                ORDER BY appearance_count DESC
                """,
                (min_appearances,),
            ).fetchall()
        return [
            LearningAppearance(
                learning_id=r["learning_id"],
                skill_name=r["skill_name"],
                appearance_count=r["appearance_count"],
                latest_content=r["latest_content"] or "",
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # generate_proposal
    # ------------------------------------------------------------------

    def generate_proposal(
        self,
        learning_id: str,
        skill_name: str,
        learning_content: str,
    ) -> PromotionProposal:
        """Create a SKILL.md promotion proposal for this learning.

        Idempotent: if a proposal already exists for this learning_id,
        return the existing one unchanged.
        """
        proposed_text = self.format_skill_md_addition(
            skill_name=skill_name,
            learning_content=learning_content,
            appearance_count=self._count_appearances(learning_id),
        )
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO learning_promotion_proposals
                        (learning_id, skill_name, proposed_text)
                    VALUES (?, ?, ?)
                    """,
                    (learning_id, skill_name, proposed_text),
                )
                proposal_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id, proposed_text, status FROM learning_promotion_proposals WHERE learning_id=?",
                    (learning_id,),
                ).fetchone()
                return PromotionProposal(
                    proposal_id=row["id"],
                    learning_id=learning_id,
                    skill_name=skill_name,
                    proposed_text=row["proposed_text"],
                    status=ProposalStatus(row["status"]),
                )
        return PromotionProposal(
            proposal_id=proposal_id,
            learning_id=learning_id,
            skill_name=skill_name,
            proposed_text=proposed_text,
            status=ProposalStatus.PENDING,
        )

    # ------------------------------------------------------------------
    # get_pending_proposals
    # ------------------------------------------------------------------

    def get_pending_proposals(self) -> list[PromotionProposal]:
        """Return all proposals awaiting review."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, learning_id, skill_name, proposed_text, status "
                "FROM learning_promotion_proposals WHERE status='pending'"
            ).fetchall()
        return [
            PromotionProposal(
                proposal_id=r["id"],
                learning_id=r["learning_id"],
                skill_name=r["skill_name"],
                proposed_text=r["proposed_text"],
                status=ProposalStatus(r["status"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # mark_applied / mark_dismissed
    # ------------------------------------------------------------------

    def mark_applied(self, proposal_id: int) -> bool:
        return self._set_status(proposal_id, ProposalStatus.APPLIED)

    def mark_dismissed(self, proposal_id: int) -> bool:
        return self._set_status(proposal_id, ProposalStatus.DISMISSED)

    def _set_status(self, proposal_id: int, status: ProposalStatus) -> bool:
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE learning_promotion_proposals SET status=? WHERE id=?",
                (status.value, proposal_id),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # format_skill_md_addition
    # ------------------------------------------------------------------

    def format_skill_md_addition(
        self,
        skill_name: str,
        learning_content: str,
        appearance_count: int,
    ) -> str:
        """Render the markdown snippet to add to a SKILL.md."""
        return (
            f"## Promoted from briefings\n\n"
            f"**Skill:** {skill_name}  \n"
            f"**Note:** {learning_content}  \n"
            f"**Why:** Surfaced in {appearance_count} briefing session(s) — "
            f"recurring enough to be a permanent reminder.\n"
        )

    # ------------------------------------------------------------------
    # auto_promote_pending
    # ------------------------------------------------------------------

    def auto_promote_pending(
        self, min_appearances: int = _DEFAULT_MIN_APPEARANCES
    ) -> int:
        """Generate proposals for all candidates meeting the threshold.

        Returns the number of new proposals created.
        """
        candidates = self.get_promotion_candidates(min_appearances=min_appearances)
        count = 0
        for candidate in candidates:
            self.generate_proposal(
                learning_id=candidate.learning_id,
                skill_name=candidate.skill_name,
                learning_content=candidate.latest_content,
            )
            count += 1
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_appearances(self, learning_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM learning_briefing_appearances WHERE learning_id=?",
                (learning_id,),
            ).fetchone()
        return row[0] if row else 0
