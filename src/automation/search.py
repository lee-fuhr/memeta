"""
Feature 30: Memory-Aware Search

Natural language queries:
- "Find memories about X from last month"
- "What did I learn about Y while working on Z?"
- "Show me all insights about client work"

Combines:
- Semantic search (sentence-transformers)
- Temporal filtering (date ranges)
- Project/tag filtering
- Importance ranking
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))
import semantic_search
from memory_ts_client import MemoryTSClient, Memory


@dataclass
class SearchQuery:
    """Structured search query"""
    text_query: Optional[str] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    min_importance: Optional[float] = None
    project_id: Optional[str] = None
    tags: Optional[List[str]] = None
    limit: int = 20


class MemoryAwareSearch:
    """
    Natural language search over memories.
    
    Example:
        search = MemoryAwareSearch()
        
        # Simple text search
        results = search.search("deadline")
        
        # Advanced query
        results = search.search_advanced(
            text_query="client feedback",
            date_start=datetime(2026, 1, 1),
            min_importance=0.7,
            project_id="ClientX"
        )
    """

    def __init__(self):
        self.client = MemoryTSClient()

    def search(self, query: str, limit: int = 20) -> List[Memory]:
        """Simple text search."""
        return semantic_search.semantic_search(query, limit=limit)

    def search_advanced(
        self,
        text_query: Optional[str] = None,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        min_importance: Optional[float] = None,
        project_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Memory]:
        """Advanced search with filters."""
        # Start with all memories
        all_memories = self.client.search()
        
        filtered = all_memories
        
        # Apply filters
        if date_start:
            filtered = [m for m in filtered if m.created_at >= date_start]
        
        if date_end:
            filtered = [m for m in filtered if m.created_at <= date_end]
        
        if min_importance:
            filtered = [m for m in filtered if m.importance >= min_importance]
        
        if project_id:
            filtered = [m for m in filtered if m.project_id == project_id]
        
        if tags:
            filtered = [m for m in filtered if any(tag in m.tags for tag in tags)]
        
        # Apply text search if provided
        if text_query:
            # Semantic search on filtered set
            filtered_ids = {m.id for m in filtered}
            semantic_results = semantic_search.semantic_search(text_query, limit=limit * 2)
            filtered = [m for m in semantic_results if m.id in filtered_ids]
        
        # Sort by importance
        filtered.sort(key=lambda m: m.importance, reverse=True)
        
        return filtered[:limit]

    def parse_natural_query(self, query: str) -> SearchQuery:
        """Parse natural language query into structured search."""
        # TODO: Use LLM to extract query components
        # For now, simple implementation
        
        search_query = SearchQuery()
        search_query.text_query = query
        
        # Extract date mentions (simple)
        if "last week" in query.lower():
            search_query.date_start = datetime.now() - timedelta(days=7)
        elif "last month" in query.lower():
            search_query.date_start = datetime.now() - timedelta(days=30)
        
        # Extract importance
        if "important" in query.lower():
            search_query.min_importance = 0.7
        
        return search_query
