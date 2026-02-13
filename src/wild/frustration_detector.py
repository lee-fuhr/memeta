"""
Feature 55: Frustration Early Warning System

Detects frustration patterns BEFORE they peak and suggests interventions.

Signals tracked:
- Repeated corrections on same topic
- Topic cycling (returning to same issue)
- Negative sentiment spikes
- High correction velocity
- Same error patterns across sessions

Interventions:
- Suggest creating a hook to prevent the issue permanently
- Identify blockers that should be solved first
- Recommend taking a break when patterns indicate stuck state
- Surface relevant past solutions from memory

Integration: Runs during session consolidation, logs to wild_features.db
"""

import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict


@dataclass
class FrustrationSignal:
    """A detected frustration indicator"""
    signal_type: str  # 'repeated_correction', 'topic_cycling', 'negative_sentiment', 'high_velocity'
    severity: float  # 0.0-1.0
    evidence: str  # What triggered this signal
    intervention: str  # Suggested action
    timestamp: datetime


@dataclass
class FrustrationEvent:
    """A frustration event that crossed the threshold"""
    session_id: str
    signals: List[FrustrationSignal]
    combined_score: float  # 0.0-1.0
    peak_time: datetime
    intervention_suggested: bool
    intervention_text: Optional[str]


class FrustrationDetector:
    """
    Detects frustration patterns during sessions and suggests interventions.

    Thresholds:
    - Individual signal: 0.6+ triggers warning
    - Combined score: 0.7+ triggers intervention
    - Repeated corrections (same topic): 3+ within 30 min
    - Topic cycling: returning to topic 3+ times in 60 min
    """

    # Detection thresholds
    SIGNAL_THRESHOLD = 0.6
    INTERVENTION_THRESHOLD = 0.7
    CORRECTION_COUNT_THRESHOLD = 3
    CYCLE_COUNT_THRESHOLD = 3

    # Time windows
    CORRECTION_WINDOW = timedelta(minutes=30)
    CYCLE_WINDOW = timedelta(minutes=60)

    # Negative sentiment keywords
    NEGATIVE_KEYWORDS = [
        'frustrat', 'annoying', 'broken', 'failing', 'wrong', 'error',
        'doesn\'t work', 'not working', 'keep breaking', 'same mistake',
        'again', 'still', 'why does', 'this is ridiculous'
    ]

    def __init__(self, db_path: str = None):
        """Initialize detector with database for persistence"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for frustration tracking"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS frustration_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    severity REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    intervention TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS frustration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    combined_score REAL NOT NULL,
                    peak_time TEXT NOT NULL,
                    intervention_suggested INTEGER NOT NULL,
                    intervention_text TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_session
                ON frustration_signals(session_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_session
                ON frustration_events(session_id)
            """)

    def analyze_session(self, session_id: str, messages: List[Dict]) -> Optional[FrustrationEvent]:
        """
        Analyze a session for frustration signals.

        Args:
            session_id: Session identifier
            messages: List of message dicts with 'role', 'content', 'timestamp'

        Returns:
            FrustrationEvent if frustration detected, None otherwise
        """
        signals = []

        # Extract corrections and topics
        corrections = self._extract_corrections(messages)
        topics = self._extract_topics(messages)

        # Detect repeated corrections
        repeated = self._detect_repeated_corrections(corrections)
        if repeated:
            signals.extend(repeated)

        # Detect topic cycling
        cycling = self._detect_topic_cycling(topics)
        if cycling:
            signals.extend(cycling)

        # Detect negative sentiment
        negative = self._detect_negative_sentiment(messages)
        if negative:
            signals.extend(negative)

        # Detect high correction velocity
        velocity = self._detect_high_velocity(corrections)
        if velocity:
            signals.append(velocity)

        if not signals:
            return None

        # Calculate combined frustration score
        combined_score = self._calculate_combined_score(signals)

        # Save signals to DB
        self._save_signals(session_id, signals)

        # Check if intervention needed
        if combined_score >= self.INTERVENTION_THRESHOLD:
            intervention = self._generate_intervention(signals)
            event = FrustrationEvent(
                session_id=session_id,
                signals=signals,
                combined_score=combined_score,
                peak_time=max(s.timestamp for s in signals),
                intervention_suggested=True,
                intervention_text=intervention
            )
            self._save_event(event)
            return event

        return None

    def _extract_corrections(self, messages: List[Dict]) -> List[Tuple[datetime, str, str]]:
        """Extract corrections from messages: (timestamp, topic, correction_text)"""
        corrections = []
        correction_patterns = [
            r'actually,?\s+(.+)',
            r'correction:?\s+(.+)',
            r'no,?\s+(.+)',
            r'wrong,?\s+(.+)',
            r'mistake,?\s+(.+)',
            r'should be\s+(.+)',
            r'meant to say\s+(.+)',
        ]

        for msg in messages:
            if msg.get('role') != 'user':
                continue

            content = msg.get('content', '')
            timestamp = msg.get('timestamp', datetime.now())

            for pattern in correction_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    topic = self._extract_topic_from_text(content)
                    corrections.append((timestamp, topic, match.group(0)))

        return corrections

    def _extract_topics(self, messages: List[Dict]) -> List[Tuple[datetime, str]]:
        """Extract topics from messages: (timestamp, topic)"""
        topics = []

        for msg in messages:
            timestamp = msg.get('timestamp', datetime.now())
            topic = self._extract_topic_from_text(msg.get('content', ''))
            if topic:
                topics.append((timestamp, topic))

        return topics

    def _extract_topic_from_text(self, text: str) -> str:
        """Extract main topic from text (simplified - could use NLP)"""
        # Look for capitalized phrases, code references, or technical terms
        words = text.lower().split()
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        keywords = [w for w in words if w not in stop_words and len(w) > 3]

        if keywords:
            return keywords[0]  # Simplified - return first meaningful word
        return "unknown"

    def _detect_repeated_corrections(self, corrections: List[Tuple[datetime, str, str]]) -> List[FrustrationSignal]:
        """Detect when same topic is corrected multiple times"""
        signals = []
        topic_corrections = defaultdict(list)

        for timestamp, topic, text in corrections:
            topic_corrections[topic].append((timestamp, text))

        for topic, corr_list in topic_corrections.items():
            if len(corr_list) < self.CORRECTION_COUNT_THRESHOLD:
                continue

            # Check if corrections are within time window
            sorted_corr = sorted(corr_list, key=lambda x: x[0])
            window_corrections = []

            for ts, text in sorted_corr:
                window_corrections = [c for c in window_corrections if ts - c[0] <= self.CORRECTION_WINDOW]
                window_corrections.append((ts, text))

                if len(window_corrections) >= self.CORRECTION_COUNT_THRESHOLD:
                    signals.append(FrustrationSignal(
                        signal_type='repeated_correction',
                        severity=min(1.0, len(window_corrections) * 0.25),
                        evidence=f"Corrected '{topic}' {len(window_corrections)}x in {self.CORRECTION_WINDOW.total_seconds()/60:.0f} min",
                        intervention=f"Add a hook or verification step to prevent '{topic}' errors permanently",
                        timestamp=ts
                    ))

        return signals

    def _detect_topic_cycling(self, topics: List[Tuple[datetime, str]]) -> List[FrustrationSignal]:
        """Detect when returning to same topic multiple times"""
        signals = []
        topic_visits = defaultdict(list)

        for timestamp, topic in topics:
            topic_visits[topic].append(timestamp)

        for topic, visits in topic_visits.items():
            if len(visits) < self.CYCLE_COUNT_THRESHOLD:
                continue

            # Check if visits span across time (not consecutive)
            sorted_visits = sorted(visits)
            if sorted_visits[-1] - sorted_visits[0] > self.CYCLE_WINDOW:
                signals.append(FrustrationSignal(
                    signal_type='topic_cycling',
                    severity=min(1.0, len(visits) * 0.2),
                    evidence=f"Returned to '{topic}' {len(visits)}x over {(sorted_visits[-1] - sorted_visits[0]).total_seconds()/60:.0f} min",
                    intervention=f"'{topic}' seems to be a blocker. Should we solve it before continuing?",
                    timestamp=sorted_visits[-1]
                ))

        return signals

    def _detect_negative_sentiment(self, messages: List[Dict]) -> List[FrustrationSignal]:
        """Detect negative sentiment spikes"""
        signals = []

        for msg in messages:
            if msg.get('role') != 'user':
                continue

            content = msg.get('content', '').lower()
            timestamp = msg.get('timestamp', datetime.now())

            # Count negative keywords
            negative_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in content)

            if negative_count >= 2:
                signals.append(FrustrationSignal(
                    signal_type='negative_sentiment',
                    severity=min(1.0, negative_count * 0.3),
                    evidence=f"Found {negative_count} frustration indicators in message",
                    intervention="Detected frustration. Want to step back and reassess the approach?",
                    timestamp=timestamp
                ))

        return signals

    def _detect_high_velocity(self, corrections: List[Tuple[datetime, str, str]]) -> Optional[FrustrationSignal]:
        """Detect high correction velocity (many corrections in short time)"""
        if len(corrections) < 5:
            return None

        sorted_corr = sorted(corrections, key=lambda x: x[0])
        recent_window = timedelta(minutes=15)

        # Count corrections in recent window
        latest = sorted_corr[-1][0]
        recent_count = sum(1 for ts, _, _ in sorted_corr if latest - ts <= recent_window)

        if recent_count >= 5:
            return FrustrationSignal(
                signal_type='high_velocity',
                severity=min(1.0, recent_count * 0.15),
                evidence=f"{recent_count} corrections in {recent_window.total_seconds()/60:.0f} min",
                intervention="High correction rate detected. Consider taking a 5-minute break to reset.",
                timestamp=latest
            )

        return None

    def _calculate_combined_score(self, signals: List[FrustrationSignal]) -> float:
        """Calculate overall frustration score from multiple signals"""
        if not signals:
            return 0.0

        # Weight by signal type
        weights = {
            'repeated_correction': 1.5,  # Strongest indicator
            'topic_cycling': 1.3,
            'negative_sentiment': 1.0,
            'high_velocity': 1.2,
        }

        weighted_sum = sum(s.severity * weights.get(s.signal_type, 1.0) for s in signals)
        max_possible = len(signals) * 1.5  # Max weight

        return min(1.0, weighted_sum / max_possible)

    def _generate_intervention(self, signals: List[FrustrationSignal]) -> str:
        """Generate intervention text based on signals"""
        # Use the highest severity signal's intervention
        primary = max(signals, key=lambda s: s.severity)

        interventions = [f"⚠️ Frustration detected: {primary.intervention}"]

        # Add context from other signals
        if len(signals) > 1:
            interventions.append(f"\nAlso noticed: {', '.join(s.signal_type.replace('_', ' ') for s in signals[1:])}")

        return '\n'.join(interventions)

    def _save_signals(self, session_id: str, signals: List[FrustrationSignal]):
        """Save signals to database"""
        with sqlite3.connect(self.db_path) as conn:
            for sig in signals:
                conn.execute("""
                    INSERT INTO frustration_signals
                    (session_id, signal_type, severity, evidence, intervention, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    session_id, sig.signal_type, sig.severity,
                    sig.evidence, sig.intervention, sig.timestamp.isoformat()
                ))

    def _save_event(self, event: FrustrationEvent):
        """Save frustration event to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO frustration_events
                (session_id, combined_score, peak_time, intervention_suggested, intervention_text)
                VALUES (?, ?, ?, ?, ?)
            """, (
                event.session_id, event.combined_score, event.peak_time.isoformat(),
                1 if event.intervention_suggested else 0, event.intervention_text
            ))

    def get_session_history(self, session_id: str) -> Optional[FrustrationEvent]:
        """Retrieve frustration event for a session"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT session_id, combined_score, peak_time, intervention_suggested, intervention_text
                FROM frustration_events WHERE session_id = ?
            """, (session_id,)).fetchone()

            if not row:
                return None

            # Fetch signals
            signal_rows = conn.execute("""
                SELECT signal_type, severity, evidence, intervention, timestamp
                FROM frustration_signals WHERE session_id = ?
                ORDER BY timestamp
            """, (session_id,)).fetchall()

            signals = [
                FrustrationSignal(
                    signal_type=s[0], severity=s[1], evidence=s[2],
                    intervention=s[3], timestamp=datetime.fromisoformat(s[4])
                )
                for s in signal_rows
            ]

            return FrustrationEvent(
                session_id=row[0],
                signals=signals,
                combined_score=row[1],
                peak_time=datetime.fromisoformat(row[2]),
                intervention_suggested=bool(row[3]),
                intervention_text=row[4]
            )

    def get_recent_frustration_trends(self, days: int = 7) -> Dict[str, any]:
        """Get frustration trends over recent sessions"""
        cutoff = datetime.now() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            # Count events by type
            type_counts = conn.execute("""
                SELECT signal_type, COUNT(*) as count
                FROM frustration_signals
                WHERE timestamp > ?
                GROUP BY signal_type
                ORDER BY count DESC
            """, (cutoff.isoformat(),)).fetchall()

            # Average frustration score
            avg_score = conn.execute("""
                SELECT AVG(combined_score) FROM frustration_events
                WHERE peak_time > ?
            """, (cutoff.isoformat(),)).fetchone()[0] or 0.0

            # Sessions with interventions
            intervention_count = conn.execute("""
                SELECT COUNT(*) FROM frustration_events
                WHERE peak_time > ? AND intervention_suggested = 1
            """, (cutoff.isoformat(),)).fetchone()[0]

        return {
            'signal_type_counts': dict(type_counts),
            'average_frustration_score': avg_score,
            'intervention_count': intervention_count,
            'days_analyzed': days
        }
