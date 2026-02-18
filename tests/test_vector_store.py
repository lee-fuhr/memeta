"""
Tests for VectorStore — FAISS-backed vector storage and similarity search.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from memory_system.vector_store import (
    VectorStore,
    VectorStoreError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Create a VectorStore with temp persist directory."""
    return VectorStore(persist_dir=str(tmp_path / "chroma_db"))


@pytest.fixture
def populated_store(store):
    """Store with some embeddings pre-loaded."""
    dim = 384
    np.random.seed(42)
    for i in range(5):
        vec = np.random.randn(dim).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        store.store_embedding(f"hash_{i}", vec, {"content": f"Memory {i}"})
    return store


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_store(self, store):
        assert store is not None

    def test_creates_persist_dir(self, tmp_path):
        persist = str(tmp_path / "new_chroma")
        s = VectorStore(persist_dir=persist)
        assert s is not None

    def test_collection_name_default(self, store):
        assert store.collection_name == "memory_embeddings"

    def test_custom_collection(self, tmp_path):
        s = VectorStore(persist_dir=str(tmp_path / "c"), collection_name="custom")
        assert s.collection_name == "custom"


# ---------------------------------------------------------------------------
# store_embedding / get_embedding
# ---------------------------------------------------------------------------

class TestStoreAndRetrieve:
    def test_store_and_get(self, store):
        vec = np.random.randn(384).astype(np.float32)
        store.store_embedding("abc123", vec, {"content": "test"})
        result = store.get_embedding("abc123")
        assert result is not None
        # Vectors are L2-normalized on store, so compare normalized versions
        expected = vec / np.linalg.norm(vec)
        np.testing.assert_allclose(result, expected, rtol=1e-5)

    def test_get_nonexistent_returns_none(self, store):
        result = store.get_embedding("does_not_exist")
        assert result is None

    def test_store_updates_existing(self, store):
        vec1 = np.random.randn(384).astype(np.float32)
        vec2 = np.random.randn(384).astype(np.float32) * 2.0
        store.store_embedding("same_hash", vec1)
        store.store_embedding("same_hash", vec2)
        result = store.get_embedding("same_hash")
        expected = vec2 / np.linalg.norm(vec2)
        np.testing.assert_allclose(result, expected, rtol=1e-5)

    def test_store_with_metadata(self, store):
        vec = np.random.randn(384).astype(np.float32)
        meta = {"content": "test content", "domain": "testing"}
        store.store_embedding("meta_hash", vec, meta)
        result = store.get_embedding("meta_hash")
        assert result is not None

    def test_store_without_metadata(self, store):
        vec = np.random.randn(384).astype(np.float32)
        store.store_embedding("no_meta", vec)
        result = store.get_embedding("no_meta")
        assert result is not None


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------

class TestFindSimilar:
    def test_find_returns_ranked_results(self, populated_store):
        query = np.random.randn(384).astype(np.float32)
        results = populated_store.find_similar(query, top_k=3)
        assert len(results) <= 3
        # Results should be sorted by similarity (descending)
        scores = [r["similarity"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_find_returns_correct_fields(self, populated_store):
        query = np.random.randn(384).astype(np.float32)
        results = populated_store.find_similar(query, top_k=1)
        assert len(results) >= 1
        r = results[0]
        assert "content_hash" in r
        assert "similarity" in r

    def test_threshold_filters_low_scores(self, store):
        dim = 384
        # Store one vector pointing "north"
        north = np.zeros(dim, dtype=np.float32)
        north[0] = 1.0
        store.store_embedding("north", north)

        # Query with "south" (opposite direction)
        south = np.zeros(dim, dtype=np.float32)
        south[0] = -1.0
        results = store.find_similar(south, top_k=10, threshold=0.5)
        assert len(results) == 0

    def test_find_empty_store(self, store):
        query = np.random.randn(384).astype(np.float32)
        results = store.find_similar(query, top_k=5)
        assert results == []

    def test_top_k_limits_results(self, populated_store):
        query = np.random.randn(384).astype(np.float32)
        results = populated_store.find_similar(query, top_k=2)
        assert len(results) <= 2

    def test_similar_vectors_rank_higher(self, store):
        dim = 384
        np.random.seed(99)
        target = np.random.randn(dim).astype(np.float32)
        target = target / np.linalg.norm(target)

        # Very similar vector (cosine ~0.99)
        similar = target + np.random.randn(dim).astype(np.float32) * 0.05
        similar = similar / np.linalg.norm(similar)

        # Dissimilar but positive (orthogonal-ish, cosine ~0.05)
        dissimilar = np.random.randn(dim).astype(np.float32)
        dissimilar = dissimilar / np.linalg.norm(dissimilar)
        # Ensure it has positive similarity by adding a small target component
        dissimilar = dissimilar * 0.95 + target * 0.05
        dissimilar = dissimilar / np.linalg.norm(dissimilar)

        store.store_embedding("similar", similar)
        store.store_embedding("dissimilar", dissimilar)

        results = store.find_similar(target, top_k=2, threshold=-1.0)
        assert len(results) == 2
        assert results[0]["content_hash"] == "similar"


# ---------------------------------------------------------------------------
# delete_embedding
# ---------------------------------------------------------------------------

class TestDeleteEmbedding:
    def test_delete_existing(self, store):
        vec = np.random.randn(384).astype(np.float32)
        store.store_embedding("to_delete", vec)
        assert store.get_embedding("to_delete") is not None
        store.delete_embedding("to_delete")
        assert store.get_embedding("to_delete") is None

    def test_delete_nonexistent_no_error(self, store):
        # Should not raise
        store.delete_embedding("nonexistent")


# ---------------------------------------------------------------------------
# count / has_embedding
# ---------------------------------------------------------------------------

class TestCountAndHas:
    def test_count_empty(self, store):
        assert store.count() == 0

    def test_count_after_adds(self, populated_store):
        assert populated_store.count() == 5

    def test_has_embedding_true(self, populated_store):
        assert populated_store.has_embedding("hash_0")

    def test_has_embedding_false(self, populated_store):
        assert not populated_store.has_embedding("nonexistent")


# ---------------------------------------------------------------------------
# batch_store
# ---------------------------------------------------------------------------

class TestBatchStore:
    def test_batch_store_multiple(self, store):
        dim = 384
        items = []
        for i in range(10):
            vec = np.random.randn(dim).astype(np.float32)
            items.append((f"batch_{i}", vec, {"content": f"Batch {i}"}))
        store.batch_store(items)
        assert store.count() == 10

    def test_batch_store_empty(self, store):
        store.batch_store([])
        assert store.count() == 0


# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------

class TestMigrationHelper:
    def test_import_from_sqlite(self, store, tmp_path):
        """Test importing embeddings from existing SQLite storage."""
        # Create a mock SQLite embeddings DB
        sqlite_db = tmp_path / "intelligence.db"
        conn = sqlite3.connect(str(sqlite_db))
        conn.execute("""
            CREATE TABLE embeddings (
                content_hash TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                dimension INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                accessed_at TEXT NOT NULL
            )
        """)
        # Insert some test embeddings
        for i in range(3):
            vec = np.random.randn(384).astype(np.float32)
            conn.execute(
                "INSERT INTO embeddings VALUES (?,?,?,?,?,?)",
                (f"sqlite_hash_{i}", vec.tobytes(), 384, "all-MiniLM-L6-v2",
                 "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
        conn.commit()
        conn.close()

        # Import
        imported = store.import_from_sqlite(str(sqlite_db))
        assert imported == 3
        assert store.count() == 3
        assert store.has_embedding("sqlite_hash_0")
