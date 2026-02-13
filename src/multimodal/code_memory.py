"""
Feature 46: Code memory - Remember code solutions

Code snippet library with semantic search
"How did I solve X before?"
"""

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from ..intelligence_db import IntelligenceDB
# Try to import semantic search (Feature 11) - optional dependency
try:
    from ..semantic_search import SemanticSearch
    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False
    SemanticSearch = None
from ..importance_engine import calculate_importance
from ..memory_ts_client import MemoryTSClient


@dataclass
class CodeMemory:
    """Code snippet with context"""
    snippet: str
    language: str
    description: str
    context: str  # What problem it solved
    file_path: Optional[str] = None
    session_id: Optional[str] = None
    created_at: str = None
    project_id: str = "LFI"
    tags: List[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.tags is None:
            self.tags = ['#code-pattern']

    def snippet_hash(self) -> str:
        """Generate unique hash for deduplication"""
        return hashlib.sha256(self.snippet.encode()).hexdigest()[:16]


class CodeMemoryLibrary:
    """
    Code snippet library with semantic search

    Remembers solutions, patterns, and implementations.
    Enables: "How did I solve async rate limiting before?"
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize code memory library

        Args:
            db_path: Intelligence database path
        """
        self.db = IntelligenceDB(db_path)
        self.memory_client = MemoryTSClient()

        # Use existing semantic search (Feature 11)
        if SEMANTIC_SEARCH_AVAILABLE:
            try:
                self.semantic_search = SemanticSearch()
            except Exception:
                # Fallback if semantic search not available
                self.semantic_search = None
        else:
            self.semantic_search = None

    def save_code_snippet(
        self,
        snippet: str,
        language: str,
        description: str,
        context: str,
        file_path: Optional[str] = None,
        session_id: Optional[str] = None,
        project_id: str = "LFI",
        save_to_memory_ts: bool = True
    ) -> CodeMemory:
        """
        Save code snippet to library

        Args:
            snippet: Code text
            language: Programming language
            description: What this code does
            context: Problem it solves
            file_path: Original file location
            session_id: Session where it was created
            project_id: Project scope
            save_to_memory_ts: Also save to memory-ts

        Returns:
            CodeMemory object

        Raises:
            ValueError: If snippet or description empty
        """
        if not snippet or not description:
            raise ValueError("Snippet and description required")

        code_mem = CodeMemory(
            snippet=snippet,
            language=language,
            description=description,
            context=context,
            file_path=file_path,
            session_id=session_id,
            project_id=project_id
        )

        # Calculate importance (code patterns tend to be high value)
        importance = calculate_importance(f"{description} {context}")
        # Boost code patterns slightly
        importance = min(1.0, importance * 1.2)

        # Generate embedding for semantic search
        embedding = None
        if self.semantic_search:
            try:
                embedding_vector = self.semantic_search.encode(
                    f"{description} {context} {snippet[:200]}"
                )
                embedding = json.dumps(embedding_vector.tolist())
            except Exception as e:
                print(f"Warning: Failed to generate embedding: {e}")

        # Save to intelligence DB
        cursor = self.db.conn.cursor()

        memory_id = None
        if save_to_memory_ts:
            try:
                memory_content = f"{description}\n\nLanguage: {language}\n\n```{language}\n{snippet}\n```\n\nContext: {context}"
                memory_id = self.memory_client.create(
                    content=memory_content,
                    tags=['#code-pattern', f'#lang-{language.lower()}'],
                    project_id=project_id,
                    importance=importance,
                    session_id=session_id
                )
            except Exception as e:
                print(f"Warning: Failed to save to memory-ts: {e}")

        cursor.execute("""
            INSERT INTO code_memories
            (snippet, language, description, context, file_path, session_id, created_at, project_id, tags, embedding, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snippet,
            language,
            description,
            context,
            file_path,
            session_id,
            code_mem.created_at,
            project_id,
            json.dumps(code_mem.tags),
            embedding,
            importance
        ))

        self.db.conn.commit()

        return code_mem

    def search_code(
        self,
        query: str,
        language: Optional[str] = None,
        project_id: Optional[str] = None,
        use_semantic: bool = True,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search code snippets by description or context

        Args:
            query: Search query (e.g., "async rate limiting")
            language: Optional language filter
            project_id: Optional project filter
            use_semantic: Use semantic search if available
            limit: Max results

        Returns:
            List of matching code memories, sorted by relevance
        """
        cursor = self.db.conn.cursor()

        if use_semantic and self.semantic_search:
            # Semantic search using embeddings
            query_embedding = self.semantic_search.encode(query)

            # Get all code memories with embeddings
            sql = "SELECT * FROM code_memories WHERE embedding IS NOT NULL"
            params = []

            if language:
                sql += " AND language = ?"
                params.append(language)

            if project_id:
                sql += " AND project_id = ?"
                params.append(project_id)

            cursor.execute(sql, params)
            results = cursor.fetchall()

            # Calculate similarity scores
            scored_results = []
            for row in results:
                embedding = json.loads(row['embedding'])
                similarity = self.semantic_search.similarity(query_embedding, embedding)
                result_dict = dict(row)
                result_dict['similarity'] = similarity
                scored_results.append(result_dict)

            # Sort by similarity
            scored_results.sort(key=lambda x: x['similarity'], reverse=True)
            return scored_results[:limit]

        else:
            # Keyword search fallback
            sql = """
                SELECT * FROM code_memories
                WHERE (description LIKE ? OR context LIKE ? OR snippet LIKE ?)
            """
            params = [f"%{query}%", f"%{query}%", f"%{query}%"]

            if language:
                sql += " AND language = ?"
                params.append(language)

            if project_id:
                sql += " AND project_id = ?"
                params.append(project_id)

            sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)

            return [dict(row) for row in cursor.fetchall()]

    def get_by_language(self, language: str, limit: int = 50) -> List[Dict]:
        """
        Get all code snippets for a specific language

        Args:
            language: Programming language
            limit: Max results

        Returns:
            List of code memories
        """
        cursor = self.db.conn.cursor()

        cursor.execute("""
            SELECT * FROM code_memories
            WHERE language = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (language, limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_recent(self, days: int = 30, limit: int = 20) -> List[Dict]:
        """
        Get recently saved code snippets

        Args:
            days: Look back this many days
            limit: Max results

        Returns:
            List of recent code memories
        """
        cursor = self.db.conn.cursor()

        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff.replace(day=cutoff.day - days)

        cursor.execute("""
            SELECT * FROM code_memories
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (cutoff.isoformat(), limit))

        return [dict(row) for row in cursor.fetchall()]

    def deduplicate_snippet(self, snippet: str) -> Optional[Dict]:
        """
        Check if snippet already exists (by hash)

        Args:
            snippet: Code text

        Returns:
            Existing code memory if found, None otherwise
        """
        snippet_hash = hashlib.sha256(snippet.encode()).hexdigest()[:16]

        cursor = self.db.conn.cursor()

        # Simple dedup by exact snippet match
        cursor.execute("""
            SELECT * FROM code_memories
            WHERE snippet = ?
            LIMIT 1
        """, (snippet,))

        result = cursor.fetchone()
        return dict(result) if result else None

    def close(self):
        """Close database connection"""
        self.db.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close on context exit"""
        self.close()
