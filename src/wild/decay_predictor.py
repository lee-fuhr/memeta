"""F60: Context Decay Prediction

Predicts when context becomes stale before it happens.

Usage:
    from wild.decay_predictor import DecayPredictor

    predictor = DecayPredictor()

    # Predict decay
    decay_date = predictor.predict_decay("memory_id_123")

    # Get memories becoming stale
    stale_soon = predictor.get_memories_becoming_stale(days_ahead=7)

    # Mark as refreshed
    predictor.refresh_memory("memory_id_123")
"""

import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class DecayPrediction:
    """Decay prediction record"""
    id: str
    memory_id: str
    predicted_stale_at: int
    confidence: float
    reason: str
    reviewed_at: Optional[int]


class DecayPredictor:
    """Predicts context staleness"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize decay predictor

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def predict_decay(
        self,
        memory_id: str,
        reason: str = "project_inactive",
        days_until_stale: int = 90
    ) -> datetime:
        """Predict when memory becomes stale

        Args:
            memory_id: Memory ID
            reason: Reason for staleness (project_inactive, superseded, outdated_source)
            days_until_stale: Days until predicted stale

        Returns:
            Predicted stale date
        """
        timestamp = int(time.time())
        predicted_stale_at = timestamp + (days_until_stale * 86400)

        # Calculate confidence based on reason
        confidence_map = {
            "project_inactive": 0.7,
            "superseded": 0.9,
            "outdated_source": 0.8
        }
        confidence = confidence_map.get(reason, 0.6)

        # Check if prediction exists
        existing = self.db.conn.execute(
            "SELECT id FROM decay_predictions WHERE memory_id = ?",
            (memory_id,)
        ).fetchone()

        if existing:
            # Update existing
            self.db.conn.execute(
                """
                UPDATE decay_predictions
                SET predicted_stale_at = ?, confidence = ?, reason = ?
                WHERE memory_id = ?
                """,
                (predicted_stale_at, confidence, reason, memory_id)
            )
        else:
            # Create new
            prediction_id = str(uuid.uuid4())
            self.db.conn.execute(
                """
                INSERT INTO decay_predictions
                (id, memory_id, predicted_stale_at, confidence, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (prediction_id, memory_id, predicted_stale_at, confidence, reason)
            )

        self.db.conn.commit()

        return datetime.fromtimestamp(predicted_stale_at)

    def get_memories_becoming_stale(self, days_ahead: int = 7) -> List[DecayPrediction]:
        """Get memories predicted to become stale soon

        Args:
            days_ahead: Look ahead window in days

        Returns:
            List of DecayPrediction objects
        """
        now = int(time.time())
        future = now + (days_ahead * 86400)

        rows = self.db.conn.execute(
            """
            SELECT id, memory_id, predicted_stale_at, confidence, reason, reviewed_at
            FROM decay_predictions
            WHERE predicted_stale_at BETWEEN ? AND ?
            AND reviewed_at IS NULL
            ORDER BY predicted_stale_at ASC
            """,
            (now, future)
        ).fetchall()

        return [
            DecayPrediction(
                id=row["id"],
                memory_id=row["memory_id"],
                predicted_stale_at=row["predicted_stale_at"],
                confidence=row["confidence"],
                reason=row["reason"],
                reviewed_at=row["reviewed_at"]
            )
            for row in rows
        ]

    def refresh_memory(self, memory_id: str):
        """Mark memory as refreshed

        Args:
            memory_id: Memory ID
        """
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            UPDATE decay_predictions
            SET reviewed_at = ?
            WHERE memory_id = ?
            """,
            (timestamp, memory_id)
        )
        self.db.conn.commit()

    def get_prediction(self, memory_id: str) -> Optional[DecayPrediction]:
        """Get decay prediction for memory

        Args:
            memory_id: Memory ID

        Returns:
            DecayPrediction or None
        """
        row = self.db.conn.execute(
            """
            SELECT id, memory_id, predicted_stale_at, confidence, reason, reviewed_at
            FROM decay_predictions
            WHERE memory_id = ?
            """,
            (memory_id,)
        ).fetchone()

        if row:
            return DecayPrediction(
                id=row["id"],
                memory_id=row["memory_id"],
                predicted_stale_at=row["predicted_stale_at"],
                confidence=row["confidence"],
                reason=row["reason"],
                reviewed_at=row["reviewed_at"]
            )

        return None

    def get_statistics(self) -> Dict:
        """Get decay prediction statistics

        Returns:
            Dict with statistics
        """
        # Total predictions
        total = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM decay_predictions"
        ).fetchone()

        # By reason
        by_reason = self.db.conn.execute(
            """
            SELECT reason, COUNT(*) as count
            FROM decay_predictions
            GROUP BY reason
            """
        ).fetchall()

        # Reviewed vs unreviewed
        reviewed = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM decay_predictions WHERE reviewed_at IS NOT NULL"
        ).fetchone()

        return {
            "total_predictions": total["count"],
            "by_reason": {row["reason"]: row["count"] for row in by_reason},
            "reviewed": reviewed["count"],
            "unreviewed": total["count"] - reviewed["count"]
        }
