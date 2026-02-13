"""F56: Client Pattern Transfer

Identifies similar problems across clients and suggests cross-pollinating solutions.

Usage:
    from wild.pattern_transfer import PatternTransferer

    transferer = PatternTransferer()

    # Find transferable patterns
    patterns = transferer.find_transferable_patterns("Client A", "Client B")

    # Transfer pattern
    transferer.transfer_pattern(pattern_id, "Client B")

    # Rate effectiveness
    transferer.rate_transfer(transfer_id, rating=0.8)
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class PatternTransfer:
    """Pattern transfer record"""
    id: str
    from_project: str
    to_project: str
    pattern_description: str
    transferred_at: int
    effectiveness_rating: Optional[float]
    notes: Optional[str]


class PatternTransferer:
    """Identifies and transfers patterns across projects"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize pattern transferer

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def find_transferable_patterns(
        self,
        from_project: str,
        to_project: str
    ) -> List[Dict]:
        """Find patterns that could transfer between projects

        Args:
            from_project: Source project
            to_project: Target project

        Returns:
            List of transferable patterns (simplified - in real version would analyze memories)
        """
        # Simplified: Check if we've already transferred patterns
        existing = self.db.conn.execute(
            """
            SELECT pattern_description, effectiveness_rating
            FROM pattern_transfers
            WHERE from_project = ? AND effectiveness_rating >= 0.7
            ORDER BY effectiveness_rating DESC
            """,
            (from_project,)
        ).fetchall()

        patterns = []
        for row in existing:
            patterns.append({
                "description": row["pattern_description"],
                "confidence": row["effectiveness_rating"],
                "source": from_project
            })

        return patterns

    def transfer_pattern(
        self,
        from_project: str,
        to_project: str,
        pattern_description: str
    ) -> str:
        """Transfer a pattern to another project

        Args:
            from_project: Source project
            to_project: Target project
            pattern_description: Description of pattern

        Returns:
            Transfer ID
        """
        transfer_id = str(uuid.uuid4())
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            INSERT INTO pattern_transfers
            (id, from_project, to_project, pattern_description, transferred_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (transfer_id, from_project, to_project, pattern_description, timestamp)
        )
        self.db.conn.commit()

        return transfer_id

    def rate_transfer(self, transfer_id: str, rating: float, notes: Optional[str] = None):
        """Rate effectiveness of a transfer

        Args:
            transfer_id: Transfer ID
            rating: Effectiveness rating (0.0-1.0)
            notes: Optional notes
        """
        if not 0.0 <= rating <= 1.0:
            raise ValueError("Rating must be between 0.0 and 1.0")

        self.db.conn.execute(
            """
            UPDATE pattern_transfers
            SET effectiveness_rating = ?, notes = ?
            WHERE id = ?
            """,
            (rating, notes, transfer_id)
        )
        self.db.conn.commit()

    def get_transfer_history(
        self,
        project: Optional[str] = None
    ) -> List[PatternTransfer]:
        """Get transfer history

        Args:
            project: Optional project filter (from or to)

        Returns:
            List of PatternTransfer objects
        """
        if project:
            rows = self.db.conn.execute(
                """
                SELECT id, from_project, to_project, pattern_description, transferred_at, effectiveness_rating, notes
                FROM pattern_transfers
                WHERE from_project = ? OR to_project = ?
                ORDER BY transferred_at DESC
                """,
                (project, project)
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """
                SELECT id, from_project, to_project, pattern_description, transferred_at, effectiveness_rating, notes
                FROM pattern_transfers
                ORDER BY transferred_at DESC
                """
            ).fetchall()

        return [
            PatternTransfer(
                id=row["id"],
                from_project=row["from_project"],
                to_project=row["to_project"],
                pattern_description=row["pattern_description"],
                transferred_at=row["transferred_at"],
                effectiveness_rating=row["effectiveness_rating"],
                notes=row["notes"]
            )
            for row in rows
        ]

    def get_successful_transfers(self, min_rating: float = 0.7) -> List[PatternTransfer]:
        """Get successful transfers

        Args:
            min_rating: Minimum effectiveness rating

        Returns:
            List of successful transfers
        """
        rows = self.db.conn.execute(
            """
            SELECT id, from_project, to_project, pattern_description, transferred_at, effectiveness_rating, notes
            FROM pattern_transfers
            WHERE effectiveness_rating >= ?
            ORDER BY effectiveness_rating DESC
            """,
            (min_rating,)
        ).fetchall()

        return [
            PatternTransfer(
                id=row["id"],
                from_project=row["from_project"],
                to_project=row["to_project"],
                pattern_description=row["pattern_description"],
                transferred_at=row["transferred_at"],
                effectiveness_rating=row["effectiveness_rating"],
                notes=row["notes"]
            )
            for row in rows
        ]
