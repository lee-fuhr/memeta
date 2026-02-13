"""F53: Energy-Aware Scheduling

Tracks energy patterns and suggests optimal times for different cognitive loads.

Usage:
    from wild.energy_scheduler import EnergyScheduler

    scheduler = EnergyScheduler()

    # Record energy level
    scheduler.record_energy_level(hour=9, level="high")

    # Get current prediction
    prediction = scheduler.get_current_energy_prediction()

    # Suggest tasks for current time
    tasks = scheduler.suggest_task_for_current_time()
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class EnergyPattern:
    """Energy pattern data"""
    id: str
    hour_of_day: int  # 0-23
    day_of_week: Optional[int]  # 0-6 (Mon-Sun) or None for all days
    energy_level: str  # high, medium, low
    confidence: float
    sample_count: int
    updated_at: int


@dataclass
class TaskComplexity:
    """Task complexity definition"""
    task_type: str
    cognitive_load: str  # high, medium, low
    optimal_energy: str  # high, medium, low
    examples: List[str]


class EnergyScheduler:
    """Learns energy patterns and suggests optimal task scheduling"""

    # Default task complexity mappings
    DEFAULT_TASK_COMPLEXITIES = {
        "deep_work": TaskComplexity(
            task_type="deep_work",
            cognitive_load="high",
            optimal_energy="high",
            examples=["Complex coding", "System design", "Strategic planning"]
        ),
        "writing": TaskComplexity(
            task_type="writing",
            cognitive_load="high",
            optimal_energy="high",
            examples=["Technical writing", "Proposals", "Documentation"]
        ),
        "meetings": TaskComplexity(
            task_type="meetings",
            cognitive_load="medium",
            optimal_energy="medium",
            examples=["Team sync", "Client calls", "1-on-1s"]
        ),
        "code_review": TaskComplexity(
            task_type="code_review",
            cognitive_load="medium",
            optimal_energy="medium",
            examples=["PR review", "Code audits", "Testing"]
        ),
        "admin": TaskComplexity(
            task_type="admin",
            cognitive_load="low",
            optimal_energy="low",
            examples=["Email triage", "Expense reports", "Calendar management"]
        ),
        "learning": TaskComplexity(
            task_type="learning",
            cognitive_load="high",
            optimal_energy="high",
            examples=["Reading papers", "Tutorials", "Research"]
        )
    }

    def __init__(self, db_path: Optional[str] = None):
        """Initialize energy scheduler

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)
        self._init_default_tasks()

    def _init_default_tasks(self):
        """Initialize default task complexity mappings if not present"""
        for task_type, complexity in self.DEFAULT_TASK_COMPLEXITIES.items():
            # Check if exists
            existing = self.db.conn.execute(
                "SELECT COUNT(*) as count FROM task_complexity WHERE task_type = ?",
                (task_type,)
            ).fetchone()

            if existing["count"] == 0:
                self.db.conn.execute(
                    """
                    INSERT INTO task_complexity
                    (task_type, cognitive_load, optimal_energy, examples)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_type, complexity.cognitive_load, complexity.optimal_energy,
                     json.dumps(complexity.examples))
                )
        self.db.conn.commit()

    def record_energy_level(self, hour: int, level: str, day_of_week: Optional[int] = None):
        """Record energy level for a specific time

        Args:
            hour: Hour of day (0-23)
            level: Energy level (high, medium, low)
            day_of_week: Optional day of week (0=Mon, 6=Sun)
        """
        if not 0 <= hour <= 23:
            raise ValueError("Hour must be between 0 and 23")
        if level not in ("high", "medium", "low"):
            raise ValueError("Level must be high, medium, or low")
        if day_of_week is not None and not 0 <= day_of_week <= 6:
            raise ValueError("Day of week must be between 0 and 6")

        # Check if pattern exists
        pattern = self.db.conn.execute(
            """
            SELECT id, sample_count, confidence
            FROM energy_patterns
            WHERE hour_of_day = ? AND day_of_week IS ?
            """,
            (hour, day_of_week)
        ).fetchone()

        timestamp = int(time.time())

        if pattern:
            # Update existing pattern
            new_count = pattern["sample_count"] + 1
            # Increase confidence with more samples (max 1.0)
            new_confidence = min(1.0, pattern["confidence"] + 0.1)

            self.db.conn.execute(
                """
                UPDATE energy_patterns
                SET energy_level = ?, confidence = ?, sample_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (level, new_confidence, new_count, timestamp, pattern["id"])
            )
        else:
            # Create new pattern
            pattern_id = str(uuid.uuid4())
            self.db.conn.execute(
                """
                INSERT INTO energy_patterns
                (id, hour_of_day, day_of_week, energy_level, confidence, sample_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (pattern_id, hour, day_of_week, level, 0.5, 1, timestamp)
            )

        self.db.conn.commit()

    def get_current_energy_prediction(self) -> str:
        """Get predicted energy level for current time

        Returns:
            Predicted energy level (high, medium, low) or "unknown"
        """
        now = datetime.now()
        hour = now.hour
        day = now.weekday()  # 0=Mon, 6=Sun

        # Try day-specific pattern first
        pattern = self.db.conn.execute(
            """
            SELECT energy_level, confidence
            FROM energy_patterns
            WHERE hour_of_day = ? AND day_of_week = ?
            ORDER BY confidence DESC, sample_count DESC
            LIMIT 1
            """,
            (hour, day)
        ).fetchone()

        # Fall back to general pattern for this hour
        if not pattern:
            pattern = self.db.conn.execute(
                """
                SELECT energy_level, confidence
                FROM energy_patterns
                WHERE hour_of_day = ? AND day_of_week IS NULL
                ORDER BY confidence DESC, sample_count DESC
                LIMIT 1
                """,
                (hour,)
            ).fetchone()

        if pattern and pattern["confidence"] >= 0.6:
            return pattern["energy_level"]

        return "unknown"

    def suggest_task_for_current_time(self) -> List[str]:
        """Suggest task types optimal for current time

        Returns:
            List of task type names
        """
        energy = self.get_current_energy_prediction()

        if energy == "unknown":
            # Default to medium complexity
            energy = "medium"

        # Get tasks matching energy level
        tasks = self.db.conn.execute(
            """
            SELECT task_type
            FROM task_complexity
            WHERE optimal_energy = ?
            """,
            (energy,)
        ).fetchall()

        return [task["task_type"] for task in tasks]

    def get_energy_patterns(self, hour: Optional[int] = None) -> List[EnergyPattern]:
        """Get energy patterns

        Args:
            hour: Optional hour to filter by

        Returns:
            List of EnergyPattern objects
        """
        if hour is not None:
            rows = self.db.conn.execute(
                """
                SELECT id, hour_of_day, day_of_week, energy_level, confidence, sample_count, updated_at
                FROM energy_patterns
                WHERE hour_of_day = ?
                ORDER BY day_of_week, confidence DESC
                """,
                (hour,)
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """
                SELECT id, hour_of_day, day_of_week, energy_level, confidence, sample_count, updated_at
                FROM energy_patterns
                ORDER BY hour_of_day, day_of_week, confidence DESC
                """
            ).fetchall()

        return [
            EnergyPattern(
                id=row["id"],
                hour_of_day=row["hour_of_day"],
                day_of_week=row["day_of_week"],
                energy_level=row["energy_level"],
                confidence=row["confidence"],
                sample_count=row["sample_count"],
                updated_at=row["updated_at"]
            )
            for row in rows
        ]

    def get_task_complexities(self) -> List[TaskComplexity]:
        """Get all task complexity definitions

        Returns:
            List of TaskComplexity objects
        """
        rows = self.db.conn.execute(
            """
            SELECT task_type, cognitive_load, optimal_energy, examples
            FROM task_complexity
            """
        ).fetchall()

        return [
            TaskComplexity(
                task_type=row["task_type"],
                cognitive_load=row["cognitive_load"],
                optimal_energy=row["optimal_energy"],
                examples=json.loads(row["examples"])
            )
            for row in rows
        ]
