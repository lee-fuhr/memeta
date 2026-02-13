"""F58: Decision Regret Detection

Tracks decisions and detects regret patterns to warn before repeating mistakes.

Usage:
    from wild.regret_detector import RegretDetector

    detector = RegretDetector()

    # Record decision
    detector.record_decision("Use framework X", alternative="Use framework Y")

    # Detect regret pattern
    pattern = detector.detect_regret_pattern("Use framework X")

    # Get warning
    warning = detector.warn_about_decision("Use framework X")
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class DecisionOutcome:
    """Decision outcome record"""
    id: str
    decision_content: str
    alternative: Optional[str]
    outcome: str  # good, bad, neutral
    regret_detected: bool
    created_at: int
    corrected_at: Optional[int]


@dataclass
class RegretPattern:
    """Detected regret pattern"""
    decision: str
    occurrence_count: int
    correction_count: int
    regret_rate: float


class RegretDetector:
    """Detects decision regret patterns"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize regret detector

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def record_decision(
        self,
        content: str,
        alternative: Optional[str] = None,
        outcome: str = "neutral"
    ) -> str:
        """Record a decision

        Args:
            content: Decision content
            alternative: What was chosen against
            outcome: Outcome (good, bad, neutral)

        Returns:
            Decision ID
        """
        if outcome not in ("good", "bad", "neutral"):
            raise ValueError("Outcome must be good, bad, or neutral")

        decision_id = str(uuid.uuid4())
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            INSERT INTO decision_outcomes
            (id, decision_content, alternative, outcome, regret_detected, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (decision_id, content, alternative, outcome, False, timestamp)
        )
        self.db.conn.commit()

        return decision_id

    def mark_regret(self, decision_id: str):
        """Mark a decision as regretted

        Args:
            decision_id: Decision ID
        """
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            UPDATE decision_outcomes
            SET regret_detected = TRUE, corrected_at = ?
            WHERE id = ?
            """,
            (timestamp, decision_id)
        )
        self.db.conn.commit()

    def detect_regret_pattern(self, decision: str) -> Optional[RegretPattern]:
        """Detect regret pattern for similar decisions

        Args:
            decision: Decision content to check

        Returns:
            RegretPattern if pattern detected, None otherwise
        """
        # Find similar decisions (exact match for MVP)
        rows = self.db.conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN regret_detected THEN 1 ELSE 0 END) as regrets
            FROM decision_outcomes
            WHERE decision_content LIKE ?
            """,
            (f"%{decision}%",)
        ).fetchone()

        total = rows["total"]
        regrets = rows["regrets"] or 0

        if total >= 2 and regrets > 0:
            regret_rate = regrets / total

            if regret_rate >= 0.5:  # 50% regret rate threshold
                return RegretPattern(
                    decision=decision,
                    occurrence_count=total,
                    correction_count=regrets,
                    regret_rate=regret_rate
                )

        return None

    def warn_about_decision(self, decision: str) -> Optional[str]:
        """Get warning if decision has regret pattern

        Args:
            decision: Decision content

        Returns:
            Warning message or None
        """
        pattern = self.detect_regret_pattern(decision)

        if pattern:
            return (
                f"WARNING: You've made similar decisions {pattern.occurrence_count} times "
                f"and regretted it {pattern.correction_count} times ({pattern.regret_rate:.0%} regret rate). "
                f"Consider the alternative carefully."
            )

        return None

    def get_decision_history(
        self,
        include_regrets_only: bool = False
    ) -> List[DecisionOutcome]:
        """Get decision history

        Args:
            include_regrets_only: If True, only return regretted decisions

        Returns:
            List of DecisionOutcome objects
        """
        if include_regrets_only:
            rows = self.db.conn.execute(
                """
                SELECT id, decision_content, alternative, outcome, regret_detected, created_at, corrected_at
                FROM decision_outcomes
                WHERE regret_detected = TRUE
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """
                SELECT id, decision_content, alternative, outcome, regret_detected, created_at, corrected_at
                FROM decision_outcomes
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            DecisionOutcome(
                id=row["id"],
                decision_content=row["decision_content"],
                alternative=row["alternative"],
                outcome=row["outcome"],
                regret_detected=bool(row["regret_detected"]),
                created_at=row["created_at"],
                corrected_at=row["corrected_at"]
            )
            for row in rows
        ]

    def get_regret_statistics(self) -> Dict:
        """Get statistics about decision regrets

        Returns:
            Dict with statistics
        """
        row = self.db.conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN regret_detected THEN 1 ELSE 0 END) as regrets,
                   SUM(CASE WHEN outcome = 'good' THEN 1 ELSE 0 END) as good,
                   SUM(CASE WHEN outcome = 'bad' THEN 1 ELSE 0 END) as bad
            FROM decision_outcomes
            """
        ).fetchone()

        total = row["total"]
        regrets = row["regrets"] or 0

        return {
            "total_decisions": total,
            "regrets": regrets,
            "good_outcomes": row["good"] or 0,
            "bad_outcomes": row["bad"] or 0,
            "regret_rate": regrets / total if total > 0 else 0.0
        }
