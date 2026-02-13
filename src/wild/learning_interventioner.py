"""F64: Learning Intervention System

Detects repeated questions and suggests creating learning resources.

Usage:
    from wild.learning_interventioner import LearningInterventioner

    interventioner = LearningInterventioner()

    # Detect repeated question
    intervention = interventioner.detect_repeated_question("How do I use feature X?")

    # Create tutorial
    tutorial = interventioner.create_tutorial("Feature X usage")

    # Create reference
    reference = interventioner.create_reference("Feature X API")
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class LearningIntervention:
    """Learning intervention record"""
    id: str
    question_pattern: str
    occurrence_count: int
    intervention_type: str  # tutorial, reference, automation
    content: str
    created_at: int
    helped: Optional[bool]


class LearningInterventioner:
    """Detects repeated questions and creates learning resources"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize learning interventioner

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def detect_repeated_question(self, question: str) -> Optional[LearningIntervention]:
        """Detect if question has been asked repeatedly

        Args:
            question: Question text

        Returns:
            LearningIntervention if pattern detected, None otherwise
        """
        # Check existing interventions
        row = self.db.conn.execute(
            """
            SELECT id, question_pattern, occurrence_count, intervention_type, content, created_at, helped
            FROM learning_interventions
            WHERE question_pattern LIKE ?
            """,
            (f"%{question[:30]}%",)  # Match on first 30 chars
        ).fetchone()

        if row:
            return LearningIntervention(
                id=row["id"],
                question_pattern=row["question_pattern"],
                occurrence_count=row["occurrence_count"],
                intervention_type=row["intervention_type"],
                content=row["content"],
                created_at=row["created_at"],
                helped=bool(row["helped"]) if row["helped"] is not None else None
            )

        return None

    def record_question(self, question: str) -> int:
        """Record question occurrence

        Args:
            question: Question text

        Returns:
            Occurrence count
        """
        # Normalize question
        normalized = question.lower().strip()

        # Check if exists
        row = self.db.conn.execute(
            """
            SELECT id, occurrence_count
            FROM learning_interventions
            WHERE question_pattern = ?
            """,
            (normalized,)
        ).fetchone()

        if row:
            # Increment count
            new_count = row["occurrence_count"] + 1
            self.db.conn.execute(
                """
                UPDATE learning_interventions
                SET occurrence_count = ?
                WHERE id = ?
                """,
                (new_count, row["id"])
            )
            self.db.conn.commit()
            return new_count
        else:
            # Create new
            intervention_id = str(uuid.uuid4())
            timestamp = int(time.time())

            self.db.conn.execute(
                """
                INSERT INTO learning_interventions
                (id, question_pattern, occurrence_count, intervention_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (intervention_id, normalized, 1, "none", "", timestamp)
            )
            self.db.conn.commit()
            return 1

    def create_tutorial(self, topic: str) -> str:
        """Create tutorial for topic

        Args:
            topic: Topic name

        Returns:
            Tutorial content (generated)
        """
        # Simplified: return template
        tutorial = f"""# Tutorial: {topic}

## Overview
This tutorial covers the basics of {topic}.

## Steps
1. Understand the concept
2. Try basic examples
3. Practice with real scenarios

## Common Pitfalls
- Watch out for edge cases
- Remember to handle errors

## Further Reading
- Documentation
- Examples repository
"""
        return tutorial

    def create_reference(self, topic: str) -> str:
        """Create reference for topic

        Args:
            topic: Topic name

        Returns:
            Reference content (generated)
        """
        # Simplified: return template
        reference = f"""# Reference: {topic}

## Quick Start
Basic usage of {topic}.

## API
- Function 1: Description
- Function 2: Description

## Examples
```python
# Example usage
example()
```

## Troubleshooting
Common issues and solutions.
"""
        return reference

    def save_intervention(
        self,
        question_pattern: str,
        intervention_type: str,
        content: str
    ) -> str:
        """Save intervention

        Args:
            question_pattern: Question pattern
            intervention_type: Type (tutorial, reference, automation)
            content: Generated content

        Returns:
            Intervention ID
        """
        intervention_id = str(uuid.uuid4())
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            INSERT INTO learning_interventions
            (id, question_pattern, occurrence_count, intervention_type, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (intervention_id, question_pattern, 0, intervention_type, content, timestamp)
        )
        self.db.conn.commit()

        return intervention_id

    def mark_helped(self, intervention_id: str, helped: bool):
        """Mark if intervention helped

        Args:
            intervention_id: Intervention ID
            helped: Whether it helped
        """
        self.db.conn.execute(
            """
            UPDATE learning_interventions
            SET helped = ?
            WHERE id = ?
            """,
            (1 if helped else 0, intervention_id)
        )
        self.db.conn.commit()

    def get_interventions(
        self,
        min_occurrences: int = 3
    ) -> List[LearningIntervention]:
        """Get interventions needing attention

        Args:
            min_occurrences: Minimum question occurrences

        Returns:
            List of LearningIntervention objects
        """
        rows = self.db.conn.execute(
            """
            SELECT id, question_pattern, occurrence_count, intervention_type, content, created_at, helped
            FROM learning_interventions
            WHERE occurrence_count >= ?
            ORDER BY occurrence_count DESC
            """,
            (min_occurrences,)
        ).fetchall()

        return [
            LearningIntervention(
                id=row["id"],
                question_pattern=row["question_pattern"],
                occurrence_count=row["occurrence_count"],
                intervention_type=row["intervention_type"],
                content=row["content"],
                created_at=row["created_at"],
                helped=bool(row["helped"]) if row["helped"] is not None else None
            )
            for row in rows
        ]

    def get_statistics(self) -> Dict:
        """Get intervention statistics

        Returns:
            Dict with statistics
        """
        # Total questions tracked
        total = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM learning_interventions"
        ).fetchone()

        # High frequency questions (3+)
        high_freq = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM learning_interventions WHERE occurrence_count >= 3"
        ).fetchone()

        # Interventions created
        created = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM learning_interventions WHERE intervention_type != 'none'"
        ).fetchone()

        return {
            "total_questions": total["count"],
            "high_frequency": high_freq["count"],
            "interventions_created": created["count"]
        }
