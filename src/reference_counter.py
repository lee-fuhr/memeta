"""
Reference counting for memory dependencies.

Based on Collins (1960) reference counting. Tracks how many other objects
point to each memory: relationship graph edges, chunk sources, decision
references, synthesis inputs. High ref count = protected from archival.
Zero refs + low importance = fast-tracked for GC.

Usage:
    from memory_system.reference_counter import ReferenceCounter

    rc = ReferenceCounter(db_path="intelligence.db")
    rc.increment("mem-abc123", ref_type="relationship")
    rc.increment("mem-abc123", ref_type="chunk")

    counts = rc.get_count("mem-abc123")
    # {'relationship': 1, 'chunk': 1, 'decision': 0, 'synthesis': 0, 'total': 2}

    if rc.is_protected("mem-abc123"):
        print("Memory has references — skip archival")

    orphans = rc.get_zero_ref_memories()
    # ['mem-old1', 'mem-old2']  — candidates for GC
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional


# Canonical ref types
REF_TYPES = ("relationship", "chunk", "decision", "synthesis")


class ReferenceCounter:
    """Track reference counts per memory per reference type."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reference_counts (
                    memory_id TEXT NOT NULL,
                    ref_type TEXT NOT NULL,
                    ref_count INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (memory_id, ref_type)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_refcount_memory
                ON reference_counts(memory_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_refcount_type
                ON reference_counts(ref_type)
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def increment(self, memory_id: str, ref_type: str = "relationship") -> int:
        """Increment reference count for a memory. Returns new total for this type."""
        now = self._now()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO reference_counts (memory_id, ref_type, ref_count, last_updated)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(memory_id, ref_type)
                DO UPDATE SET
                    ref_count = ref_count + 1,
                    last_updated = excluded.last_updated
            """, (memory_id, ref_type, now))
            conn.commit()
            row = conn.execute(
                "SELECT ref_count FROM reference_counts WHERE memory_id=? AND ref_type=?",
                (memory_id, ref_type),
            ).fetchone()
            return row["ref_count"] if row else 0
        finally:
            conn.close()

    def decrement(self, memory_id: str, ref_type: str = "relationship") -> int:
        """Decrement reference count. Returns new total for this type. Never goes below 0."""
        now = self._now()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT ref_count FROM reference_counts WHERE memory_id=? AND ref_type=?",
                (memory_id, ref_type),
            ).fetchone()
            if row is None or row["ref_count"] <= 0:
                # Nothing to decrement — ensure a zero row exists
                conn.execute("""
                    INSERT INTO reference_counts (memory_id, ref_type, ref_count, last_updated)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(memory_id, ref_type)
                    DO UPDATE SET last_updated = excluded.last_updated
                """, (memory_id, ref_type, now))
                conn.commit()
                return 0
            new_count = max(row["ref_count"] - 1, 0)
            conn.execute("""
                UPDATE reference_counts
                SET ref_count = ?, last_updated = ?
                WHERE memory_id = ? AND ref_type = ?
            """, (new_count, now, memory_id, ref_type))
            conn.commit()
            return new_count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_count(self, memory_id: str) -> dict:
        """Get reference counts by type. Returns dict with each type and total."""
        result = {t: 0 for t in REF_TYPES}
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT ref_type, ref_count FROM reference_counts WHERE memory_id=?",
                (memory_id,),
            ).fetchall()
            for row in rows:
                rt = row["ref_type"]
                if rt in result:
                    result[rt] = row["ref_count"]
            result["total"] = sum(result[t] for t in REF_TYPES)
            return result
        finally:
            conn.close()

    def get_zero_ref_memories(self) -> list[str]:
        """Return memory IDs with zero total references."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT memory_id, SUM(ref_count) as total
                FROM reference_counts
                GROUP BY memory_id
                HAVING total = 0
            """).fetchall()
            return [row["memory_id"] for row in rows]
        finally:
            conn.close()

    def get_highly_referenced(self, min_refs: int = 3) -> list[dict]:
        """Return memories with total reference count >= min_refs."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT memory_id, SUM(ref_count) as total
                FROM reference_counts
                GROUP BY memory_id
                HAVING total >= ?
                ORDER BY total DESC
            """, (min_refs,)).fetchall()
            return [{"memory_id": row["memory_id"], "total": row["total"]} for row in rows]
        finally:
            conn.close()

    def is_protected(self, memory_id: str) -> bool:
        """Return True if memory has any references (should not be archived)."""
        counts = self.get_count(memory_id)
        return counts["total"] > 0

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def bulk_update_from_relationships(self, edges: list[tuple[str, str]]) -> dict:
        """
        Recompute relationship ref counts from a full edge list.

        Each edge (A, B) means A links to B. Both A and B get +1 relationship
        ref since both participate in the relationship graph.

        This is a full recompute: all existing relationship counts are reset
        to zero, then rebuilt from edges. Other ref types are untouched.

        Returns {updated: N} where N is number of distinct memories updated.
        """
        # Count refs per memory from edges
        ref_counts: dict[str, int] = {}
        for source, target in edges:
            ref_counts[source] = ref_counts.get(source, 0) + 1
            ref_counts[target] = ref_counts.get(target, 0) + 1

        now = self._now()
        conn = self._connect()
        try:
            # Zero out all existing relationship counts
            conn.execute("""
                UPDATE reference_counts
                SET ref_count = 0, last_updated = ?
                WHERE ref_type = 'relationship'
            """, (now,))

            # Upsert new counts
            for memory_id, count in ref_counts.items():
                conn.execute("""
                    INSERT INTO reference_counts (memory_id, ref_type, ref_count, last_updated)
                    VALUES (?, 'relationship', ?, ?)
                    ON CONFLICT(memory_id, ref_type)
                    DO UPDATE SET
                        ref_count = excluded.ref_count,
                        last_updated = excluded.last_updated
                """, (memory_id, count, now))

            conn.commit()
            return {"updated": len(ref_counts)}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def find_dangling_references(self, active_memory_ids: set[str]) -> list[dict]:
        """
        Find references pointing to archived/deleted memories.

        Returns list of dicts with memory_id and total for memories that
        have reference counts but are NOT in the active_memory_ids set.
        """
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT memory_id, SUM(ref_count) as total
                FROM reference_counts
                GROUP BY memory_id
                HAVING total > 0
            """).fetchall()
            dangling = []
            for row in rows:
                if row["memory_id"] not in active_memory_ids:
                    dangling.append({
                        "memory_id": row["memory_id"],
                        "total": row["total"],
                    })
            return dangling
        finally:
            conn.close()

    def get_ref_distribution(self) -> dict:
        """
        Return reference count distribution across all tracked memories.

        Returns {zero_refs: N, one_ref: N, two_refs: N, three_plus: N, max_refs: N}.
        """
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT memory_id, SUM(ref_count) as total
                FROM reference_counts
                GROUP BY memory_id
            """).fetchall()

            dist = {
                "zero_refs": 0,
                "one_ref": 0,
                "two_refs": 0,
                "three_plus": 0,
                "max_refs": 0,
            }

            if not rows:
                return dist

            max_total = 0
            for row in rows:
                total = row["total"]
                if total > max_total:
                    max_total = total
                if total == 0:
                    dist["zero_refs"] += 1
                elif total == 1:
                    dist["one_ref"] += 1
                elif total == 2:
                    dist["two_refs"] += 1
                else:
                    dist["three_plus"] += 1

            dist["max_refs"] = max_total
            return dist
        finally:
            conn.close()
