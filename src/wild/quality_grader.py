"""
Feature 62: Memory Quality Auto-Grading

Grades every memory (A/B/C/D) and learns what makes good memories from user behavior.

Quality signals:
- Memory reinforcement frequency (how often it's validated across sessions)
- User corrections referencing the memory
- Cross-project validation count
- Specificity vs vagueness
- Actionability (does it lead to behavioral change?)
- Contradiction rate (how often it gets invalidated)

Learning loop:
1. Grade every memory at creation
2. Track actual usage/validation over time
3. Update grade based on real-world signals
4. Identify patterns in high-quality memories
5. Feed back into importance scoring and extraction prompts

Integration: Runs during consolidation, updates memory-ts metadata
"""

import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import Counter


@dataclass
class QualityGrade:
    """Quality grade for a memory"""
    memory_id: str
    grade: str  # A, B, C, D
    score: float  # 0.0-1.0 numeric score
    precision_score: float  # How specific vs vague
    actionability_score: float  # Does it lead to action?
    evidence_score: float  # How much supporting evidence?
    graded_at: datetime
    last_updated: datetime


@dataclass
class QualityPattern:
    """Learned pattern about what makes quality memories"""
    pattern_type: str  # 'high_quality', 'low_quality'
    characteristics: Dict[str, any]  # Common traits
    example_count: int
    confidence: float  # 0.0-1.0


class MemoryQualityGrader:
    """
    Grades memory quality and learns what makes good memories.

    Grading scale:
    - A (0.85-1.0): Precise, actionable, well-evidenced, validated
    - B (0.65-0.84): Good but could be more specific/actionable
    - C (0.40-0.64): Vague or limited usefulness
    - D (0.0-0.39): Too vague, not actionable, or invalidated

    Learning metrics:
    - Reinforcement rate (how often validated)
    - Correction rate (how often referenced in corrections)
    - Cross-project validation (seen in multiple contexts)
    - Time-to-invalidation (how long until contradiction)
    """

    # Grade thresholds
    GRADE_A_MIN = 0.85
    GRADE_B_MIN = 0.65
    GRADE_C_MIN = 0.40

    # Quality indicators
    VAGUE_WORDS = ['maybe', 'possibly', 'sometimes', 'often', 'usually', 'generally', 'typically']
    ACTION_VERBS = ['use', 'do', 'create', 'avoid', 'check', 'verify', 'test', 'run', 'add', 'remove']
    EVIDENCE_MARKERS = ['because', 'since', 'found that', 'discovered', 'measured', 'tested']

    def __init__(self, db_path: str = None):
        """Initialize grader with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for quality tracking"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_quality_grades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL UNIQUE,
                    grade TEXT NOT NULL CHECK(grade IN ('A', 'B', 'C', 'D')),
                    score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
                    precision_score REAL NOT NULL,
                    actionability_score REAL NOT NULL,
                    evidence_score REAL NOT NULL,
                    graded_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quality_validation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('reinforcement', 'correction', 'cross_project', 'contradiction')),
                    session_id TEXT,
                    evidence TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quality_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL CHECK(pattern_type IN ('high_quality', 'low_quality')),
                    characteristic_key TEXT NOT NULL,
                    characteristic_value TEXT NOT NULL,
                    example_count INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    last_updated TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_grades_memory ON memory_quality_grades(memory_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_validations_memory ON quality_validation_events(memory_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_type ON quality_patterns(pattern_type)")

    def grade_memory(self, memory_id: str, content: str, importance: float) -> QualityGrade:
        """
        Grade a memory at creation time.

        Args:
            memory_id: Memory identifier
            content: Memory content text
            importance: Importance score (0.0-1.0)

        Returns:
            QualityGrade with initial assessment
        """
        # Calculate component scores
        precision = self._score_precision(content)
        actionability = self._score_actionability(content)
        evidence = self._score_evidence(content)

        # Weighted combination (importance influences but doesn't dominate)
        score = min(1.0, (
            precision * 0.35 +
            actionability * 0.35 +
            evidence * 0.20 +
            importance * 0.10
        ))

        # Determine letter grade
        if score >= self.GRADE_A_MIN:
            grade = 'A'
        elif score >= self.GRADE_B_MIN:
            grade = 'B'
        elif score >= self.GRADE_C_MIN:
            grade = 'C'
        else:
            grade = 'D'

        now = datetime.now()
        quality_grade = QualityGrade(
            memory_id=memory_id,
            grade=grade,
            score=score,
            precision_score=precision,
            actionability_score=actionability,
            evidence_score=evidence,
            graded_at=now,
            last_updated=now
        )

        self._save_grade(quality_grade)
        return quality_grade

    def _score_precision(self, content: str) -> float:
        """Score how precise vs vague the memory is (0.0-1.0)"""
        words = content.lower().split()

        if not words:
            return 0.0

        # Penalize vague words
        vague_count = sum(1 for w in words if any(v in w for v in self.VAGUE_WORDS))
        vague_ratio = vague_count / len(words)

        # Reward specifics: numbers, proper nouns, code references
        specific_count = sum(1 for w in words if w[0].isupper() or w.isdigit() or '`' in content)
        specific_ratio = min(1.0, specific_count / (len(words) * 0.2))

        # Length bonus for detailed memories (sweet spot: 50-200 words)
        word_count = len(words)
        length_score = 1.0 if 50 <= word_count <= 200 else max(0.3, min(1.0, word_count / 100))

        return max(0.0, min(1.0, (1 - vague_ratio) * 0.4 + specific_ratio * 0.4 + length_score * 0.2))

    def _score_actionability(self, content: str) -> float:
        """Score how actionable the memory is (0.0-1.0)"""
        content_lower = content.lower()

        # Look for action verbs
        action_count = sum(1 for verb in self.ACTION_VERBS if verb in content_lower)

        # Look for imperative statements
        imperative_patterns = [
            r'\b(use|do|create|avoid|check|verify|test|run|add|remove|ensure|always|never)\b',
            r'\b(should|must|need to|have to|required|important to)\b',
        ]
        imperative_count = sum(1 for p in imperative_patterns if re.search(p, content_lower))

        # Look for concrete examples
        example_markers = ['example', 'e.g.', 'such as', 'like', 'for instance']
        has_examples = any(marker in content_lower for marker in example_markers)

        # Combine signals
        action_score = min(1.0, action_count * 0.2)
        imperative_score = min(1.0, imperative_count * 0.3)
        example_score = 0.3 if has_examples else 0.0

        return action_score + imperative_score + example_score

    def _score_evidence(self, content: str) -> float:
        """Score how well-evidenced the memory is (0.0-1.0)"""
        content_lower = content.lower()

        # Look for evidence markers
        evidence_count = sum(1 for marker in self.EVIDENCE_MARKERS if marker in content_lower)

        # Look for measurements or data
        has_numbers = bool(re.search(r'\b\d+%?|\d+\.\d+\b', content))

        # Look for citations or references
        has_references = bool(re.search(r'(session|conversation|discussion|meeting|email|document)', content_lower))

        # Combine signals
        evidence_marker_score = min(1.0, evidence_count * 0.4)
        data_score = 0.3 if has_numbers else 0.0
        reference_score = 0.3 if has_references else 0.0

        return evidence_marker_score + data_score + reference_score

    def update_grade_from_validation(self, memory_id: str, event_type: str, session_id: str = None, evidence: str = None):
        """
        Update memory grade based on real-world validation events.

        Args:
            memory_id: Memory to update
            event_type: 'reinforcement', 'correction', 'cross_project', 'contradiction'
            session_id: Session where validation occurred
            evidence: Supporting evidence text
        """
        # Log the validation event
        self._log_validation_event(memory_id, event_type, session_id, evidence)

        # Retrieve current grade
        current = self._get_grade(memory_id)
        if not current:
            return  # Memory not graded yet

        # Get validation history
        validations = self._get_validation_history(memory_id)

        # Calculate adjustments based on validation patterns
        reinforcement_count = sum(1 for v in validations if v[0] == 'reinforcement')
        correction_count = sum(1 for v in validations if v[0] == 'correction')
        cross_project_count = sum(1 for v in validations if v[0] == 'cross_project')
        contradiction_count = sum(1 for v in validations if v[0] == 'contradiction')

        # Scoring adjustments
        reinforcement_boost = min(0.15, reinforcement_count * 0.03)
        cross_project_boost = min(0.15, cross_project_count * 0.05)
        correction_boost = min(0.10, correction_count * 0.02)
        contradiction_penalty = min(0.30, contradiction_count * 0.10)

        # Calculate new score
        new_score = current.score + reinforcement_boost + cross_project_boost + correction_boost - contradiction_penalty
        new_score = max(0.0, min(1.0, new_score))

        # Update grade
        if new_score >= self.GRADE_A_MIN:
            new_grade = 'A'
        elif new_score >= self.GRADE_B_MIN:
            new_grade = 'B'
        elif new_score >= self.GRADE_C_MIN:
            new_grade = 'C'
        else:
            new_grade = 'D'

        # Save updated grade
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE memory_quality_grades
                SET grade = ?, score = ?, last_updated = ?
                WHERE memory_id = ?
            """, (new_grade, new_score, datetime.now().isoformat(), memory_id))

    def learn_quality_patterns(self, min_examples: int = 10) -> List[QualityPattern]:
        """
        Analyze graded memories to identify patterns in high/low quality memories.

        Args:
            min_examples: Minimum examples needed to establish pattern

        Returns:
            List of learned quality patterns
        """
        patterns = []

        with sqlite3.connect(self.db_path) as conn:
            # Get high-quality memories (A/B grades)
            high_quality = conn.execute("""
                SELECT memory_id, precision_score, actionability_score, evidence_score
                FROM memory_quality_grades
                WHERE grade IN ('A', 'B')
            """).fetchall()

            # Get low-quality memories (C/D grades)
            low_quality = conn.execute("""
                SELECT memory_id, precision_score, actionability_score, evidence_score
                FROM memory_quality_grades
                WHERE grade IN ('C', 'D')
            """).fetchall()

        if len(high_quality) >= min_examples:
            # Calculate average scores for high-quality
            avg_precision = sum(m[1] for m in high_quality) / len(high_quality)
            avg_action = sum(m[2] for m in high_quality) / len(high_quality)
            avg_evidence = sum(m[3] for m in high_quality) / len(high_quality)

            patterns.append(QualityPattern(
                pattern_type='high_quality',
                characteristics={
                    'avg_precision': round(avg_precision, 2),
                    'avg_actionability': round(avg_action, 2),
                    'avg_evidence': round(avg_evidence, 2),
                },
                example_count=len(high_quality),
                confidence=min(1.0, len(high_quality) / 50)  # Confidence grows with examples
            ))

        if len(low_quality) >= min_examples:
            # Calculate average scores for low-quality
            avg_precision = sum(m[1] for m in low_quality) / len(low_quality)
            avg_action = sum(m[2] for m in low_quality) / len(low_quality)
            avg_evidence = sum(m[3] for m in low_quality) / len(low_quality)

            patterns.append(QualityPattern(
                pattern_type='low_quality',
                characteristics={
                    'avg_precision': round(avg_precision, 2),
                    'avg_actionability': round(avg_action, 2),
                    'avg_evidence': round(avg_evidence, 2),
                },
                example_count=len(low_quality),
                confidence=min(1.0, len(low_quality) / 50)
            ))

        # Save patterns
        for pattern in patterns:
            self._save_pattern(pattern)

        return patterns

    def get_quality_report(self) -> Dict[str, any]:
        """Generate quality metrics report"""
        with sqlite3.connect(self.db_path) as conn:
            # Grade distribution
            grade_dist = conn.execute("""
                SELECT grade, COUNT(*) as count
                FROM memory_quality_grades
                GROUP BY grade
                ORDER BY grade
            """).fetchall()

            # Average scores by grade
            avg_scores = conn.execute("""
                SELECT grade,
                       AVG(precision_score) as avg_precision,
                       AVG(actionability_score) as avg_action,
                       AVG(evidence_score) as avg_evidence
                FROM memory_quality_grades
                GROUP BY grade
            """).fetchall()

            # Most improved memories (biggest grade jumps)
            # (Would need update history tracking for this)

        return {
            'grade_distribution': dict(grade_dist),
            'average_scores_by_grade': {
                row[0]: {
                    'precision': round(row[1], 2),
                    'actionability': round(row[2], 2),
                    'evidence': round(row[3], 2)
                }
                for row in avg_scores
            },
            'total_graded': sum(count for _, count in grade_dist),
        }

    def _save_grade(self, grade: QualityGrade):
        """Save grade to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memory_quality_grades
                (memory_id, grade, score, precision_score, actionability_score, evidence_score, graded_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                grade.memory_id, grade.grade, grade.score,
                grade.precision_score, grade.actionability_score, grade.evidence_score,
                grade.graded_at.isoformat(), grade.last_updated.isoformat()
            ))

    def _get_grade(self, memory_id: str) -> Optional[QualityGrade]:
        """Retrieve grade from database"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT memory_id, grade, score, precision_score, actionability_score,
                       evidence_score, graded_at, last_updated
                FROM memory_quality_grades WHERE memory_id = ?
            """, (memory_id,)).fetchone()

        if not row:
            return None

        return QualityGrade(
            memory_id=row[0], grade=row[1], score=row[2],
            precision_score=row[3], actionability_score=row[4], evidence_score=row[5],
            graded_at=datetime.fromisoformat(row[6]), last_updated=datetime.fromisoformat(row[7])
        )

    def _log_validation_event(self, memory_id: str, event_type: str, session_id: str = None, evidence: str = None):
        """Log a validation event"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO quality_validation_events
                (memory_id, event_type, session_id, evidence, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (memory_id, event_type, session_id, evidence, datetime.now().isoformat()))

    def _get_validation_history(self, memory_id: str) -> List[Tuple[str, str, str]]:
        """Get validation history for a memory"""
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("""
                SELECT event_type, session_id, timestamp
                FROM quality_validation_events
                WHERE memory_id = ?
                ORDER BY timestamp
            """, (memory_id,)).fetchall()

    def _save_pattern(self, pattern: QualityPattern):
        """Save learned pattern to database"""
        with sqlite3.connect(self.db_path) as conn:
            for key, value in pattern.characteristics.items():
                conn.execute("""
                    INSERT OR REPLACE INTO quality_patterns
                    (pattern_type, characteristic_key, characteristic_value, example_count, confidence, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    pattern.pattern_type, key, str(value),
                    pattern.example_count, pattern.confidence, datetime.now().isoformat()
                ))
