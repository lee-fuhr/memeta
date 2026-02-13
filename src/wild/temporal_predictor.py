"""
Feature 51: Temporal Pattern Prediction

Learns temporal patterns from memory access behavior and predicts needs proactively.

Key capabilities:
- Passive learning from memory access logs (time/day/context)
- Pattern detection (daily, weekly, monthly with min 3 occurrences)
- Proactive prediction based on current time
- Feedback loop (confirm/dismiss to adjust confidence)

Integration: Used by topic-resumption-detector hook and can be queried for predictions
"""

import sqlite3
import json
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


@dataclass
class TemporalPattern:
    """A detected temporal pattern"""
    id: str
    pattern_type: str  # 'daily', 'weekly', 'monthly'
    trigger_condition: str  # e.g., 'Monday 9:00', 'Daily 14:00'
    predicted_need: str  # Description of what's needed
    memory_ids: List[str]  # Memories typically accessed
    confidence: float  # 0.0-1.0
    occurrence_count: int
    dismissed_count: int
    last_confirmed: Optional[int]
    last_dismissed: Optional[int]


class TemporalPatternPredictor:
    """
    Learns temporal patterns from memory access behavior.
    Predicts likely-needed memories based on time/context.

    Thresholds:
    - Min occurrences to detect pattern: 3
    - Min confidence to surface prediction: 0.7
    - Confidence adjustment: +0.05 on confirm, -0.1 on dismiss
    """

    # Detection thresholds
    MIN_OCCURRENCES = 3
    CONFIDENCE_THRESHOLD = 0.7
    CONFIRM_BOOST = 0.05
    DISMISS_PENALTY = 0.1

    def __init__(self, db_path: str = None):
        """
        Initialize predictor with database.

        Args:
            db_path: Path to intelligence.db (default: project root)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"

        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        """Create tables if not exist."""
        with get_connection(self.db_path) as conn:
            # Temporal patterns table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS temporal_patterns (
                    id TEXT PRIMARY KEY,
                    pattern_type TEXT NOT NULL,
                    trigger_condition TEXT NOT NULL,
                    predicted_need TEXT NOT NULL,
                    memory_ids TEXT,
                    confidence REAL DEFAULT 0.5,
                    occurrence_count INTEGER DEFAULT 0,
                    dismissed_count INTEGER DEFAULT 0,
                    last_confirmed INTEGER,
                    last_dismissed INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # Memory access log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_access_log (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    accessed_at INTEGER NOT NULL,
                    access_type TEXT NOT NULL,
                    day_of_week INTEGER,
                    hour_of_day INTEGER,
                    session_id TEXT,
                    context_keywords TEXT,
                    created_at INTEGER NOT NULL
                )
            """)

            # Indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_pattern_type
                    ON temporal_patterns(pattern_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_trigger
                    ON temporal_patterns(trigger_condition)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_confidence
                    ON temporal_patterns(confidence DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_memory
                    ON memory_access_log(memory_id, accessed_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_temporal
                    ON memory_access_log(day_of_week, hour_of_day)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_access_session
                    ON memory_access_log(session_id)
            """)

            conn.commit()

    def log_memory_access(
        self,
        memory_id: str,
        access_type: str,
        context_keywords: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        Log a memory access event.

        Args:
            memory_id: Memory that was accessed
            access_type: How it was accessed (search/direct/predicted/hook)
            context_keywords: Surrounding context words
            session_id: Current session

        Returns:
            Log entry ID
        """
        now = int(datetime.now().timestamp())
        dt = datetime.now()

        # Include microseconds for uniqueness
        import time
        unique_str = f"{memory_id}-{now}-{time.time()}-{access_type}"
        log_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO memory_access_log
                (id, memory_id, accessed_at, access_type, day_of_week,
                 hour_of_day, session_id, context_keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id,
                memory_id,
                now,
                access_type,
                dt.weekday(),  # 0=Monday in Python
                dt.hour,
                session_id,
                json.dumps(context_keywords or []),
                now
            ))
            conn.commit()

        return log_id

    def detect_patterns(self, min_occurrences: int = None) -> List[Dict]:
        """
        Detect recurring temporal patterns from access logs.

        Args:
            min_occurrences: Minimum occurrences to establish pattern (default: 3)

        Returns:
            List of detected patterns
        """
        if min_occurrences is None:
            min_occurrences = self.MIN_OCCURRENCES

        with get_connection(self.db_path) as conn:
            # Query access logs grouped by memory_id + day_of_week + hour_of_day
            cursor = conn.execute("""
                SELECT
                    memory_id,
                    day_of_week,
                    hour_of_day,
                    COUNT(*) as occurrence_count
                FROM memory_access_log
                GROUP BY memory_id, day_of_week, hour_of_day
                HAVING COUNT(*) >= ?
            """, (min_occurrences,))

            patterns = []
            now = int(datetime.now().timestamp())
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

            for row in cursor:
                memory_id, dow, hour, count = row

                # Classify pattern_type
                if dow is not None and hour is not None:
                    pattern_type = 'weekly'  # Specific day + hour
                    trigger = f"{days[dow]} {hour}:00"
                elif hour is not None:
                    pattern_type = 'daily'  # Same hour every day
                    trigger = f"Daily {hour}:00"
                else:
                    pattern_type = 'monthly'  # Less specific
                    trigger = 'Monthly pattern'

                # Calculate confidence: min(1.0, count / (count + 2))
                confidence = min(1.0, count / (count + 2))

                # Generate pattern_id
                pattern_id = hashlib.md5(
                    f"{pattern_type}-{trigger}-{memory_id}".encode()
                ).hexdigest()[:16]

                # CREATE OR REPLACE pattern
                conn.execute("""
                    INSERT OR REPLACE INTO temporal_patterns
                    (id, pattern_type, trigger_condition, predicted_need,
                     memory_ids, confidence, occurrence_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pattern_id,
                    pattern_type,
                    trigger,
                    f"Memory {memory_id[:8]}...",  # Placeholder
                    json.dumps([memory_id]),
                    confidence,
                    count,
                    now,
                    now
                ))

                patterns.append({
                    'id': pattern_id,
                    'pattern_type': pattern_type,
                    'trigger_condition': trigger,
                    'memory_ids': [memory_id],
                    'confidence': confidence,
                    'occurrence_count': count
                })

            conn.commit()
            return patterns

    def predict_needs(
        self,
        current_time: Optional[datetime] = None,
        confidence_threshold: float = None
    ) -> List[Dict]:
        """
        Predict likely-needed memories based on current time/context.

        Args:
            current_time: Time to predict for (default: now)
            confidence_threshold: Min confidence to surface prediction (default: 0.7)

        Returns:
            List of predictions: [
                {
                    'pattern_id': '...',
                    'predicted_need': 'Connection Lab context',
                    'memory_ids': ['mem1', 'mem2'],
                    'confidence': 0.85,
                    'trigger_condition': 'Monday 9:00'
                }
            ]
        """
        if current_time is None:
            current_time = datetime.now()
        if confidence_threshold is None:
            confidence_threshold = self.CONFIDENCE_THRESHOLD

        current_dow = current_time.weekday()  # 0=Monday
        current_hour = current_time.hour
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        with get_connection(self.db_path) as conn:
            # Find patterns matching current day_of_week + hour_of_day
            cursor = conn.execute("""
                SELECT id, pattern_type, trigger_condition, predicted_need,
                       memory_ids, confidence
                FROM temporal_patterns
                WHERE confidence >= ?
            """, (confidence_threshold,))

            predictions = []
            for row in cursor:
                pattern_id, pattern_type, trigger, predicted_need, memory_ids_json, confidence = row

                # Parse trigger_condition and match against current time
                match = False
                if pattern_type == 'weekly':
                    # Extract day + hour from trigger like "Monday 9:00"
                    for i, day in enumerate(days):
                        if trigger.startswith(day):
                            trigger_hour = int(trigger.split()[1].split(':')[0])
                            if i == current_dow and trigger_hour == current_hour:
                                match = True
                elif pattern_type == 'daily':
                    # Extract hour from trigger like "Daily 9:00"
                    trigger_hour = int(trigger.split()[1].split(':')[0])
                    if trigger_hour == current_hour:
                        match = True

                if match:
                    predictions.append({
                        'pattern_id': pattern_id,
                        'predicted_need': predicted_need,
                        'memory_ids': json.loads(memory_ids_json),
                        'confidence': confidence,
                        'trigger_condition': trigger
                    })

            return predictions

    def confirm_prediction(self, pattern_id: str):
        """
        Record that prediction was correct.
        Increases confidence.
        """
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE temporal_patterns
                SET
                    occurrence_count = occurrence_count + 1,
                    last_confirmed = ?,
                    confidence = MIN(1.0, confidence + ?),
                    updated_at = ?
                WHERE id = ?
            """, (now, self.CONFIRM_BOOST, now, pattern_id))
            conn.commit()

    def dismiss_prediction(self, pattern_id: str):
        """
        Record that prediction was incorrect.
        Decreases confidence.
        """
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE temporal_patterns
                SET
                    dismissed_count = dismissed_count + 1,
                    last_dismissed = ?,
                    confidence = MAX(0.0, confidence - ?),
                    updated_at = ?
                WHERE id = ?
            """, (now, self.DISMISS_PENALTY, now, pattern_id))
            conn.commit()

    def get_pattern_stats(self) -> Dict:
        """
        Get pattern detection statistics.

        Returns:
            {
                'total_patterns': 42,
                'active_patterns': 28,  # confidence > 0.7
                'total_accesses_logged': 1523,
                'patterns_by_type': {'daily': 10, 'weekly': 18, ...}
            }
        """
        with get_connection(self.db_path) as conn:
            # Total patterns
            total = conn.execute(
                "SELECT COUNT(*) FROM temporal_patterns"
            ).fetchone()[0]

            # Active patterns (confidence > 0.7)
            active = conn.execute(
                "SELECT COUNT(*) FROM temporal_patterns WHERE confidence >= ?",
                (self.CONFIDENCE_THRESHOLD,)
            ).fetchone()[0]

            # Total accesses logged
            accesses = conn.execute(
                "SELECT COUNT(*) FROM memory_access_log"
            ).fetchone()[0]

            # Patterns by type
            cursor = conn.execute("""
                SELECT pattern_type, COUNT(*)
                FROM temporal_patterns
                GROUP BY pattern_type
            """)

            patterns_by_type = {row[0]: row[1] for row in cursor}

            return {
                'total_patterns': total,
                'active_patterns': active,
                'total_accesses_logged': accesses,
                'patterns_by_type': patterns_by_type
            }
