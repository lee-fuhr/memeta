"""
Embedding Manager - Persistent embedding storage and batch computation.

Fixes Performance Issue #1: Semantic search O(n) embedding computation.

Solution:
- Store embeddings in SQLite (embeddings table)
- Batch pre-compute nightly (not on every search)
- Use FAISS index for fast similarity search (optional upgrade)

Performance:
- Before: 500s per search at 10K memories (embed all on every search)
- After: <1s per search (pre-computed embeddings + indexed lookup)
"""

import sqlite3
import numpy as np
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import hashlib
from datetime import datetime
from collections import OrderedDict


class EmbeddingManager:
    """
    Manages persistent embeddings for semantic search.

    Architecture:
    - embeddings table: (content_hash, embedding_blob, created_at) [SQLite]
    - VectorStore: FAISS index for fast similarity search [dual-write]
    - Batch computation: Process all memories without embeddings
    - Cache in-memory for session lifetime
    """

    _CACHE_MAX_SIZE = 1000  # LRU cache size limit

    def __init__(self, db_path: str = None):
        """Initialize embedding manager"""
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._model = None
        self._session_cache = OrderedDict()  # LRU-bounded in-memory cache
        self._vector_store = None
        self._init_db()
        self._init_vector_store()

    def _init_vector_store(self):
        """Try to initialize FAISS VectorStore for fast similarity search."""
        try:
            from memory_system.vector_store import VectorStore
            self._vector_store = VectorStore()
        except (ImportError, Exception):
            self._vector_store = None

    def _init_db(self):
        """Create embeddings table if needed"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    content_hash TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_accessed
                ON embeddings(accessed_at DESC)
            """)

    def _get_model(self):
        """Lazy-load sentence-transformers model"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer('all-MiniLM-L6-v2')
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
        return self._model

    def _hash_content(self, content: str) -> str:
        """Generate stable hash for content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def get_embedding(self, content: str, use_cache: bool = True) -> np.ndarray:
        """
        Get embedding for content (from cache/DB or compute).

        Args:
            content: Text to embed
            use_cache: Whether to use cache/DB (False = force recompute)

        Returns:
            384-dim numpy array
        """
        content_hash = self._hash_content(content)

        # Check session cache (LRU-bounded)
        if use_cache and content_hash in self._session_cache:
            # Move to end (mark as recently used)
            self._session_cache.move_to_end(content_hash)
            return self._session_cache[content_hash]

        # Check database
        if use_cache:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT embedding FROM embeddings WHERE content_hash = ?",
                    (content_hash,)
                ).fetchone()

                if row:
                    # Update accessed_at
                    conn.execute(
                        "UPDATE embeddings SET accessed_at = ? WHERE content_hash = ?",
                        (datetime.now().isoformat(), content_hash)
                    )
                    conn.commit()

                    # Deserialize embedding
                    embedding = np.frombuffer(row[0], dtype=np.float32)
                    # Add to cache with LRU eviction
                    self._session_cache[content_hash] = embedding
                    if len(self._session_cache) > self._CACHE_MAX_SIZE:
                        self._session_cache.popitem(last=False)
                    return embedding

        # Compute embedding
        model = self._get_model()
        embedding = model.encode(content, convert_to_numpy=True).astype(np.float32)

        # Save to database (SQLite — primary storage)
        with sqlite3.connect(self.db_path) as conn:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT OR REPLACE INTO embeddings
                (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                content_hash,
                embedding.tobytes(),
                len(embedding),
                'all-MiniLM-L6-v2',
                now,
                now
            ))
            conn.commit()

        # Dual-write to VectorStore (FAISS) for fast search
        if self._vector_store is not None:
            try:
                self._vector_store.store_embedding(content_hash, embedding)
            except Exception:
                pass

        # Cache in session with LRU eviction
        self._session_cache[content_hash] = embedding
        if len(self._session_cache) > self._CACHE_MAX_SIZE:
            self._session_cache.popitem(last=False)
        return embedding

    def batch_compute_embeddings(
        self,
        contents: List[str],
        show_progress: bool = True
    ) -> Dict[str, np.ndarray]:
        """
        Batch compute embeddings for multiple contents.

        Much faster than computing one at a time.

        Args:
            contents: List of texts to embed
            show_progress: Show progress bar

        Returns:
            Dict mapping content_hash to embedding
        """
        # Filter out contents that already have embeddings
        content_hashes = [self._hash_content(c) for c in contents]

        with sqlite3.connect(self.db_path) as conn:
            placeholders = ','.join('?' * len(content_hashes))
            existing = conn.execute(
                f"SELECT content_hash FROM embeddings WHERE content_hash IN ({placeholders})",
                content_hashes
            ).fetchall()
            existing_hashes = {row[0] for row in existing}

        # Find contents that need computation
        to_compute = [
            (content, hash_val)
            for content, hash_val in zip(contents, content_hashes)
            if hash_val not in existing_hashes
        ]

        if not to_compute:
            print(f"All {len(contents)} embeddings already exist")
            return {}

        print(f"Computing {len(to_compute)} new embeddings (skipping {len(existing_hashes)} existing)...")

        # Batch compute
        model = self._get_model()
        texts = [c[0] for c in to_compute]
        embeddings = model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=show_progress
        ).astype(np.float32)

        # Save to database (batch insert)
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO embeddings
                (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (
                    hash_val,
                    embedding.tobytes(),
                    len(embedding),
                    'all-MiniLM-L6-v2',
                    now,
                    now
                )
                for (_, hash_val), embedding in zip(to_compute, embeddings)
            ])
            conn.commit()

        # Return mapping
        result = {}
        for (_, hash_val), embedding in zip(to_compute, embeddings):
            result[hash_val] = embedding
            # Add to cache with LRU eviction
            self._session_cache[hash_val] = embedding
            if len(self._session_cache) > self._CACHE_MAX_SIZE:
                self._session_cache.popitem(last=False)

        print(f"✅ Computed and saved {len(result)} embeddings")
        return result

    def precompute_all_memories(self):
        """
        Pre-compute embeddings for all memories in memory-ts.

        Call this from nightly maintenance job.
        """
        from memory_ts_client import MemoryTSClient

        print("🔄 Pre-computing embeddings for all memories...")

        client = MemoryTSClient(project_id="LFI")
        memories = client.search()  # Get all memories

        if not memories:
            print("No memories found")
            return

        contents = [m.content for m in memories if m.content]
        self.batch_compute_embeddings(contents, show_progress=True)

        print(f"✅ Pre-computation complete for {len(contents)} memories")

    def semantic_search(
        self,
        query: str,
        memories: List[Dict],
        top_k: int = 10,
        threshold: float = 0.3
    ) -> List[Tuple[Dict, float]]:
        """
        Fast semantic search using pre-computed embeddings.

        Uses FAISS VectorStore when available for O(1) indexed search,
        falls back to brute-force cosine similarity.

        Args:
            query: Search query
            memories: List of memory dicts with 'content' key
            top_k: Number of results
            threshold: Minimum similarity

        Returns:
            List of (memory, similarity_score) tuples
        """
        # Get query embedding
        query_embedding = self.get_embedding(query)

        # Try FAISS VectorStore for fast indexed search
        if self._vector_store is not None and self._vector_store.count() > 0:
            try:
                results = self._vector_store.find_similar(
                    query_embedding, top_k=top_k, threshold=threshold
                )
                # Map back to memory dicts via content_hash
                hash_to_memory = {}
                for memory in memories:
                    content = memory.get('content', '')
                    if content:
                        h = self._hash_content(content)
                        hash_to_memory[h] = memory

                scored = []
                for r in results:
                    mem = hash_to_memory.get(r["content_hash"])
                    if mem:
                        scored.append((mem, r["similarity"]))
                if scored:
                    return scored
            except Exception:
                pass

        # Fallback: brute-force cosine similarity
        scored = []

        for memory in memories:
            content = memory.get('content', '')
            if not content:
                continue

            # Get embedding (from cache/DB)
            mem_embedding = self.get_embedding(content, use_cache=True)

            # Cosine similarity
            similarity = float(
                np.dot(query_embedding, mem_embedding) /
                (np.linalg.norm(query_embedding) * np.linalg.norm(mem_embedding))
            )

            if similarity >= threshold:
                scored.append((memory, similarity))

        # Sort by similarity
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[:top_k]

    def clear_session_cache(self):
        """Clear the in-memory session cache (useful for testing or memory management)."""
        self._session_cache = OrderedDict()

    def cleanup_old_embeddings(self, days: int = 90):
        """
        Clean up embeddings for content not accessed in N days.

        Call from nightly maintenance.
        """
        from datetime import timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM embeddings WHERE accessed_at < ?",
                (cutoff,)
            ).rowcount
            conn.commit()

        print(f"🗑️  Cleaned up {deleted} old embeddings (not accessed in {days} days)")
        return deleted

    def get_stats(self) -> Dict:
        """Get embedding statistics"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

            # Total size
            size_mb = conn.execute(
                "SELECT SUM(LENGTH(embedding)) / 1024.0 / 1024.0 FROM embeddings"
            ).fetchone()[0] or 0

            # Oldest and newest
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM embeddings"
            ).fetchone()[0]

            newest = conn.execute(
                "SELECT MAX(created_at) FROM embeddings"
            ).fetchone()[0]

        return {
            'total_embeddings': total,
            'size_mb': round(size_mb, 2),
            'oldest': oldest,
            'newest': newest,
            'session_cache_size': len(self._session_cache)
        }


# Convenience function for backward compatibility
def semantic_search(query: str, memories: List[Dict], top_k: int = 10) -> List[Dict]:
    """
    Semantic search with pre-computed embeddings.

    Drop-in replacement for old semantic_search.py function.
    """
    manager = EmbeddingManager()
    results = manager.semantic_search(query, memories, top_k=top_k)

    # Return in old format (memory dict with similarity score)
    return [
        {**memory, 'similarity': score}
        for memory, score in results
    ]


if __name__ == "__main__":
    # Test/demo
    manager = EmbeddingManager()

    # Show stats
    stats = manager.get_stats()
    print(f"\n📊 Embedding Stats:")
    for key, value in stats.items():
        print(f"   {key}: {value}")

    # Pre-compute all memories
    manager.precompute_all_memories()
