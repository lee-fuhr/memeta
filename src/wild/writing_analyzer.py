"""
Feature 57: Writing Style Evolution Tracking

Tracks Lee's writing style changes over time and detects intentional vs accidental drift.

Metrics tracked:
- Headline length (words, characters)
- Sentence length distribution
- Paragraph structure
- Word choice patterns (compression, formality)
- Technical density (jargon, code references)
- Tone indicators (questions, imperatives, etc.)

Alerts:
- "Your headlines were 8 words avg in Q4 2025, now 5 words. Intentional compression?"
- "Sentence length variance increased 40% - more variety or loss of rhythm?"
- "Technical density dropped 25% in client docs - matching audience or losing depth?"

Integration: Analyzes session content, tracks trends in intelligence.db
"""

import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict, Counter
import statistics


@dataclass
class WritingSnapshot:
    """A snapshot of writing style at a point in time"""
    session_id: str
    timestamp: datetime
    content_type: str  # 'headline', 'body', 'email', 'doc', 'code_comment'

    # Length metrics
    avg_headline_length: Optional[float]  # words
    avg_sentence_length: float  # words
    avg_paragraph_length: float  # sentences

    # Word choice
    compression_score: float  # 0.0-1.0 (higher = more compressed)
    formality_score: float  # 0.0-1.0 (higher = more formal)
    technical_density: float  # Technical terms per 100 words

    # Tone
    question_rate: float  # Questions per 100 sentences
    imperative_rate: float  # Commands per 100 sentences
    passive_rate: float  # Passive voice per 100 sentences

    # Variety
    sentence_length_variance: float
    vocabulary_richness: float  # Unique words / total words


@dataclass
class StyleTrend:
    """Detected trend in writing style"""
    metric: str  # Which metric changed
    direction: str  # 'increase', 'decrease', 'stable'
    magnitude: float  # Size of change (%)
    time_period: str  # e.g., "Q4 2025 → Q1 2026"
    old_value: float
    new_value: float
    is_significant: bool  # >20% change
    interpretation: str  # What this might mean


class WritingStyleAnalyzer:
    """
    Tracks writing style evolution over time.

    Thresholds:
    - Significant change: >20% deviation from baseline
    - Trend detection window: 30 days
    - Minimum samples for trend: 10 sessions
    """

    SIGNIFICANT_CHANGE_THRESHOLD = 0.20  # 20%
    TREND_WINDOW_DAYS = 30
    MIN_SAMPLES = 10

    # Word lists for scoring
    FILLER_WORDS = [
        'actually', 'basically', 'essentially', 'literally', 'really', 'very',
        'quite', 'rather', 'somewhat', 'just', 'simply', 'merely'
    ]

    FORMAL_WORDS = [
        'however', 'therefore', 'thus', 'furthermore', 'moreover', 'consequently',
        'nevertheless', 'nonetheless', 'accordingly', 'henceforth'
    ]

    TECHNICAL_MARKERS = [
        'api', 'database', 'server', 'client', 'backend', 'frontend', 'deployment',
        'architecture', 'infrastructure', 'authentication', 'authorization',
        'algorithm', 'optimization', 'performance', 'scalability'
    ]

    def __init__(self, db_path: str = None):
        """Initialize analyzer with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for style tracking"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS writing_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    avg_headline_length REAL,
                    avg_sentence_length REAL NOT NULL,
                    avg_paragraph_length REAL NOT NULL,
                    compression_score REAL NOT NULL,
                    formality_score REAL NOT NULL,
                    technical_density REAL NOT NULL,
                    question_rate REAL NOT NULL,
                    imperative_rate REAL NOT NULL,
                    passive_rate REAL NOT NULL,
                    sentence_length_variance REAL NOT NULL,
                    vocabulary_richness REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS style_trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('increase', 'decrease', 'stable')),
                    magnitude REAL NOT NULL,
                    time_period TEXT NOT NULL,
                    old_value REAL NOT NULL,
                    new_value REAL NOT NULL,
                    is_significant INTEGER NOT NULL,
                    interpretation TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_session ON writing_snapshots(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_time ON writing_snapshots(timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trends_metric ON style_trends(metric)")

    def analyze_text(self, session_id: str, text: str, content_type: str = 'body') -> WritingSnapshot:
        """
        Analyze text and create writing style snapshot.

        Args:
            session_id: Session identifier
            text: Text to analyze
            content_type: Type of content ('headline', 'body', 'email', etc.)

        Returns:
            WritingSnapshot with style metrics
        """
        # Extract sentences and paragraphs
        sentences = self._split_sentences(text)
        paragraphs = self._split_paragraphs(text)
        words = text.lower().split()

        # Length metrics
        if content_type == 'headline':
            headlines = [s for s in sentences if len(s.split()) < 15]
            avg_headline_length = statistics.mean(len(h.split()) for h in headlines) if headlines else None
        else:
            avg_headline_length = None

        avg_sentence_length = statistics.mean(len(s.split()) for s in sentences) if sentences else 0.0
        avg_paragraph_length = statistics.mean(len(self._split_sentences(p)) for p in paragraphs) if paragraphs else 0.0

        # Word choice
        compression_score = self._calculate_compression(words)
        formality_score = self._calculate_formality(words)
        technical_density = self._calculate_technical_density(words)

        # Tone
        question_rate = (sum(1 for s in sentences if '?' in s) / max(1, len(sentences))) * 100
        imperative_rate = self._calculate_imperative_rate(sentences)
        passive_rate = self._calculate_passive_rate(sentences)

        # Variety
        sentence_lengths = [len(s.split()) for s in sentences]
        sentence_length_variance = statistics.variance(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
        vocabulary_richness = len(set(words)) / max(1, len(words))

        snapshot = WritingSnapshot(
            session_id=session_id,
            timestamp=datetime.now(),
            content_type=content_type,
            avg_headline_length=avg_headline_length,
            avg_sentence_length=avg_sentence_length,
            avg_paragraph_length=avg_paragraph_length,
            compression_score=compression_score,
            formality_score=formality_score,
            technical_density=technical_density,
            question_rate=question_rate,
            imperative_rate=imperative_rate,
            passive_rate=passive_rate,
            sentence_length_variance=sentence_length_variance,
            vocabulary_richness=vocabulary_richness
        )

        self._save_snapshot(snapshot)
        return snapshot

    def detect_trends(self, days: int = None) -> List[StyleTrend]:
        """
        Detect significant trends in writing style.

        Args:
            days: Look back this many days (default: TREND_WINDOW_DAYS)

        Returns:
            List of detected style trends
        """
        if days is None:
            days = self.TREND_WINDOW_DAYS

        cutoff = datetime.now() - timedelta(days=days)
        midpoint = cutoff + timedelta(days=days/2)

        trends = []

        # Get snapshots before and after midpoint
        old_snapshots = self._get_snapshots(cutoff, midpoint)
        new_snapshots = self._get_snapshots(midpoint, datetime.now())

        if len(old_snapshots) < self.MIN_SAMPLES or len(new_snapshots) < self.MIN_SAMPLES:
            return []  # Not enough data

        # Metrics to track
        metrics = [
            'avg_headline_length', 'avg_sentence_length', 'avg_paragraph_length',
            'compression_score', 'formality_score', 'technical_density',
            'question_rate', 'imperative_rate', 'passive_rate',
            'sentence_length_variance', 'vocabulary_richness'
        ]

        for metric in metrics:
            # Calculate averages for old and new periods
            old_values = [getattr(s, metric) for s in old_snapshots if getattr(s, metric) is not None]
            new_values = [getattr(s, metric) for s in new_snapshots if getattr(s, metric) is not None]

            if not old_values or not new_values:
                continue

            old_avg = statistics.mean(old_values)
            new_avg = statistics.mean(new_values)

            if old_avg == 0:
                continue

            # Calculate change
            change = (new_avg - old_avg) / old_avg
            magnitude = abs(change)

            # Direction
            if magnitude < 0.05:
                direction = 'stable'
            elif change > 0:
                direction = 'increase'
            else:
                direction = 'decrease'

            # Is it significant?
            is_significant = magnitude >= self.SIGNIFICANT_CHANGE_THRESHOLD

            if is_significant or direction != 'stable':
                interpretation = self._interpret_change(metric, direction, magnitude, old_avg, new_avg)

                trend = StyleTrend(
                    metric=metric,
                    direction=direction,
                    magnitude=magnitude,
                    time_period=f"{cutoff.strftime('%Y-%m')} → {datetime.now().strftime('%Y-%m')}",
                    old_value=old_avg,
                    new_value=new_avg,
                    is_significant=is_significant,
                    interpretation=interpretation
                )

                trends.append(trend)
                self._save_trend(trend)

        return trends

    def _calculate_compression(self, words: List[str]) -> float:
        """Calculate compression score (0.0-1.0, higher = more compressed)"""
        if not words:
            return 0.0

        # Count filler words
        filler_count = sum(1 for w in words if w in self.FILLER_WORDS)
        filler_ratio = filler_count / len(words)

        # Compression is inverse of filler ratio
        return 1.0 - filler_ratio

    def _calculate_formality(self, words: List[str]) -> float:
        """Calculate formality score (0.0-1.0, higher = more formal)"""
        if not words:
            return 0.0

        formal_count = sum(1 for w in words if w in self.FORMAL_WORDS)
        formal_ratio = formal_count / len(words)

        # Normalize to 0-1 (assume 5% formal words is max)
        return min(1.0, formal_ratio * 20)

    def _calculate_technical_density(self, words: List[str]) -> float:
        """Calculate technical density (technical terms per 100 words)"""
        if not words:
            return 0.0

        technical_count = sum(1 for w in words if w in self.TECHNICAL_MARKERS)
        return (technical_count / len(words)) * 100

    def _calculate_imperative_rate(self, sentences: List[str]) -> float:
        """Calculate imperative sentence rate (per 100 sentences)"""
        if not sentences:
            return 0.0

        # Simple heuristic: starts with verb
        imperative_verbs = ['use', 'do', 'create', 'avoid', 'check', 'add', 'remove', 'run', 'test']
        imperative_count = sum(1 for s in sentences if any(s.lower().strip().startswith(v) for v in imperative_verbs))

        return (imperative_count / len(sentences)) * 100

    def _calculate_passive_rate(self, sentences: List[str]) -> float:
        """Calculate passive voice rate (per 100 sentences)"""
        if not sentences:
            return 0.0

        # Simple heuristic: "is/was/are/were + past participle"
        passive_pattern = re.compile(r'\b(is|was|are|were|been|be)\s+\w+ed\b', re.IGNORECASE)
        passive_count = sum(1 for s in sentences if passive_pattern.search(s))

        return (passive_count / len(sentences)) * 100

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences"""
        # Simple sentence splitter
        sentences = re.split(r'[.!?]+\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs"""
        paragraphs = text.split('\n\n')
        return [p.strip() for p in paragraphs if p.strip()]

    def _interpret_change(self, metric: str, direction: str, magnitude: float,
                         old_value: float, new_value: float) -> str:
        """Generate human-readable interpretation of style change"""
        change_pct = int(magnitude * 100)

        interpretations = {
            'avg_headline_length': {
                'increase': f"Headlines got {change_pct}% longer ({old_value:.1f} → {new_value:.1f} words). Intentional or losing punch?",
                'decrease': f"Headlines compressed {change_pct}% ({old_value:.1f} → {new_value:.1f} words). Intentional tightening?"
            },
            'avg_sentence_length': {
                'increase': f"Sentences {change_pct}% longer. More complexity or losing clarity?",
                'decrease': f"Sentences {change_pct}% shorter. Intentional compression or choppy?"
            },
            'compression_score': {
                'increase': f"Writing {change_pct}% more compressed. Removing fluff or losing flow?",
                'decrease': f"Writing {change_pct}% less compressed. Adding context or filler?"
            },
            'technical_density': {
                'increase': f"Technical density up {change_pct}%. More depth or losing accessibility?",
                'decrease': f"Technical density down {change_pct}%. Matching audience or oversimplifying?"
            },
            'sentence_length_variance': {
                'increase': f"Sentence variety up {change_pct}%. More rhythm or losing consistency?",
                'decrease': f"Sentence variety down {change_pct}%. More consistent or monotonous?"
            },
        }

        return interpretations.get(metric, {}).get(direction, f"{metric} {direction}d {change_pct}%")

    def _save_snapshot(self, snapshot: WritingSnapshot):
        """Save snapshot to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO writing_snapshots
                (session_id, timestamp, content_type, avg_headline_length,
                 avg_sentence_length, avg_paragraph_length, compression_score,
                 formality_score, technical_density, question_rate,
                 imperative_rate, passive_rate, sentence_length_variance,
                 vocabulary_richness)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.session_id, snapshot.timestamp.isoformat(), snapshot.content_type,
                snapshot.avg_headline_length, snapshot.avg_sentence_length,
                snapshot.avg_paragraph_length, snapshot.compression_score,
                snapshot.formality_score, snapshot.technical_density,
                snapshot.question_rate, snapshot.imperative_rate,
                snapshot.passive_rate, snapshot.sentence_length_variance,
                snapshot.vocabulary_richness
            ))

    def _get_snapshots(self, start: datetime, end: datetime) -> List[WritingSnapshot]:
        """Get snapshots in time range"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT session_id, timestamp, content_type, avg_headline_length,
                       avg_sentence_length, avg_paragraph_length, compression_score,
                       formality_score, technical_density, question_rate,
                       imperative_rate, passive_rate, sentence_length_variance,
                       vocabulary_richness
                FROM writing_snapshots
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (start.isoformat(), end.isoformat())).fetchall()

        return [
            WritingSnapshot(
                session_id=r[0], timestamp=datetime.fromisoformat(r[1]), content_type=r[2],
                avg_headline_length=r[3], avg_sentence_length=r[4],
                avg_paragraph_length=r[5], compression_score=r[6],
                formality_score=r[7], technical_density=r[8],
                question_rate=r[9], imperative_rate=r[10], passive_rate=r[11],
                sentence_length_variance=r[12], vocabulary_richness=r[13]
            )
            for r in rows
        ]

    def _save_trend(self, trend: StyleTrend):
        """Save trend to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO style_trends
                (metric, direction, magnitude, time_period, old_value, new_value,
                 is_significant, interpretation, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trend.metric, trend.direction, trend.magnitude, trend.time_period,
                trend.old_value, trend.new_value, 1 if trend.is_significant else 0,
                trend.interpretation, datetime.now().isoformat()
            ))
