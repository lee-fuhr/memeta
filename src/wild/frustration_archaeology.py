"""
Feature: Frustration Archaeology

Analyzes historical frustration events to find recurring patterns.
Groups events by signal type and evidence similarity, generates
actionable recommendations for preventing repeat frustration.

Integration: Reads from frustration_events and frustration_signals tables
populated by FrustrationDetector (Feature 55). Outputs markdown reports
for weekly review.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import json
import sqlite3
import time
import re


@dataclass
class FrustrationPattern:
    """A cluster of related frustration events forming a pattern."""
    pattern_name: str           # e.g., "Repeated correction: Webflow CSS"
    signal_type: str            # Primary signal type in this cluster
    event_count: int
    avg_severity: float
    common_signals: List[str]   # Most common evidence strings
    date_range: str             # "Feb 1 - Feb 15, 2026"
    recommendation: str         # Actionable suggestion
    event_ids: List[str] = field(default_factory=list)


# Stopwords for keyword extraction
STOPWORDS = frozenset({
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'it', 'this', 'that', 'was', 'are',
    'be', 'has', 'had', 'have', 'do', 'did', 'does', 'not', 'no', 'so',
    'if', 'as', 'up', 'out', 'about', 'into', 'over', 'after', 'been',
    'would', 'could', 'should', 'will', 'can', 'may', 'than', 'then',
    'its', 'my', 'your', 'his', 'her', 'our', 'their', 'which', 'what',
    'when', 'where', 'who', 'how', 'all', 'each', 'every', 'both',
    'few', 'more', 'most', 'other', 'some', 'such', 'only', 'same',
    'also', 'just', 'because', 'any', 'very', 'too', 'here', 'there',
})


class FrustrationArchaeologist:
    """
    Analyzes historical frustration events to surface recurring patterns.

    Process:
    1. Query frustration_events + frustration_signals for a date range
    2. Group by signal_type
    3. Sub-cluster within each type by evidence keyword overlap
    4. Generate FrustrationPattern with stats and recommendations
    5. Sort by event_count descending

    Example:
        arch = FrustrationArchaeologist(db_path="intelligence.db")
        patterns = arch.analyze(days=90)
        report = arch.generate_report(patterns)
        print(report)
    """

    # Recommendation templates by signal type
    RECOMMENDATIONS = {
        'repeated_correction': "Consider adding a hookify rule or reference doc to prevent this recurring correction pattern.",
        'topic_cycling': "This topic keeps resurfacing without resolution. Schedule a focused session to resolve it definitively.",
        'negative_sentiment': "Recurring frustration with this area. Consider whether the tooling or process needs to change.",
        'high_velocity': "Rapid-fire corrections suggest a fundamental misunderstanding. Create a reference document for this domain.",
    }

    DEFAULT_RECOMMENDATION = "Review this pattern and consider process or tooling changes to prevent recurrence."

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize archaeologist with database path.

        Args:
            db_path: Path to intelligence.db. If None, uses default location.
        """
        if db_path is None:
            from pathlib import Path
            db_path = str(Path(__file__).parent.parent.parent / "intelligence.db")
        self.db_path = str(db_path)

    def analyze(self, days: int = 90) -> List[FrustrationPattern]:
        """
        Analyze frustration events over the last N days.

        Process:
        1. Query frustration_events from intelligence.db for the date range
        2. Fetch associated signals from frustration_signals table
        3. Group events by primary signal_type
        4. Within each signal type, sub-cluster by evidence similarity (keyword overlap)
        5. For each cluster: create FrustrationPattern with stats and recommendation
        6. Sort by event_count descending (most common patterns first)

        Args:
            days: Number of days to look back

        Returns:
            List of FrustrationPattern sorted by event_count descending
        """
        events = self._query_events(days)
        if not events:
            return []

        # Group events by their primary signal type
        by_signal_type = defaultdict(list)
        for event in events:
            primary_type = self._get_primary_signal_type(event)
            by_signal_type[primary_type].append(event)

        patterns = []
        for signal_type, type_events in by_signal_type.items():
            # Sub-cluster by evidence similarity within this signal type
            clusters = self._cluster_by_evidence(type_events)

            for cluster in clusters:
                pattern = self._build_pattern(signal_type, cluster)
                patterns.append(pattern)

        # Sort by event_count descending
        patterns.sort(key=lambda p: p.event_count, reverse=True)

        return patterns

    def generate_report(self, patterns: List[FrustrationPattern]) -> str:
        """
        Generate a markdown report for weekly review.

        Args:
            patterns: List of FrustrationPattern from analyze()

        Returns:
            Markdown formatted report string
        """
        total_events = sum(p.event_count for p in patterns)

        lines = [
            "# Frustration archaeology -- last 90 days",
            "",
        ]

        if not patterns:
            lines.append("No frustration patterns detected.")
            return "\n".join(lines)

        lines.append(f"**{total_events} events clustered into {len(patterns)} patterns**")
        lines.append("")

        for i, pattern in enumerate(patterns, 1):
            lines.append(f"## Pattern {i}: {pattern.pattern_name} ({pattern.event_count} events)")
            lines.append("")
            lines.append(f"- **Type:** {pattern.signal_type}")
            lines.append(f"- **Severity:** {pattern.avg_severity:.1f}/1.0")
            lines.append(f"- **Period:** {pattern.date_range}")
            lines.append(f"- **Common triggers:** {', '.join(pattern.common_signals)}")
            lines.append(f"- **Recommendation:** {pattern.recommendation}")
            lines.append("")

        return "\n".join(lines)

    def _query_events(self, days: int) -> List[Dict]:
        """
        Query frustration_events and their signals for the last N days.

        Returns list of dicts with keys:
            id, session_id, combined_score, peak_time, intervention_text,
            created_at, signals (list of signal dicts)
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        events = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Query events within date range
            event_rows = conn.execute("""
                SELECT id, session_id, combined_score, peak_time,
                       intervention_text, created_at
                FROM frustration_events
                WHERE peak_time >= ?
                ORDER BY peak_time ASC
            """, (cutoff_iso,)).fetchall()

            for row in event_rows:
                session_id = row['session_id']

                # Fetch associated signals
                signal_rows = conn.execute("""
                    SELECT signal_type, severity, evidence, intervention, timestamp
                    FROM frustration_signals
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                """, (session_id,)).fetchall()

                signals = [
                    {
                        'signal_type': s['signal_type'],
                        'severity': s['severity'],
                        'evidence': s['evidence'],
                        'intervention': s['intervention'],
                        'timestamp': s['timestamp'],
                    }
                    for s in signal_rows
                ]

                events.append({
                    'id': row['id'],
                    'session_id': session_id,
                    'combined_score': row['combined_score'],
                    'peak_time': row['peak_time'],
                    'intervention_text': row['intervention_text'],
                    'created_at': row['created_at'],
                    'signals': signals,
                })

        return events

    def _get_primary_signal_type(self, event: Dict) -> str:
        """
        Determine the primary signal type for an event.

        Uses the signal type with the highest severity. Falls back to
        the most frequent signal type if severities are equal.
        """
        signals = event.get('signals', [])
        if not signals:
            return 'unknown'

        # Find signal with highest severity
        best = max(signals, key=lambda s: s['severity'])
        return best['signal_type']

    def _cluster_by_evidence(self, events: List[Dict]) -> List[List[Dict]]:
        """
        Group events with similar evidence strings using keyword overlap.

        Two events are considered similar if their evidence keyword overlap
        exceeds 50% (Jaccard similarity). Uses single-linkage clustering:
        if an event is similar to any event in a cluster, it joins that cluster.

        Args:
            events: List of event dicts (all same signal_type)

        Returns:
            List of clusters, where each cluster is a list of event dicts
        """
        if not events:
            return []

        if len(events) == 1:
            return [events]

        # Extract evidence keywords for each event
        event_keywords = []
        for event in events:
            all_evidence = ' '.join(s['evidence'] for s in event.get('signals', []))
            keywords = self._extract_keywords(all_evidence)
            event_keywords.append(keywords)

        # Single-linkage clustering by keyword overlap
        clusters: List[List[int]] = []  # indices into events list

        for i, keywords_i in enumerate(event_keywords):
            merged = False
            for cluster in clusters:
                # Check if this event is similar to any event in the cluster
                for j in cluster:
                    similarity = self._jaccard_similarity(keywords_i, event_keywords[j])
                    if similarity > 0.5:
                        cluster.append(i)
                        merged = True
                        break
                if merged:
                    break

            if not merged:
                clusters.append([i])

        return [[events[i] for i in cluster] for cluster in clusters]

    def _extract_keywords(self, text: str) -> set:
        """
        Extract meaningful keywords from evidence text.

        Lowercases, splits on non-alphanumeric characters, removes
        stopwords and short words (< 3 chars), removes pure numbers.
        """
        if not text:
            return set()

        # Lowercase and split on non-alphanumeric
        tokens = re.split(r'[^a-zA-Z0-9]+', text.lower())

        # Filter stopwords, short words, and pure numbers
        keywords = {
            t for t in tokens
            if t and len(t) >= 3 and t not in STOPWORDS and not t.isdigit()
        }

        return keywords

    def _jaccard_similarity(self, set_a: set, set_b: set) -> float:
        """Calculate Jaccard similarity between two sets."""
        if not set_a and not set_b:
            return 1.0  # Both empty = identical
        if not set_a or not set_b:
            return 0.0

        intersection = len(set_a & set_b)
        union = len(set_a | set_b)

        return intersection / union if union > 0 else 0.0

    def _build_pattern(self, signal_type: str, cluster: List[Dict]) -> FrustrationPattern:
        """
        Build a FrustrationPattern from a cluster of events.

        Args:
            signal_type: Primary signal type for this cluster
            cluster: List of event dicts in this cluster

        Returns:
            FrustrationPattern with computed stats
        """
        event_count = len(cluster)

        # Average severity (combined_score from events)
        avg_severity = sum(e['combined_score'] for e in cluster) / event_count

        # Collect all evidence strings
        all_evidence = []
        for event in cluster:
            for signal in event.get('signals', []):
                all_evidence.append(signal['evidence'])

        # Most common evidence strings (top 3)
        evidence_counter = Counter(all_evidence)
        common_signals = [ev for ev, _ in evidence_counter.most_common(3)]

        # Date range
        date_range = self._compute_date_range(cluster)

        # Pattern name from most common evidence
        pattern_name = self._generate_pattern_name(signal_type, common_signals)

        # Recommendation
        recommendation = self.RECOMMENDATIONS.get(signal_type, self.DEFAULT_RECOMMENDATION)

        # Event IDs
        event_ids = [str(e['id']) for e in cluster]

        return FrustrationPattern(
            pattern_name=pattern_name,
            signal_type=signal_type,
            event_count=event_count,
            avg_severity=round(avg_severity, 3),
            common_signals=common_signals if common_signals else ["No evidence recorded"],
            date_range=date_range,
            recommendation=recommendation,
            event_ids=event_ids,
        )

    def _compute_date_range(self, cluster: List[Dict]) -> str:
        """
        Compute human-readable date range from cluster events.

        Returns format like "Feb 1 - Feb 15, 2026" or "Feb 1, 2026" for single day.
        """
        peak_times = []
        for event in cluster:
            pt = event.get('peak_time', '')
            if pt:
                try:
                    peak_times.append(datetime.fromisoformat(pt))
                except (ValueError, TypeError):
                    pass

        if not peak_times:
            return "Unknown"

        earliest = min(peak_times)
        latest = max(peak_times)

        if earliest.date() == latest.date():
            return earliest.strftime("%b %-d, %Y")

        if earliest.year == latest.year:
            if earliest.month == latest.month:
                return f"{earliest.strftime('%b %-d')} - {latest.strftime('%-d, %Y')}"
            return f"{earliest.strftime('%b %-d')} - {latest.strftime('%b %-d, %Y')}"

        return f"{earliest.strftime('%b %-d, %Y')} - {latest.strftime('%b %-d, %Y')}"

    def _generate_pattern_name(self, signal_type: str, common_signals: List[str]) -> str:
        """
        Generate a human-readable pattern name.

        Format: "Signal type label: key evidence excerpt"
        """
        type_labels = {
            'repeated_correction': 'Repeated correction',
            'topic_cycling': 'Topic cycling',
            'negative_sentiment': 'Negative sentiment',
            'high_velocity': 'High velocity',
        }

        label = type_labels.get(signal_type, signal_type.replace('_', ' ').title())

        if common_signals:
            # Extract a short descriptor from the most common evidence
            excerpt = common_signals[0]
            # Truncate to something reasonable
            if len(excerpt) > 50:
                excerpt = excerpt[:47] + "..."
            return f"{label}: {excerpt}"

        return label
