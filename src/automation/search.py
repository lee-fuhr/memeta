"""
Feature 30: Memory-Aware Search

Natural language queries with multiple filter dimensions.

Capabilities:
- Semantic search via embeddings
- Temporal filtering (date ranges, relative dates)
- Project/tag filtering
- Importance ranking
- Combined multi-dimensional queries

Database: intelligence.db (search_history table for query analytics)
"""

import json
import time
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

from memory_system.db_pool import get_connection
from memory_system.memory_ts_client import MemoryTSClient, Memory
from memory_system.intelligence.search_optimizer import SearchOptimizer


@dataclass
class SearchQuery:
    """Structured search query with multiple filter dimensions"""
    text_query: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    min_importance: Optional[float] = None
    max_importance: Optional[float] = None
    project_id: Optional[str] = None
    tags: Optional[List[str]] = None
    exclude_tags: Optional[List[str]] = None
    limit: int = 20
    order_by: str = "importance"  # "importance", "recency", "relevance"


@dataclass
class SearchResult:
    """Search result with relevance scoring"""
    memory: Memory
    relevance_score: float
    match_reason: str  # What caused this result to match


class MemoryAwareSearch:
    """
    Multi-dimensional search over memories with natural language support.

    Capabilities:
    - Semantic search via content similarity
    - Temporal filtering (absolute and relative dates)
    - Project and tag filtering
    - Importance range filtering
    - Natural language query parsing
    - Query history tracking

    Example:
        search = MemoryAwareSearch()

        # Simple content search
        results = search.search("client feedback about design")

        # Advanced multi-dimensional query
        results = search.search_advanced(
            text_query="deadline",
            date_start=datetime(2026, 1, 1),
            min_importance=0.7,
            project_id="ClientX",
            tags=["urgent"]
        )

        # Natural language query
        results = search.search_natural(
            "What did I learn about API design last month?"
        )

        # Query history
        history = search.get_search_history(limit=10)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize search system.

        Args:
            db_path: Path to intelligence.db for history tracking
        """
        self.client = MemoryTSClient()

        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self.optimizer = SearchOptimizer(db_path=str(self.db_path))
        self._init_db()

    def _init_db(self):
        """Create search history table."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_text TEXT NOT NULL,
                    query_struct TEXT NOT NULL,
                    results_count INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_search_history_timestamp
                ON search_history(timestamp DESC)
            """)

            conn.commit()

    def search(self, query: str, limit: int = 20) -> List[SearchResult]:
        """
        Simple content search.

        Args:
            query: Search query text
            limit: Maximum results

        Returns:
            List of SearchResult objects
        """
        def _search_fn(q: str) -> list:
            return self.client.search(content=q)

        memories = self.optimizer.search_with_cache(query, _search_fn)
        memories = self.optimizer.rank_results(memories, query)[:limit]

        search_results = [
            SearchResult(memory=mem, relevance_score=mem.importance, match_reason="Content match")
            for mem in memories
        ]

        self._log_search(query, {}, len(search_results))

        return search_results

    def search_advanced(
        self,
        text_query: Optional[str] = None,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        min_importance: Optional[float] = None,
        max_importance: Optional[float] = None,
        project_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        limit: int = 20,
        order_by: str = "importance"
    ) -> List[SearchResult]:
        """
        Advanced multi-dimensional search.

        Args:
            text_query: Semantic search query
            date_start: Filter memories created after this date
            date_end: Filter memories created before this date
            min_importance: Minimum importance score
            max_importance: Maximum importance score
            project_id: Filter by project
            tags: Include memories with any of these tags
            exclude_tags: Exclude memories with these tags
            limit: Maximum results
            order_by: Sort order (importance | recency | relevance)

        Returns:
            List of SearchResult objects
        """
        # Start with base search or all memories — use cache when text query present
        if text_query:
            def _search_fn(q: str) -> list:
                return self.client.search(content=q)

            memories = self.optimizer.search_with_cache(
                text_query, _search_fn, project_id=project_id
            )
        else:
            memories = self.client.search(content="", project_id=project_id)

        filtered = []

        for mem in memories:
            # Apply filters
            if date_start and mem.created < date_start:
                continue

            if date_end and mem.created > date_end:
                continue

            if min_importance is not None and mem.importance < min_importance:
                continue

            if max_importance is not None and mem.importance > max_importance:
                continue

            if project_id and mem.project_id != project_id:
                continue

            if tags and not any(tag in mem.tags for tag in tags):
                continue

            if exclude_tags and any(tag in mem.tags for tag in exclude_tags):
                continue

            match_reasons = []
            if text_query:
                match_reasons.append("Content match")
            if tags and any(tag in mem.tags for tag in tags):
                match_reasons.append(f"Tag: {', '.join([t for t in tags if t in mem.tags])}")
            if min_importance and mem.importance >= min_importance:
                match_reasons.append(f"High importance ({mem.importance:.2f})")

            filtered.append(SearchResult(
                memory=mem,
                relevance_score=self._calculate_relevance(mem, text_query, order_by),
                match_reason="; ".join(match_reasons) if match_reasons else "Filter match"
            ))

        # Sort by requested order
        if order_by == "importance":
            filtered.sort(key=lambda r: r.memory.importance, reverse=True)
        elif order_by == "recency":
            filtered.sort(key=lambda r: r.memory.created, reverse=True)
        elif order_by == "relevance":
            # Delegate to F28 optimizer for multi-factor ranking
            ranked_memories = self.optimizer.rank_results(
                [r.memory for r in filtered], text_query
            )
            memory_order = {mem.id: i for i, mem in enumerate(ranked_memories)}
            filtered.sort(key=lambda r: memory_order.get(r.memory.id, len(filtered)))

        results = filtered[:limit]

        # Log search
        query_dict = {
            "text_query": text_query,
            "date_start": date_start.isoformat() if date_start else None,
            "date_end": date_end.isoformat() if date_end else None,
            "min_importance": min_importance,
            "project_id": project_id,
            "tags": tags
        }
        self._log_search(text_query or "(filtered search)", query_dict, len(results))

        return results

    def search_natural(self, query: str, limit: int = 20) -> List[SearchResult]:
        """
        Natural language query with automatic parsing.

        Args:
            query: Natural language query
            limit: Maximum results

        Returns:
            List of SearchResult objects
        """
        parsed = self.parse_natural_query(query)

        return self.search_advanced(
            text_query=parsed.text_query,
            date_start=parsed.date_start,
            date_end=parsed.date_end,
            min_importance=parsed.min_importance,
            project_id=parsed.project_id,
            tags=parsed.tags,
            limit=limit,
            order_by=parsed.order_by
        )

    def parse_natural_query(self, query: str) -> SearchQuery:
        """
        Parse natural language query into structured search.

        Extracts:
        - Temporal references (last week, yesterday, January, etc.)
        - Importance indicators (important, critical, minor)
        - Project mentions
        - Tag references

        Args:
            query: Natural language query

        Returns:
            SearchQuery object
        """
        search_query = SearchQuery()
        query_lower = query.lower()

        # Extract text query (remove filter keywords)
        search_query.text_query = query

        # Temporal extraction
        now = datetime.now()

        if "today" in query_lower:
            search_query.date_start = datetime(now.year, now.month, now.day)
        elif "yesterday" in query_lower:
            yesterday = now - timedelta(days=1)
            search_query.date_start = datetime(yesterday.year, yesterday.month, yesterday.day)
            search_query.date_end = datetime(now.year, now.month, now.day)
        elif "last week" in query_lower or "past week" in query_lower:
            search_query.date_start = now - timedelta(days=7)
        elif "last month" in query_lower or "past month" in query_lower:
            search_query.date_start = now - timedelta(days=30)
        elif "last year" in query_lower:
            search_query.date_start = now - timedelta(days=365)

        # Month names
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12
        }
        for month_name, month_num in months.items():
            if month_name in query_lower:
                search_query.date_start = datetime(now.year, month_num, 1)
                # End of month
                if month_num == 12:
                    search_query.date_end = datetime(now.year + 1, 1, 1)
                else:
                    search_query.date_end = datetime(now.year, month_num + 1, 1)
                break

        # Importance extraction
        if any(word in query_lower for word in ["important", "critical", "crucial", "key"]):
            search_query.min_importance = 0.7
        elif "minor" in query_lower or "small" in query_lower:
            search_query.max_importance = 0.5

        # Project extraction (simple pattern: "project X", "in X")
        project_match = re.search(r'(?:project|in|about)\s+([A-Z][A-Za-z0-9_-]+)', query)
        if project_match:
            search_query.project_id = project_match.group(1)

        # Tag extraction (simple pattern: #tag or "tagged X")
        tags_found = re.findall(r'#(\w+)', query)
        if tags_found:
            search_query.tags = tags_found

        # Order by extraction
        if "recent" in query_lower or "latest" in query_lower or "newest" in query_lower:
            search_query.order_by = "recency"
        elif "relevant" in query_lower or "similar" in query_lower:
            search_query.order_by = "relevance"

        return search_query

    def get_search_history(self, limit: int = 20) -> List[Dict]:
        """
        Get recent search history.

        Args:
            limit: Maximum history entries

        Returns:
            List of search history dictionaries
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT query_text, query_struct, results_count, timestamp
                FROM search_history
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            history = []
            for row in cursor.fetchall():
                history.append({
                    'query_text': row[0],
                    'query_struct': json.loads(row[1]),
                    'results_count': row[2],
                    'timestamp': datetime.fromtimestamp(row[3])
                })

            return history

    def _calculate_relevance(self, memory: Memory, query: Optional[str], order_by: str) -> float:
        """Calculate relevance score for sorting."""
        if order_by == "importance":
            return memory.importance
        elif order_by == "recency":
            # Convert datetime to score (higher = more recent)
            return memory.created.timestamp() if memory.created else 0
        elif order_by == "relevance":
            # Combined score
            importance_score = memory.importance * 0.6
            recency_score = (memory.created.timestamp() / datetime.now().timestamp()) * 0.4 if memory.created else 0
            return importance_score + recency_score
        return 0.5

    def _log_search(self, query_text: str, query_struct: Dict, results_count: int):
        """Log search query for analytics."""
        now = int(time.time())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO search_history (query_text, query_struct, results_count, timestamp)
                VALUES (?, ?, ?, ?)
            """, (query_text, json.dumps(query_struct), results_count, now))

            conn.commit()
