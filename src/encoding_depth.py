"""
Elaborative encoding depth scorer.

Based on Craik & Lockhart (1972) levels of processing theory:
deeper semantic processing produces stronger, more durable memories.

Scores each memory's encoding depth on a 1-3 scale:
  Level 1 (shallow): Bare facts, no context. Short content without causal
      connectors, comparisons, or cross-references.
  Level 2 (intermediate): Facts with explanation. Contains causal connectors
      (because, therefore, due to...) or substantial length (>80 chars).
  Level 3 (deep): Facts with reasoning, analogies, connections to other
      knowledge. References other projects, uses comparisons, draws on
      prior experience.

Level 1 memories are flagged for enrichment — a separate nightly process
can deepen them by prompting for context or linking related knowledge.

All scoring is heuristic (no LLM calls). Pure Python + SQLite.
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class EncodingDepthScorer:
    """Score and track elaborative encoding depth for memories."""

    # Causal connectors — indicate explanatory reasoning
    CAUSAL_CONNECTORS = [
        "because",
        "since",
        "therefore",
        "so that",
        "due to",
        "as a result",
        "in order to",
        "which means",
        "this causes",
        "leading to",
    ]

    # Comparison markers — indicate analogical thinking
    COMPARISON_MARKERS = [
        "similar to",
        "unlike",
        "compared to",
        "reminds me of",
        "same as",
        "different from",
        "just as",
        "whereas",
    ]

    # Reference markers — indicate cross-knowledge connections
    REFERENCE_MARKERS = [
        "in project",
        "last time",
        "previously",
        "we learned",
        "that time",
    ]

    def __init__(self, db_path: str):
        """Initialize scorer with SQLite database path.

        Args:
            db_path: Path to SQLite database file.
        """
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the encoding_depth table if it doesn't exist."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS encoding_depth (
                    memory_id TEXT PRIMARY KEY,
                    depth_level INTEGER NOT NULL,
                    char_count INTEGER,
                    causal_count INTEGER DEFAULT 0,
                    comparison_count INTEGER DEFAULT 0,
                    reference_count INTEGER DEFAULT 0,
                    signals TEXT,
                    scored_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _count_markers(self, content_lower: str, markers: List[str]) -> tuple:
        """Count occurrences of markers in content and return (count, matched_list).

        Uses word-boundary-aware matching to avoid substring false positives
        for single-word markers. Multi-word markers are matched as-is since
        they're specific enough to avoid ambiguity.

        Args:
            content_lower: Lowercased content string.
            markers: List of marker phrases to search for.

        Returns:
            Tuple of (count, list_of_matched_markers).
        """
        count = 0
        matched = []
        for marker in markers:
            # Multi-word markers: exact substring match (specific enough)
            # Single-word markers: use word boundary regex to avoid
            # matching "like" inside "likely" etc.
            if " " in marker:
                occurrences = content_lower.count(marker)
            else:
                pattern = r"\b" + re.escape(marker) + r"\b"
                occurrences = len(re.findall(pattern, content_lower))
            if occurrences > 0:
                count += occurrences
                matched.append(marker)
        return count, matched

    def score_depth(self, content: str) -> int:
        """Score encoding depth 1-3 based on content analysis.

        Args:
            content: Memory content text.

        Returns:
            Depth level: 1 (shallow), 2 (intermediate), or 3 (deep).
        """
        return self.analyze_content(content)["depth"]

    def analyze_content(self, content: str) -> Dict:
        """Return detailed analysis of encoding depth.

        Args:
            content: Memory content text.

        Returns:
            Dict with keys: depth, char_count, causal_count,
            comparison_count, reference_count, signals.
        """
        stripped = content.strip()
        char_count = len(stripped)
        content_lower = stripped.lower()

        causal_count, causal_matched = self._count_markers(
            content_lower, self.CAUSAL_CONNECTORS
        )
        comparison_count, comparison_matched = self._count_markers(
            content_lower, self.COMPARISON_MARKERS
        )
        reference_count, reference_matched = self._count_markers(
            content_lower, self.REFERENCE_MARKERS
        )

        # Build signals list with categorized labels
        signals = []
        for m in causal_matched:
            signals.append(f"causal:{m}")
        for m in comparison_matched:
            signals.append(f"comparison:{m}")
        for m in reference_matched:
            signals.append(f"reference:{m}")

        # --- Depth determination ---
        # Level 3: Must have signals from multiple categories
        #   (causal + comparison, causal + reference, or comparison + reference)
        has_causal = causal_count > 0
        has_comparison = comparison_count > 0
        has_reference = reference_count > 0
        category_count = sum([has_causal, has_comparison, has_reference])

        if category_count >= 2:
            depth = 3
        elif has_causal or has_comparison or has_reference:
            # Level 2: At least one signal category present
            depth = 2
        elif char_count > 80:
            # Level 2: Substantial length implies some elaboration
            depth = 2
        else:
            # Level 1: Shallow — bare fact, no context
            depth = 1

        return {
            "depth": depth,
            "char_count": char_count,
            "causal_count": causal_count,
            "comparison_count": comparison_count,
            "reference_count": reference_count,
            "signals": signals,
        }

    def record_depth(self, memory_id: str, content: str) -> int:
        """Score and record depth for a memory.

        If a record for memory_id already exists, it is updated (upsert).

        Args:
            memory_id: Unique memory identifier.
            content: Memory content text.

        Returns:
            Depth level (1, 2, or 3).
        """
        analysis = self.analyze_content(content)
        now = datetime.now().isoformat()

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO encoding_depth
                    (memory_id, depth_level, char_count, causal_count,
                     comparison_count, reference_count, signals, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    depth_level = excluded.depth_level,
                    char_count = excluded.char_count,
                    causal_count = excluded.causal_count,
                    comparison_count = excluded.comparison_count,
                    reference_count = excluded.reference_count,
                    signals = excluded.signals,
                    scored_at = excluded.scored_at
                """,
                (
                    memory_id,
                    analysis["depth"],
                    analysis["char_count"],
                    analysis["causal_count"],
                    analysis["comparison_count"],
                    analysis["reference_count"],
                    json.dumps(analysis["signals"]),
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return analysis["depth"]

    def get_shallow_memories(self, limit: int = 50) -> List[Dict]:
        """Return level-1 memories that need enrichment.

        Args:
            limit: Maximum number of results to return.

        Returns:
            List of dicts with memory_id, depth_level, scored_at.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT memory_id, depth_level, char_count, causal_count,
                       comparison_count, reference_count, signals, scored_at
                FROM encoding_depth
                WHERE depth_level = 1
                ORDER BY scored_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_depth_distribution(self) -> Dict[int, int]:
        """Return count of memories at each depth level.

        Returns:
            Dict mapping depth level (1, 2, 3) to count.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT depth_level, COUNT(*) as cnt
                FROM encoding_depth
                GROUP BY depth_level
                """
            ).fetchall()

            dist = {1: 0, 2: 0, 3: 0}
            for level, count in rows:
                dist[level] = count
            return dist
        finally:
            conn.close()

    def get_enrichment_candidates(
        self, max_age_days: int = 30
    ) -> List[Dict]:
        """Return shallow memories recent enough to be worth enriching.

        Args:
            max_age_days: Only include memories scored within this many days.

        Returns:
            List of dicts with memory details.
        """
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT memory_id, depth_level, char_count, causal_count,
                       comparison_count, reference_count, signals, scored_at
                FROM encoding_depth
                WHERE depth_level = 1 AND scored_at >= ?
                ORDER BY scored_at DESC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
