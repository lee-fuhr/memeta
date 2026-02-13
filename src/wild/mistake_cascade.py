"""F65: Mistake Compounding Detector

Tracks mistake cascades to prevent compound errors.

Usage:
    from wild.mistake_cascade import MistakeCascadeDetector

    detector = MistakeCascadeDetector()

    # Record cascade
    cascade_id = detector.record_cascade(
        root_mistake_id="mistake_123",
        downstream_errors=["error_456", "error_789"]
    )

    # Detect cascade from error
    cascade = detector.detect_cascade("error_456")

    # Analyze root cause
    root = detector.analyze_root_cause("error_456")

    # Get prevention strategy
    strategy = detector.suggest_prevention(cascade_id)
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class MistakeCascade:
    """Mistake cascade record"""
    id: str
    root_mistake_id: str
    downstream_error_ids: List[str]
    cascade_depth: int
    total_cost: str
    prevention_strategy: str
    created_at: int


class MistakeCascadeDetector:
    """Detects and analyzes mistake cascades"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize cascade detector

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def record_cascade(
        self,
        root_mistake_id: str,
        downstream_errors: List[str],
        total_cost: str = "unknown"
    ) -> str:
        """Record a mistake cascade

        Args:
            root_mistake_id: ID of root mistake
            downstream_errors: List of downstream error IDs
            total_cost: Total cost/effort wasted

        Returns:
            Cascade ID
        """
        cascade_id = str(uuid.uuid4())
        timestamp = int(time.time())
        depth = len(downstream_errors)

        # Generate prevention strategy
        prevention = self._generate_prevention_strategy(depth)

        self.db.conn.execute(
            """
            INSERT INTO mistake_cascades
            (id, root_mistake_id, downstream_error_ids, cascade_depth, total_cost, prevention_strategy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cascade_id, root_mistake_id, json.dumps(downstream_errors), depth, total_cost, prevention, timestamp)
        )
        self.db.conn.commit()

        return cascade_id

    def detect_cascade(self, error_id: str) -> Optional[MistakeCascade]:
        """Detect if error is part of a cascade

        Args:
            error_id: Error ID

        Returns:
            MistakeCascade if found, None otherwise
        """
        # Check if error is root
        row = self.db.conn.execute(
            """
            SELECT id, root_mistake_id, downstream_error_ids, cascade_depth, total_cost, prevention_strategy, created_at
            FROM mistake_cascades
            WHERE root_mistake_id = ?
            """,
            (error_id,)
        ).fetchone()

        if row:
            return self._row_to_cascade(row)

        # Check if error is downstream
        rows = self.db.conn.execute(
            """
            SELECT id, root_mistake_id, downstream_error_ids, cascade_depth, total_cost, prevention_strategy, created_at
            FROM mistake_cascades
            """
        ).fetchall()

        for row in rows:
            downstream = json.loads(row["downstream_error_ids"])
            if error_id in downstream:
                return self._row_to_cascade(row)

        return None

    def analyze_root_cause(self, error_id: str) -> Optional[str]:
        """Analyze root cause of error

        Args:
            error_id: Error ID

        Returns:
            Root mistake ID or None
        """
        cascade = self.detect_cascade(error_id)

        if cascade:
            return cascade.root_mistake_id

        return None

    def suggest_prevention(self, cascade_id: str) -> str:
        """Get prevention strategy for cascade

        Args:
            cascade_id: Cascade ID

        Returns:
            Prevention strategy
        """
        row = self.db.conn.execute(
            """
            SELECT prevention_strategy
            FROM mistake_cascades
            WHERE id = ?
            """,
            (cascade_id,)
        ).fetchone()

        if row:
            return row["prevention_strategy"]

        return "No prevention strategy found"

    def get_cascades(
        self,
        min_depth: int = 2
    ) -> List[MistakeCascade]:
        """Get cascades with minimum depth

        Args:
            min_depth: Minimum cascade depth

        Returns:
            List of MistakeCascade objects
        """
        rows = self.db.conn.execute(
            """
            SELECT id, root_mistake_id, downstream_error_ids, cascade_depth, total_cost, prevention_strategy, created_at
            FROM mistake_cascades
            WHERE cascade_depth >= ?
            ORDER BY cascade_depth DESC, created_at DESC
            """,
            (min_depth,)
        ).fetchall()

        return [self._row_to_cascade(row) for row in rows]

    def get_statistics(self) -> Dict:
        """Get cascade statistics

        Returns:
            Dict with statistics
        """
        # Total cascades
        total = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM mistake_cascades"
        ).fetchone()

        # Average depth
        avg_depth = self.db.conn.execute(
            "SELECT AVG(cascade_depth) as avg FROM mistake_cascades"
        ).fetchone()

        # Max depth
        max_depth = self.db.conn.execute(
            "SELECT MAX(cascade_depth) as max FROM mistake_cascades"
        ).fetchone()

        # Depth distribution
        by_depth = self.db.conn.execute(
            """
            SELECT cascade_depth, COUNT(*) as count
            FROM mistake_cascades
            GROUP BY cascade_depth
            ORDER BY cascade_depth
            """
        ).fetchall()

        return {
            "total_cascades": total["count"],
            "average_depth": avg_depth["avg"] or 0,
            "max_depth": max_depth["max"] or 0,
            "by_depth": {row["cascade_depth"]: row["count"] for row in by_depth}
        }

    def _generate_prevention_strategy(self, depth: int) -> str:
        """Generate prevention strategy based on cascade depth

        Args:
            depth: Cascade depth

        Returns:
            Prevention strategy
        """
        if depth == 1:
            return "Catch error early - add validation at entry point"
        elif depth == 2:
            return "Add intermediate checks - validate assumptions between steps"
        elif depth >= 3:
            return "Add circuit breaker - stop execution after first error detected"
        else:
            return "Review error handling - consider defensive programming"

    def _row_to_cascade(self, row) -> MistakeCascade:
        """Convert database row to MistakeCascade"""
        return MistakeCascade(
            id=row["id"],
            root_mistake_id=row["root_mistake_id"],
            downstream_error_ids=json.loads(row["downstream_error_ids"]),
            cascade_depth=row["cascade_depth"],
            total_cost=row["total_cost"],
            prevention_strategy=row["prevention_strategy"],
            created_at=row["created_at"]
        )
