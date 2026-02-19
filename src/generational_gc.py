"""
Generational garbage collection for memory lifecycle management.

Divides the memory store into three generations based on age and applies
graduated collection policies inspired by generational GC (Ungar, 1984):

- **Generation 0 (nursery):** Memories <7 days old. Collected daily.
  Memories not accessed or reinforced are candidates for archival.
- **Generation 1 (young):** Memories 7-90 days old. Collected weekly.
  Must have >=2 accesses OR importance >0.5 to survive.
- **Generation 2 (tenured):** Memories 90+ days old. Collected monthly.
  Only archived if importance <0.15 AND no accesses in 60 days AND no
  relationship links.

Collection does NOT actually archive files — it returns the list of memory
IDs that should be archived.  The caller handles actual archival.

Usage:
    from memory_system.generational_gc import GenerationalGC

    gc = GenerationalGC(db_path="path/to/gc.db")
    result = gc.run_daily()   # Collects gen-0
    result = gc.run_weekly()  # Collects gen-0 and gen-1
    result = gc.run_monthly() # Collects all generations
    stats  = gc.get_generation_stats()
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Generation boundaries (days) ─────────────────────────────────────────────

GEN_0_MAX_DAYS = 7    # Nursery: 0-6 days
GEN_1_MAX_DAYS = 90   # Young:   7-89 days
# Gen 2: 90+ days (tenured)

# ── Collection thresholds ────────────────────────────────────────────────────

# Gen 0: collected if access_count == 0
# Gen 1: collected if access_count < 2 AND importance <= 0.5
GEN_1_MIN_ACCESS = 2
GEN_1_MIN_IMPORTANCE = 0.5

# Gen 2: collected only when ALL three conditions are true:
GEN_2_MAX_IMPORTANCE = 0.15       # importance must be < 0.15
GEN_2_ACCESS_STALE_DAYS = 60      # no accesses in 60 days
# AND no relationship links


class GenerationalGC:
    """
    Three-generation garbage collector for the memory store.

    Each instance manages its own SQLite database with tables for generation
    tracking and GC event history.  The caller provides importance, access
    counts, etc. via a mock_memories table (created externally for testing).
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        """
        Initialize the generational GC database.

        Args:
            db_path: Path to the SQLite database file.  Defaults to
                     ``generational_gc.db`` in the package root.
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "generational_gc.db"
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        try:
            self._init_db()
        except Exception:
            self.conn.close()
            raise

    # ── Schema ────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        cur = self.conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS memory_generations (
                memory_id TEXT PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 0,
                promoted_at TEXT,
                collection_survived INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS gc_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                generation INTEGER NOT NULL,
                collected_count INTEGER NOT NULL,
                promoted_count INTEGER NOT NULL,
                total_in_generation INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_mg_generation "
            "ON memory_generations(generation)"
        )

        self.conn.commit()

    # ── Generation assignment ─────────────────────────────────────────────

    def assign_generation(self, memory_id: str, created_at: datetime) -> int:
        """
        Assign a memory to generation 0, 1, or 2 based on its age.

        Args:
            memory_id: Unique memory identifier.
            created_at: When the memory was created (timezone-aware UTC).

        Returns:
            The generation number (0, 1, or 2).
        """
        now = datetime.now(timezone.utc)
        age_days = (now - created_at).total_seconds() / 86400

        if age_days < GEN_0_MAX_DAYS:
            gen = 0
        elif age_days < GEN_1_MAX_DAYS:
            gen = 1
        else:
            gen = 2

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO memory_generations (memory_id, generation, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET generation = excluded.generation
        """, (memory_id, gen, created_at.isoformat()))
        self.conn.commit()

        return gen

    # ── Promotion ─────────────────────────────────────────────────────────

    def promote(self, memory_id: str) -> int:
        """
        Promote a memory to the next generation (survived collection).

        Args:
            memory_id: The memory to promote.

        Returns:
            The new generation number.

        Raises:
            ValueError: If the memory is not tracked.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT generation, collection_survived FROM memory_generations WHERE memory_id = ?",
            (memory_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Memory '{memory_id}' not found in generation tracker")

        current_gen = row["generation"]
        survived = row["collection_survived"]
        new_gen = min(current_gen + 1, 2)
        now_iso = datetime.now(timezone.utc).isoformat()

        cur.execute("""
            UPDATE memory_generations
            SET generation = ?, promoted_at = ?, collection_survived = ?
            WHERE memory_id = ?
        """, (new_gen, now_iso, survived + 1, memory_id))
        self.conn.commit()

        return new_gen

    # ── Collection ────────────────────────────────────────────────────────

    def collect_generation(self, generation: int) -> list[str]:
        """
        Run garbage collection on a specific generation.

        Returns a list of memory IDs that should be archived.  Does NOT
        delete or modify the generation tracking rows — the caller is
        responsible for actual archival.

        Args:
            generation: 0, 1, or 2.

        Returns:
            List of memory IDs to archive.

        Raises:
            ValueError: If generation is not 0, 1, or 2.
        """
        if generation not in (0, 1, 2):
            raise ValueError(f"Invalid generation {generation}. Must be 0, 1, or 2.")

        cur = self.conn.cursor()

        # Get all memories in this generation
        cur.execute(
            "SELECT memory_id FROM memory_generations WHERE generation = ?",
            (generation,)
        )
        gen_members = [row["memory_id"] for row in cur.fetchall()]
        total_in_gen = len(gen_members)

        if total_in_gen == 0:
            self._record_gc_event(generation, 0, 0, 0)
            return []

        collected: list[str] = []
        promoted: list[str] = []

        for mid in gen_members:
            # Fetch mock memory signals
            cur.execute(
                "SELECT importance, access_count, last_accessed, has_links "
                "FROM mock_memories WHERE memory_id = ?",
                (mid,)
            )
            mem_row = cur.fetchone()
            if mem_row is None:
                # No metadata available — keep it (safe default)
                promoted.append(mid)
                continue

            importance = mem_row["importance"]
            access_count = mem_row["access_count"]
            last_accessed = mem_row["last_accessed"]
            has_links = bool(mem_row["has_links"])

            should_collect = self._should_collect(
                generation, importance, access_count, last_accessed, has_links
            )

            if should_collect:
                collected.append(mid)
            else:
                promoted.append(mid)

        self._record_gc_event(generation, len(collected), len(promoted), total_in_gen)
        return collected

    def _should_collect(
        self,
        generation: int,
        importance: float,
        access_count: int,
        last_accessed: str | None,
        has_links: bool,
    ) -> bool:
        """Determine if a memory should be collected based on generation rules."""
        if generation == 0:
            # Nursery: collected if never accessed or reinforced
            return access_count == 0

        elif generation == 1:
            # Young: must have >=2 accesses OR importance >0.5 to survive
            survives = access_count >= GEN_1_MIN_ACCESS or importance > GEN_1_MIN_IMPORTANCE
            return not survives

        elif generation == 2:
            # Tenured: only collected if ALL three conditions met
            if importance >= GEN_2_MAX_IMPORTANCE:
                return False
            if has_links:
                return False
            # Check access recency
            if last_accessed is not None:
                now = datetime.now(timezone.utc)
                last_dt = datetime.fromisoformat(last_accessed)
                # Make timezone-aware if needed
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_since = (now - last_dt).total_seconds() / 86400
                if days_since < GEN_2_ACCESS_STALE_DAYS:
                    return False
            # All three conditions met
            return True

        return False

    def _record_gc_event(
        self,
        generation: int,
        collected_count: int,
        promoted_count: int,
        total_in_generation: int,
    ) -> None:
        """Record a GC collection event."""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO gc_events (generation, collected_count, promoted_count,
                                   total_in_generation, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (generation, collected_count, promoted_count, total_in_generation,
              datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    # ── Scheduled runs ────────────────────────────────────────────────────

    def run_daily(self) -> dict:
        """
        Run daily collection: gen-0 only.

        Returns:
            Dict with gen_0 results.
        """
        collected_0 = self.collect_generation(0)
        return {
            "gen_0": {
                "collected": collected_0,
                "count": len(collected_0),
            }
        }

    def run_weekly(self) -> dict:
        """
        Run weekly collection: gen-0 and gen-1.

        Returns:
            Dict with gen_0 and gen_1 results.
        """
        collected_0 = self.collect_generation(0)
        collected_1 = self.collect_generation(1)
        return {
            "gen_0": {
                "collected": collected_0,
                "count": len(collected_0),
            },
            "gen_1": {
                "collected": collected_1,
                "count": len(collected_1),
            },
        }

    def run_monthly(self) -> dict:
        """
        Run monthly collection: all generations.

        Returns:
            Dict with gen_0, gen_1, and gen_2 results.
        """
        collected_0 = self.collect_generation(0)
        collected_1 = self.collect_generation(1)
        collected_2 = self.collect_generation(2)
        return {
            "gen_0": {
                "collected": collected_0,
                "count": len(collected_0),
            },
            "gen_1": {
                "collected": collected_1,
                "count": len(collected_1),
            },
            "gen_2": {
                "collected": collected_2,
                "count": len(collected_2),
            },
        }

    # ── Stats and history ─────────────────────────────────────────────────

    def get_generation_stats(self) -> dict:
        """
        Return counts and age information per generation.

        Returns:
            Dict with gen_0, gen_1, gen_2 sub-dicts (count, avg_age_days)
            and a total count.
        """
        cur = self.conn.cursor()
        stats: dict = {}
        total = 0

        for gen in (0, 1, 2):
            cur.execute(
                "SELECT COUNT(*) as cnt FROM memory_generations WHERE generation = ?",
                (gen,)
            )
            count = cur.fetchone()["cnt"]
            total += count

            # Average age
            cur.execute(
                "SELECT created_at FROM memory_generations WHERE generation = ?",
                (gen,)
            )
            rows = cur.fetchall()
            if rows:
                now = datetime.now(timezone.utc)
                ages = []
                for r in rows:
                    created = datetime.fromisoformat(r["created_at"])
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    ages.append((now - created).total_seconds() / 86400)
                avg_age = sum(ages) / len(ages)
            else:
                avg_age = 0.0

            stats[f"gen_{gen}"] = {
                "count": count,
                "avg_age_days": round(avg_age, 1),
            }

        stats["total"] = total
        return stats

    def get_gc_history(self, limit: int = 50) -> list[dict]:
        """
        Return recent GC events, most recent first.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of event dicts.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM gc_events ORDER BY event_id DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cur.fetchall()]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
