"""
Feature 28: Memory Search Optimization

Optimizes memory search with caching and improved ranking.

Features:
- Query result caching with 24h TTL
- Improved ranking: semantic + keyword + recency + importance
- Query analytics (foundation for future CTR learning)

Deferred to future:
- Click-through rate learning (needs impression tracking)
- Query embedding pre-computation
- A/B testing framework

Integration:
- Wraps existing hybrid_search functionality
- Works with Memory dataclass from memory_ts_client
"""

import sqlite3
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


class SearchOptimizer:
    """
    Optimizes memory search with caching and improved ranking.

    Core operations:
    - search_with_cache(): Cache-aware search wrapper
    - rank_results(): Improved ranking algorithm
    - record_selection(): Track user selections (for future CTR)
    - get_search_analytics(): Query statistics
    """

    def __init__(self, db_path: str = None):
        """Initialize optimizer with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"

        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        """Create search optimization tables"""
        with get_connection(self.db_path) as conn:
            # Cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    results TEXT NOT NULL,
                    hits INTEGER DEFAULT 0,
                    last_hit INTEGER,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_hits
                ON search_cache(hits DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_expires
                ON search_cache(expires_at)
            """)

            # Analytics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_analytics (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    result_count INTEGER,
                    selected_memory_id TEXT,
                    position INTEGER,
                    created_at INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_analytics_query
                ON search_analytics(query)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_analytics_created
                ON search_analytics(created_at DESC)
            """)

            conn.commit()

    def search_with_cache(
        self,
        query: str,
        search_fn,  # Function that does actual search
        use_cache: bool = True,
        project_id: Optional[str] = None
    ) -> List:
        """
        Cache-aware search wrapper.

        Args:
            query: Search query
            search_fn: Function to call for actual search (takes query)
            use_cache: Enable caching
            project_id: Optional project filter (included in cache key)

        Returns:
            List of Memory objects
        """
        if not use_cache or not query.strip():
            return search_fn(query)

        # Generate cache key (include project_id for scoped caching)
        cache_key = f"{query}|{project_id or 'global'}"
        query_hash = hashlib.md5(cache_key.encode()).hexdigest()

        # Check cache
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT results, expires_at FROM search_cache WHERE query_hash = ?",
                (query_hash,)
            ).fetchone()

            now = int(datetime.now().timestamp())

            if row:
                expires_at = row[1]

                if expires_at > now:
                    # Cache hit!
                    conn.execute(
                        "UPDATE search_cache SET hits = hits + 1, last_hit = ? WHERE query_hash = ?",
                        (now, query_hash)
                    )
                    conn.commit()

                    # Hydrate cached result IDs to Memory objects
                    result_ids = json.loads(row[0])

                    # Import MemoryTSClient for hydration
                    try:
                        from memory_ts_client import MemoryTSClient
                        client = MemoryTSClient()

                        # Hydrate each ID, skip deleted memories
                        hydrated_results = []
                        for memory_id in result_ids:
                            try:
                                memory = client.get(memory_id)
                                if memory:
                                    hydrated_results.append(memory)
                            except (FileNotFoundError, Exception):
                                # Memory was deleted or doesn't exist, skip it
                                continue

                        return hydrated_results
                    except ImportError:
                        # Fallback for tests without actual memory storage
                        # Return empty list (cache invalidated for missing memories)
                        return []

        # Cache miss - perform search
        results = search_fn(query)

        # Cache if worthwhile (3-100 results)
        if 3 <= len(results) <= 100:
            result_ids = [getattr(r, 'id', str(r)) for r in results]
            results_json = json.dumps(result_ids)
            expires_at = now + 86400  # 24 hours

            with get_connection(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO search_cache
                    (query_hash, query, results, hits, last_hit, created_at, expires_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                """, (query_hash, cache_key, results_json, now, now, expires_at))
                conn.commit()

        return results

    def rank_results(
        self,
        results: List,
        query: Optional[str] = None
    ) -> List:
        """
        Improved ranking algorithm.

        Ranking formula:
        score = semantic * 0.5 + keyword * 0.2 + recency * 0.2 + importance * 0.1

        Args:
            results: List of Memory objects with scores
            query: Original query (for keyword matching)

        Returns:
            Re-ranked list of Memory objects
        """
        if not results:
            return results

        now = datetime.now()
        scored_results = []

        for memory in results:
            # Get existing scores (from hybrid search)
            semantic_score = getattr(memory, 'semantic_score', 0.5)
            keyword_score = getattr(memory, 'keyword_score', 0.0)

            # Recency score (clamped to prevent negatives)
            try:
                created = datetime.fromisoformat(memory.created)
                days_old = (now - created).days
                recency_score = max(0.0, 1.0 - (days_old / 365.0))
            except Exception:
                recency_score = 0.5  # Default for invalid dates

            # Importance score
            importance_score = getattr(memory, 'importance', 0.5)

            # Combined score (no CTR component yet - needs impression tracking)
            combined_score = (
                semantic_score * 0.5 +
                keyword_score * 0.2 +
                recency_score * 0.2 +
                importance_score * 0.1
            )

            scored_results.append((memory, combined_score))

        # Sort by combined score descending
        scored_results.sort(key=lambda x: x[1], reverse=True)

        return [mem for mem, score in scored_results]

    def record_selection(
        self,
        query: str,
        memory_id: str,
        position: int,
        result_count: int
    ):
        """
        Record user selection (for future CTR learning).

        Args:
            query: Search query
            memory_id: Selected memory ID
            position: Position in results (1-based)
            result_count: Total results shown
        """
        analytics_id = hashlib.md5(
            f"{query}-{memory_id}-{datetime.now().timestamp()}".encode()
        ).hexdigest()[:16]

        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO search_analytics
                (id, query, result_count, selected_memory_id, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (analytics_id, query, result_count, memory_id, position, now))
            conn.commit()

    def get_search_analytics(self, days: int = 7) -> dict:
        """
        Get search analytics for last N days.

        Args:
            days: Look back period

        Returns:
            dict with total_searches, avg_results, cache_hit_rate, top_queries
        """
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())

        with get_connection(self.db_path) as conn:
            # Total searches
            total_searches = conn.execute(
                "SELECT COUNT(*) FROM search_analytics WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()[0]

            # Average results
            avg_results_row = conn.execute(
                "SELECT AVG(result_count) FROM search_analytics WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()
            avg_results = avg_results_row[0] if avg_results_row[0] else 0.0

            # Cache stats (all time)
            total_cache_entries = conn.execute(
                "SELECT COUNT(*) FROM search_cache"
            ).fetchone()[0]

            total_hits = conn.execute(
                "SELECT SUM(hits) FROM search_cache"
            ).fetchone()[0] or 0

            cache_hit_rate = total_hits / max(total_searches, 1)

            # Top queries
            cursor = conn.execute("""
                SELECT query, COUNT(*) as query_count
                FROM search_analytics
                WHERE created_at >= ?
                GROUP BY query
                ORDER BY query_count DESC
                LIMIT 5
            """, (cutoff,))

            top_queries = [row[0] for row in cursor.fetchall()]

            return {
                'total_searches': total_searches,
                'avg_results': avg_results,
                'cache_hit_rate': cache_hit_rate,
                'cache_entries': total_cache_entries,
                'total_cache_hits': total_hits,
                'top_queries': top_queries
            }

    def invalidate_cache(self, query: Optional[str] = None, project_id: Optional[str] = None):
        """
        Invalidate cache entries.

        Args:
            query: Specific query to invalidate (if None, clears expired)
            project_id: Optional project filter (must match cache key format)
        """
        with get_connection(self.db_path) as conn:
            if query:
                # Invalidate specific query (use same composite key as storage)
                cache_key = f"{query}|{project_id or 'global'}"
                query_hash = hashlib.md5(cache_key.encode()).hexdigest()
                conn.execute(
                    "DELETE FROM search_cache WHERE query_hash = ?",
                    (query_hash,)
                )
            else:
                # Clean up expired entries
                now = int(datetime.now().timestamp())
                conn.execute(
                    "DELETE FROM search_cache WHERE expires_at < ?",
                    (now,)
                )

            conn.commit()

    def get_cache_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            dict with total_entries, total_hits, hit_rate, most_popular
        """
        with get_connection(self.db_path) as conn:
            total_entries = conn.execute(
                "SELECT COUNT(*) FROM search_cache"
            ).fetchone()[0]

            total_hits = conn.execute(
                "SELECT SUM(hits) FROM search_cache"
            ).fetchone()[0] or 0

            # Most popular cached queries
            cursor = conn.execute("""
                SELECT query, hits
                FROM search_cache
                ORDER BY hits DESC
                LIMIT 5
            """)

            most_popular = [(row[0], row[1]) for row in cursor.fetchall()]

            return {
                'total_entries': total_entries,
                'total_hits': total_hits,
                'most_popular': most_popular
            }
