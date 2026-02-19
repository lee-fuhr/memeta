"""
Content hash deduplication — multi-level hashing for duplicate detection.

Computes content hashes at three granularities to catch duplicates without
expensive LLM calls:

1. **Exact hash:** SHA-256 of full content. Catches true duplicates.
2. **Normalized hash:** SHA-256 after lowercasing, removing punctuation,
   collapsing whitespace. Catches formatting variants.
3. **Semantic hash:** Quantized embedding vector bucketed into N bins,
   then hashed. Catches paraphrases.

At extraction time, checks all three levels before creating a new memory.
Exact match = definite duplicate. Normalized match = likely duplicate.
Semantic hash match = possible duplicate (needs confirmation).

Usage:
    from memory_system.content_dedup import ContentDedup

    dedup = ContentDedup(db_path="dedup.db")
    dedup.register_memory("mem-001", "Hello world", embedding=[0.1, 0.2, ...])

    result = dedup.check_duplicate("Hello world")
    # {'is_duplicate': True, 'match_level': 'exact',
    #  'matched_memory_id': 'mem-001', 'confidence': 1.0}
"""

import hashlib
import re
import sqlite3
import string
from datetime import datetime, timezone
from typing import Optional

import numpy as np


class ContentDedup:
    """Multi-level content hash deduplication engine."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS content_hashes (
                    memory_id TEXT PRIMARY KEY,
                    exact_hash TEXT NOT NULL,
                    normalized_hash TEXT NOT NULL,
                    semantic_hash TEXT,
                    registered_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_exact_hash
                    ON content_hashes(exact_hash);
                CREATE INDEX IF NOT EXISTS idx_normalized_hash
                    ON content_hashes(normalized_hash);
                CREATE INDEX IF NOT EXISTS idx_semantic_hash
                    ON content_hashes(semantic_hash);

                CREATE TABLE IF NOT EXISTS dedup_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    new_content_hash TEXT NOT NULL,
                    matched_memory_id TEXT NOT NULL,
                    match_level TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new database connection."""
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # Hash computation
    # ------------------------------------------------------------------

    def compute_exact_hash(self, content: str) -> str:
        """SHA-256 of content as-is."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def compute_normalized_hash(self, content: str) -> str:
        """SHA-256 after normalizing: lowercase, strip punctuation, collapse whitespace."""
        normalized = content.lower()
        # Remove all punctuation
        normalized = normalized.translate(
            str.maketrans("", "", string.punctuation)
        )
        # Collapse all whitespace (tabs, newlines, multiple spaces) to single space
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def compute_semantic_hash(
        self, embedding: list[float], n_bins: int = 64
    ) -> str:
        """Quantize embedding into n_bins buckets, then SHA-256 the bucket assignments.

        The embedding values are mapped to [0, 1] range using min-max scaling,
        then each dimension is assigned to one of n_bins integer buckets.
        The resulting bucket array is hashed.
        """
        arr = np.array(embedding, dtype=np.float64)
        arr_min = arr.min()
        arr_max = arr.max()

        if arr_max - arr_min < 1e-12:
            # All values identical — put everything in bucket 0
            buckets = np.zeros(len(arr), dtype=np.int32)
        else:
            # Scale to [0, 1] then quantize to integer buckets
            scaled = (arr - arr_min) / (arr_max - arr_min)
            buckets = np.clip(
                (scaled * n_bins).astype(np.int32), 0, n_bins - 1
            )

        # Hash the bucket assignment bytes
        return hashlib.sha256(buckets.tobytes()).hexdigest()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_memory(
        self,
        memory_id: str,
        content: str,
        embedding: Optional[list[float]] = None,
    ) -> None:
        """Register a memory's hashes for future dedup checks.

        If memory_id already exists, it is replaced (upsert).
        """
        exact = self.compute_exact_hash(content)
        normalized = self.compute_normalized_hash(content)
        semantic = (
            self.compute_semantic_hash(embedding) if embedding is not None else None
        )
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_hashes
                    (memory_id, exact_hash, normalized_hash, semantic_hash, registered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, exact, normalized, semantic, now),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Duplicate checking
    # ------------------------------------------------------------------

    def check_duplicate(
        self,
        content: str,
        embedding: Optional[list[float]] = None,
    ) -> dict:
        """Check all three hash levels for duplicates.

        Returns:
            dict with keys:
                is_duplicate: bool
                match_level: 'exact' | 'normalized' | 'semantic' | None
                matched_memory_id: str | None
                confidence: float (1.0 exact, 0.9 normalized, 0.6 semantic, 0.0 none)
        """
        exact = self.compute_exact_hash(content)
        normalized = self.compute_normalized_hash(content)
        semantic = (
            self.compute_semantic_hash(embedding) if embedding is not None else None
        )

        conn = self._get_conn()
        try:
            # Level 1: exact match
            row = conn.execute(
                "SELECT memory_id FROM content_hashes WHERE exact_hash = ? LIMIT 1",
                (exact,),
            ).fetchone()
            if row:
                self._log_event(conn, exact, row[0], "exact")
                return {
                    "is_duplicate": True,
                    "match_level": "exact",
                    "matched_memory_id": row[0],
                    "confidence": 1.0,
                }

            # Level 2: normalized match
            row = conn.execute(
                "SELECT memory_id FROM content_hashes WHERE normalized_hash = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if row:
                self._log_event(conn, normalized, row[0], "normalized")
                return {
                    "is_duplicate": True,
                    "match_level": "normalized",
                    "matched_memory_id": row[0],
                    "confidence": 0.9,
                }

            # Level 3: semantic match (only if embedding provided)
            if semantic is not None:
                row = conn.execute(
                    "SELECT memory_id FROM content_hashes WHERE semantic_hash = ? LIMIT 1",
                    (semantic,),
                ).fetchone()
                if row:
                    self._log_event(conn, semantic, row[0], "semantic")
                    return {
                        "is_duplicate": True,
                        "match_level": "semantic",
                        "matched_memory_id": row[0],
                        "confidence": 0.6,
                    }

            # No match
            return {
                "is_duplicate": False,
                "match_level": None,
                "matched_memory_id": None,
                "confidence": 0.0,
            }
        finally:
            conn.close()

    def _log_event(
        self,
        conn: sqlite3.Connection,
        content_hash: str,
        matched_memory_id: str,
        match_level: str,
    ) -> None:
        """Record a dedup event in the events table."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO dedup_events (new_content_hash, matched_memory_id, match_level, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (content_hash, matched_memory_id, match_level, now),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_duplicate_groups(self) -> list[list[str]]:
        """Find groups of memories sharing the same normalized hash.

        Returns a list of groups, where each group is a list of memory_ids
        that share the same normalized hash. Only groups with 2+ members
        are returned.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT normalized_hash, GROUP_CONCAT(memory_id)
                FROM content_hashes
                GROUP BY normalized_hash
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            return [row[1].split(",") for row in rows]
        finally:
            conn.close()

    def get_dedup_stats(self) -> dict:
        """Return deduplication statistics.

        Returns:
            dict with keys:
                total_registered: int
                exact_dupes_found: int
                normalized_dupes_found: int
                semantic_dupes_found: int
        """
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM content_hashes"
            ).fetchone()[0]

            exact = conn.execute(
                "SELECT COUNT(*) FROM dedup_events WHERE match_level = 'exact'"
            ).fetchone()[0]

            normalized = conn.execute(
                "SELECT COUNT(*) FROM dedup_events WHERE match_level = 'normalized'"
            ).fetchone()[0]

            semantic = conn.execute(
                "SELECT COUNT(*) FROM dedup_events WHERE match_level = 'semantic'"
            ).fetchone()[0]

            return {
                "total_registered": total,
                "exact_dupes_found": exact,
                "normalized_dupes_found": normalized,
                "semantic_dupes_found": semantic,
            }
        finally:
            conn.close()
