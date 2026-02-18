"""
VectorStore — FAISS-backed persistent vector storage and similarity search.

Replaces brute-force cosine similarity in semantic_search.py with indexed
vector search via FAISS (Facebook AI Similarity Search).

Chosen over ChromaDB because:
  - No pydantic dependency conflicts (ChromaDB broken on Python 3.14)
  - Pure NumPy integration (no serialization overhead)
  - Faster for local use cases
  - Simpler persistence (just save/load the index)

Usage:
    from memory_system.vector_store import VectorStore

    store = VectorStore()
    store.store_embedding("hash123", embedding_array, {"content": "text"})
    results = store.find_similar(query_vector, top_k=10, threshold=0.5)

Migration from SQLite:
    store.import_from_sqlite("path/to/intelligence.db")
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None

DEFAULT_PERSIST_DIR = str(Path.home() / ".local/share/memory/vector_store")
DEFAULT_COLLECTION = "memory_embeddings"
DIMENSION = 384  # all-MiniLM-L6-v2 output dimension


class VectorStoreError(Exception):
    """Error in VectorStore operations."""
    pass


class VectorStore:
    """FAISS-backed persistent vector storage.

    Features:
        - Persistent storage via save/load
        - Indexed similarity search (inner product on normalized vectors)
        - Metadata storage alongside vectors (JSON sidecar)
        - Batch operations for bulk import
        - Migration from SQLite embeddings table
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: str = DEFAULT_COLLECTION,
        dimension: int = DIMENSION,
    ):
        if faiss is None:
            raise ImportError(
                "faiss-cpu not installed. Install with: pip install faiss-cpu"
            )

        self.persist_dir = persist_dir or DEFAULT_PERSIST_DIR
        self.collection_name = collection_name
        self.dimension = dimension

        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

        self._index_path = Path(self.persist_dir) / f"{collection_name}.index"
        self._meta_path = Path(self.persist_dir) / f"{collection_name}.meta.json"

        # Maps: position in FAISS index ↔ content_hash
        self._hash_to_pos: dict[str, int] = {}
        self._pos_to_hash: dict[int, str] = {}
        self._metadata: dict[str, dict] = {}

        # FAISS index — inner product on L2-normalized vectors = cosine similarity
        self._index = faiss.IndexFlatIP(dimension)

        # Load existing data if available
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_embedding(
        self,
        content_hash: str,
        embedding: np.ndarray,
        metadata: Optional[dict] = None,
    ) -> None:
        """Store an embedding vector with optional metadata."""
        vec = self._normalize(embedding)

        if content_hash in self._hash_to_pos:
            # Update: remove old, add new
            self._remove_from_index(content_hash)

        pos = self._index.ntotal
        self._index.add(vec.reshape(1, -1))
        self._hash_to_pos[content_hash] = pos
        self._pos_to_hash[pos] = content_hash
        if metadata:
            self._metadata[content_hash] = metadata

        self._save()

    def get_embedding(self, content_hash: str) -> Optional[np.ndarray]:
        """Retrieve an embedding by content hash."""
        if content_hash not in self._hash_to_pos:
            return None

        pos = self._hash_to_pos[content_hash]
        vec = self._index.reconstruct(pos)
        return np.array(vec, dtype=np.float32)

    def find_similar(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[dict]:
        """Find similar embeddings by vector similarity."""
        if self._index.ntotal == 0:
            return []

        query = self._normalize(query_embedding).reshape(1, -1)
        n_results = min(top_k, self._index.ntotal)

        scores, indices = self._index.search(query, n_results)

        items = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            similarity = float(score)  # inner product of normalized vecs = cosine sim
            if similarity >= threshold:
                hash_id = self._pos_to_hash.get(int(idx))
                if hash_id:
                    items.append({
                        "content_hash": hash_id,
                        "similarity": similarity,
                        "metadata": self._metadata.get(hash_id, {}),
                    })

        items.sort(key=lambda x: x["similarity"], reverse=True)
        return items

    def delete_embedding(self, content_hash: str) -> None:
        """Delete an embedding by content hash."""
        if content_hash not in self._hash_to_pos:
            return
        self._remove_from_index(content_hash)
        self._metadata.pop(content_hash, None)
        self._save()

    def has_embedding(self, content_hash: str) -> bool:
        """Check if an embedding exists."""
        return content_hash in self._hash_to_pos

    def count(self) -> int:
        """Return total number of stored embeddings."""
        return len(self._hash_to_pos)

    def batch_store(
        self,
        items: list[tuple[str, np.ndarray, Optional[dict]]],
        batch_size: int = 1000,
    ) -> None:
        """Store multiple embeddings efficiently."""
        if not items:
            return

        for content_hash, embedding, metadata in items:
            vec = self._normalize(embedding)
            if content_hash in self._hash_to_pos:
                self._remove_from_index(content_hash)

            pos = self._index.ntotal
            self._index.add(vec.reshape(1, -1))
            self._hash_to_pos[content_hash] = pos
            self._pos_to_hash[pos] = content_hash
            if metadata:
                self._metadata[content_hash] = metadata

        self._save()

    def import_from_sqlite(self, sqlite_db_path: str) -> int:
        """Import embeddings from existing SQLite embeddings table."""
        conn = sqlite3.connect(sqlite_db_path)
        try:
            rows = conn.execute(
                "SELECT content_hash, embedding, dimension FROM embeddings"
            ).fetchall()

            if not rows:
                return 0

            items = []
            for content_hash, blob, dimension in rows:
                vec = np.frombuffer(blob, dtype=np.float32)
                if len(vec) == dimension:
                    items.append((content_hash, vec, None))

            self.batch_store(items)
            return len(items)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _normalize(self, vec: np.ndarray) -> np.ndarray:
        """L2-normalize a vector for cosine similarity via inner product."""
        v = vec.astype(np.float32)
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        return v

    def _remove_from_index(self, content_hash: str) -> None:
        """Remove a hash from the index by rebuilding without it."""
        if content_hash not in self._hash_to_pos:
            return

        # Collect all vectors except the one to remove
        remaining = []
        for h, pos in sorted(self._hash_to_pos.items(), key=lambda x: x[1]):
            if h != content_hash:
                vec = self._index.reconstruct(pos)
                remaining.append((h, np.array(vec, dtype=np.float32)))

        # Rebuild index
        self._index = faiss.IndexFlatIP(self.dimension)
        self._hash_to_pos.clear()
        self._pos_to_hash.clear()

        for h, vec in remaining:
            pos = self._index.ntotal
            self._index.add(vec.reshape(1, -1))
            self._hash_to_pos[h] = pos
            self._pos_to_hash[pos] = h

        self._metadata.pop(content_hash, None)

    def _save(self) -> None:
        """Persist index and metadata to disk."""
        faiss.write_index(self._index, str(self._index_path))
        meta = {
            "hash_to_pos": self._hash_to_pos,
            "metadata": self._metadata,
        }
        self._meta_path.write_text(json.dumps(meta))

    def _load(self) -> None:
        """Load index and metadata from disk."""
        if self._index_path.exists() and self._meta_path.exists():
            try:
                self._index = faiss.read_index(str(self._index_path))
                data = json.loads(self._meta_path.read_text())
                self._hash_to_pos = {k: int(v) for k, v in data.get("hash_to_pos", {}).items()}
                self._pos_to_hash = {int(v): k for k, v in self._hash_to_pos.items()}
                self._metadata = data.get("metadata", {})
            except Exception:
                # Corrupted — start fresh
                self._index = faiss.IndexFlatIP(self.dimension)
                self._hash_to_pos.clear()
                self._pos_to_hash.clear()
                self._metadata.clear()
