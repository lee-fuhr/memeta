"""
Retrieval-induced forgetting detector.

Cognitive psychology feature based on Anderson, Bjork & Bjork (1994).
Repeatedly retrieving some memories from a category inhibits retrieval
of related but un-practiced memories.

Tracks which memories in a cluster are repeatedly retrieved and which
are ignored.  When a subset dominates retrieval, flags the neglected
siblings using the Gini coefficient to measure retrieval inequality.

Usage:
    from memory_system.retrieval_forgetting import RetrievalForgettingDetector

    detector = RetrievalForgettingDetector(db_path="intelligence.db")
    detector.log_retrieval("mem-001", cluster_id="webflow", query="deploy")
    result = detector.analyze_cluster("webflow", ["mem-001", "mem-002", ...])
    blind_spots = detector.find_blind_spots(cluster_memories={...})
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


class RetrievalForgettingDetector:
    """
    Detects retrieval-induced forgetting within memory clusters.

    Uses the Gini coefficient to measure retrieval inequality.  When a
    small subset of memories in a cluster dominates retrieval (Gini above
    threshold), the neglected siblings are flagged as blind spots.
    """

    def __init__(
        self,
        db_path: str,
        gini_threshold: float = 0.7,
    ):
        """
        Initialize the retrieval forgetting detector.

        Args:
            db_path: Path to the SQLite database file.
            gini_threshold: Gini coefficient above which a cluster is
                considered imbalanced.  Default 0.7.
        """
        self.db_path = Path(db_path)
        self.gini_threshold = gini_threshold
        self.conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    # ── Schema ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                cluster_id TEXT,
                query TEXT,
                retrieved_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_blind_spots (
                spot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id TEXT NOT NULL,
                gini_coefficient REAL NOT NULL,
                dominant_ids TEXT NOT NULL,
                neglected_ids TEXT NOT NULL,
                detected_at TEXT NOT NULL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_retrieval_memory "
            "ON retrieval_log(memory_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_retrieval_cluster "
            "ON retrieval_log(cluster_id)"
        )
        self.conn.commit()

    # ── Gini coefficient ────────────────────────────────────────────────

    def compute_gini(self, values: list[int]) -> float:
        """
        Compute Gini coefficient for a list of retrieval counts.

        0 = perfect equality (all memories retrieved equally).
        1 = perfect inequality (one memory gets all retrievals).

        Args:
            values: List of retrieval counts per memory.

        Returns:
            Gini coefficient as a float in [0, 1].
        """
        if not values:
            return 0.0

        n = len(values)
        if n == 1:
            return 0.0

        total = sum(values)
        if total == 0:
            return 0.0

        sorted_values = sorted(values)
        # Gini = (2 * sum(i * v[i])) / (n * sum(values)) - (n + 1) / n
        # where i is 1-indexed
        weighted_sum = sum((i + 1) * v for i, v in enumerate(sorted_values))
        gini = (2.0 * weighted_sum) / (n * total) - (n + 1) / n
        return max(0.0, min(1.0, gini))  # Clamp to [0, 1]

    # ── Write ───────────────────────────────────────────────────────────

    def log_retrieval(
        self,
        memory_id: str,
        cluster_id: Optional[str] = None,
        query: str = "",
    ) -> None:
        """
        Log a retrieval event for a memory.

        Args:
            memory_id: Identifier of the retrieved memory.
            cluster_id: Optional cluster the memory belongs to.
            query: Optional search query that triggered the retrieval.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO retrieval_log (memory_id, cluster_id, query, retrieved_at) "
            "VALUES (?, ?, ?, ?)",
            (memory_id, cluster_id, query, now),
        )
        self.conn.commit()

    # ── Analysis ────────────────────────────────────────────────────────

    def _get_retrieval_counts(
        self, cluster_id: str, memory_ids: list[str]
    ) -> dict[str, int]:
        """
        Get retrieval counts for each memory in a cluster.

        Returns a dict mapping memory_id to retrieval count.  Memories
        not found in retrieval_log get count 0.
        """
        counts: dict[str, int] = {mid: 0 for mid in memory_ids}
        if not memory_ids:
            return counts

        cur = self.conn.cursor()
        placeholders = ",".join("?" for _ in memory_ids)
        cur.execute(
            f"SELECT memory_id, COUNT(*) as cnt "
            f"FROM retrieval_log "
            f"WHERE cluster_id = ? AND memory_id IN ({placeholders}) "
            f"GROUP BY memory_id",
            [cluster_id] + memory_ids,
        )
        for row in cur.fetchall():
            counts[row[0]] = row[1]
        return counts

    def analyze_cluster(self, cluster_id: str, memory_ids: list[str]) -> dict:
        """
        Analyze retrieval patterns for a cluster.

        Args:
            cluster_id: Identifier of the cluster.
            memory_ids: All memory IDs that belong to this cluster.

        Returns:
            Dict with keys: gini, dominant_ids, neglected_ids, is_imbalanced.
        """
        if not memory_ids:
            return {
                "gini": 0.0,
                "dominant_ids": [],
                "neglected_ids": [],
                "is_imbalanced": False,
            }

        counts = self._get_retrieval_counts(cluster_id, memory_ids)
        values = list(counts.values())
        gini = self.compute_gini(values)

        # Determine dominant (top 50%) and neglected (bottom 50%)
        neglected = self._compute_neglected(counts)
        dominant = self._compute_dominant(counts)

        is_imbalanced = gini >= self.gini_threshold

        return {
            "gini": gini,
            "dominant_ids": dominant,
            "neglected_ids": neglected,
            "is_imbalanced": is_imbalanced,
        }

    def _compute_neglected(self, counts: dict[str, int]) -> list[str]:
        """
        Return memory IDs in the bottom 50% of retrieval count.

        If all counts are equal, returns empty list (no one is neglected).
        Memories with zero retrievals are always considered neglected
        when other memories have retrievals.
        """
        if not counts:
            return []

        values = list(counts.values())
        total = sum(values)

        # If nothing has been retrieved, everything is equally neglected
        if total == 0:
            return list(counts.keys())

        # If all equal, none are neglected
        if len(set(values)) == 1:
            return []

        # Sort by count ascending
        sorted_items = sorted(counts.items(), key=lambda x: x[1])
        median_idx = len(sorted_items) // 2

        # Bottom 50%: memories with counts strictly below the median value
        median_value = sorted_items[median_idx][1]
        neglected = [mid for mid, cnt in sorted_items if cnt < median_value]
        return neglected

    def _compute_dominant(self, counts: dict[str, int]) -> list[str]:
        """
        Return memory IDs in the top 50% of retrieval count.

        Only includes memories with counts strictly above the median.
        """
        if not counts:
            return []

        values = list(counts.values())
        total = sum(values)
        if total == 0:
            return []

        if len(set(values)) == 1:
            return []

        sorted_items = sorted(counts.items(), key=lambda x: x[1])
        median_idx = len(sorted_items) // 2
        median_value = sorted_items[median_idx][1]
        dominant = [mid for mid, cnt in sorted_items if cnt > median_value]
        return dominant

    def get_neglected_memories(
        self, cluster_id: str, memory_ids: list[str]
    ) -> list[str]:
        """
        Return memory IDs in the bottom 50% of retrieval count within a cluster.

        Convenience method wrapping _get_retrieval_counts and _compute_neglected.

        Args:
            cluster_id: Identifier of the cluster.
            memory_ids: All memory IDs that belong to this cluster.

        Returns:
            List of neglected memory IDs.
        """
        if not memory_ids:
            return []
        counts = self._get_retrieval_counts(cluster_id, memory_ids)
        return self._compute_neglected(counts)

    def find_blind_spots(
        self,
        cluster_memories: Optional[dict[str, list[str]]] = None,
    ) -> list[dict]:
        """
        Find all clusters with retrieval imbalance above threshold.

        Args:
            cluster_memories: Dict mapping cluster_id to list of all
                memory IDs in that cluster.  If not provided, discovers
                clusters from retrieval_log (but won't know about
                never-retrieved memories).

        Returns:
            List of dicts: [{cluster_id, gini, dominant, neglected}].
        """
        if cluster_memories is None:
            # Discover clusters from retrieval log
            cur = self.conn.cursor()
            cur.execute(
                "SELECT DISTINCT cluster_id FROM retrieval_log "
                "WHERE cluster_id IS NOT NULL"
            )
            cluster_ids = [row[0] for row in cur.fetchall()]
            cluster_memories = {}
            for cid in cluster_ids:
                cur.execute(
                    "SELECT DISTINCT memory_id FROM retrieval_log "
                    "WHERE cluster_id = ?",
                    (cid,),
                )
                cluster_memories[cid] = [row[0] for row in cur.fetchall()]

        spots = []
        for cluster_id, memory_ids in cluster_memories.items():
            result = self.analyze_cluster(cluster_id, memory_ids)
            if result["is_imbalanced"]:
                spot = {
                    "cluster_id": cluster_id,
                    "gini": result["gini"],
                    "dominant": result["dominant_ids"],
                    "neglected": result["neglected_ids"],
                }
                spots.append(spot)
                self._persist_blind_spot(spot)

        return spots

    def _persist_blind_spot(self, spot: dict) -> None:
        """Write a blind spot record to the database."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO retrieval_blind_spots "
            "(cluster_id, gini_coefficient, dominant_ids, neglected_ids, detected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                spot["cluster_id"],
                spot["gini"],
                json.dumps(spot["dominant"]),
                json.dumps(spot["neglected"]),
                now,
            ),
        )
        self.conn.commit()

    # ── Stats ───────────────────────────────────────────────────────────

    def get_retrieval_stats(self) -> dict:
        """
        Return overall retrieval stats.

        Returns:
            Dict with keys: total_retrievals, unique_memories_retrieved,
            clusters_analyzed, blind_spots_found.
        """
        cur = self.conn.cursor()

        cur.execute("SELECT COUNT(*) FROM retrieval_log")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT memory_id) FROM retrieval_log")
        unique = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT cluster_id) FROM retrieval_blind_spots"
        )
        clusters_analyzed = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM retrieval_blind_spots")
        blind_spots = cur.fetchone()[0]

        return {
            "total_retrievals": total,
            "unique_memories_retrieved": unique,
            "clusters_analyzed": clusters_analyzed,
            "blind_spots_found": blind_spots,
        }

    # ── Cleanup ─────────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
        except Exception:
            pass
