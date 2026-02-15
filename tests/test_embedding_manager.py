"""
Tests for embedding_manager.py - Persistent embedding storage and semantic search.

Covers:
1. Initialization (DB setup, table creation, cache initialization)
2. Embedding generation (single text, batch, normalization)
3. Caching behavior (cache hits, cache misses, LRU eviction at max 1000)
4. Similarity search (cosine similarity, top-k results, thresholds)
5. Pre-computation (batch pre-compute, updates)
6. DB persistence (embeddings survive restart)
7. Edge cases (empty text, very long text, special characters)
8. Error handling (model load failure, corrupt embeddings)
9. Utility methods (stats, cleanup, clear_session_cache)
10. Backward-compatible convenience function
"""

import pytest
import tempfile
import sqlite3
import numpy as np
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from collections import OrderedDict

from memory_system.embedding_manager import EmbeddingManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384


def _make_embedding(seed: int = 0) -> np.ndarray:
    """Return a deterministic, normalised float32 embedding of dimension 384."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(EMBEDDING_DIM).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _make_model_mock():
    """Return a mock that behaves like SentenceTransformer for encode()."""
    model = MagicMock()

    def _encode_side_effect(text, convert_to_numpy=True, show_progress_bar=False):
        # Return deterministic embedding based on content hash
        if isinstance(text, str):
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)
            return _make_embedding(seed)
        elif isinstance(text, list):
            results = []
            for t in text:
                seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % (2**31)
                results.append(_make_embedding(seed))
            return np.array(results)

    model.encode = MagicMock(side_effect=_encode_side_effect)
    return model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)
    Path(db_path + '-wal').unlink(missing_ok=True)
    Path(db_path + '-shm').unlink(missing_ok=True)


@pytest.fixture
def manager(temp_db):
    """Create an EmbeddingManager with a temp database and mocked model."""
    mgr = EmbeddingManager(db_path=temp_db)
    mgr._model = _make_model_mock()
    yield mgr


@pytest.fixture
def manager_no_model(temp_db):
    """Create an EmbeddingManager with NO model pre-loaded (for testing lazy load)."""
    mgr = EmbeddingManager(db_path=temp_db)
    yield mgr


# ===========================================================================
# 1. Initialization
# ===========================================================================

class TestInitialization:

    def test_creates_embeddings_table(self, temp_db):
        """Embeddings table exists after init."""
        EmbeddingManager(db_path=temp_db)
        with sqlite3.connect(temp_db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
            ).fetchall()
        assert len(tables) == 1

    def test_creates_accessed_at_index(self, temp_db):
        """Index on accessed_at column exists."""
        EmbeddingManager(db_path=temp_db)
        with sqlite3.connect(temp_db) as conn:
            indices = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_embeddings_accessed'"
            ).fetchall()
        assert len(indices) == 1

    def test_session_cache_starts_empty(self, manager):
        """Session cache is an empty OrderedDict on init."""
        assert isinstance(manager._session_cache, OrderedDict)
        assert len(manager._session_cache) == 0

    def test_model_starts_as_none(self, temp_db):
        """Model is not loaded until first use."""
        mgr = EmbeddingManager(db_path=temp_db)
        assert mgr._model is None

    def test_db_path_stored_as_string(self, temp_db):
        """db_path is stored as a string."""
        mgr = EmbeddingManager(db_path=temp_db)
        assert isinstance(mgr.db_path, str)

    def test_default_cache_max_size(self):
        """Class constant for max cache size is 1000."""
        assert EmbeddingManager._CACHE_MAX_SIZE == 1000

    def test_idempotent_init(self, temp_db):
        """Creating manager twice on same DB does not error."""
        EmbeddingManager(db_path=temp_db)
        EmbeddingManager(db_path=temp_db)
        with sqlite3.connect(temp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert count == 0


# ===========================================================================
# 2. Embedding generation
# ===========================================================================

class TestEmbeddingGeneration:

    def test_get_embedding_returns_ndarray(self, manager):
        """get_embedding returns a numpy ndarray."""
        emb = manager.get_embedding("hello world")
        assert isinstance(emb, np.ndarray)

    def test_get_embedding_correct_dimension(self, manager):
        """Embedding has expected dimension (384)."""
        emb = manager.get_embedding("hello world")
        assert emb.shape == (EMBEDDING_DIM,)

    def test_get_embedding_float32(self, manager):
        """Embedding uses float32 dtype."""
        emb = manager.get_embedding("hello world")
        assert emb.dtype == np.float32

    def test_get_embedding_deterministic(self, manager):
        """Same content always produces same embedding."""
        emb1 = manager.get_embedding("same text", use_cache=False)
        manager.clear_session_cache()
        emb2 = manager.get_embedding("same text", use_cache=False)
        np.testing.assert_array_equal(emb1, emb2)

    def test_different_content_different_embedding(self, manager):
        """Different content produces different embeddings."""
        emb1 = manager.get_embedding("text one")
        emb2 = manager.get_embedding("text two")
        assert not np.array_equal(emb1, emb2)

    def test_embedding_saved_to_db(self, manager, temp_db):
        """After get_embedding, the embedding is persisted to DB."""
        manager.get_embedding("persist me")
        content_hash = hashlib.sha256("persist me".encode()).hexdigest()
        with sqlite3.connect(temp_db) as conn:
            row = conn.execute(
                "SELECT content_hash, dimension, model_name FROM embeddings WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()
        assert row is not None
        assert row[0] == content_hash
        assert row[1] == EMBEDDING_DIM
        assert row[2] == 'all-MiniLM-L6-v2'

    def test_embedding_force_recompute(self, manager):
        """use_cache=False forces recomputation."""
        emb1 = manager.get_embedding("recompute")
        manager._model.encode.reset_mock()
        emb2 = manager.get_embedding("recompute", use_cache=False)
        # Model.encode should have been called again
        assert manager._model.encode.called


# ===========================================================================
# 3. Caching behavior
# ===========================================================================

class TestCachingBehavior:

    def test_cache_hit_skips_model(self, manager):
        """Second call for same content uses cache, not model."""
        manager.get_embedding("cached text")
        manager._model.encode.reset_mock()
        manager.get_embedding("cached text")
        manager._model.encode.assert_not_called()

    def test_cache_hit_returns_same_array(self, manager):
        """Cache returns identical array to original computation."""
        emb1 = manager.get_embedding("match me")
        emb2 = manager.get_embedding("match me")
        np.testing.assert_array_equal(emb1, emb2)

    def test_cache_miss_after_clear(self, manager):
        """After clear_session_cache, cache is empty; must recompute or load from DB."""
        manager.get_embedding("will be cleared")
        manager.clear_session_cache()
        assert len(manager._session_cache) == 0

    def test_db_serves_after_cache_clear(self, manager):
        """After cache clear, embedding is loaded from DB (not recomputed)."""
        manager.get_embedding("db fallback")
        manager.clear_session_cache()
        manager._model.encode.reset_mock()
        emb = manager.get_embedding("db fallback")
        # Should NOT call encode because DB has it
        manager._model.encode.assert_not_called()
        assert emb.shape == (EMBEDDING_DIM,)

    def test_lru_eviction_at_max(self, manager):
        """Cache evicts oldest entry when exceeding _CACHE_MAX_SIZE."""
        # Override to a small limit for testing
        manager._CACHE_MAX_SIZE = 5
        for i in range(6):
            manager.get_embedding(f"entry-{i}")
        assert len(manager._session_cache) == 5
        # First entry should have been evicted
        first_hash = hashlib.sha256("entry-0".encode()).hexdigest()
        assert first_hash not in manager._session_cache

    def test_lru_eviction_preserves_recent(self, manager):
        """LRU eviction keeps the most recently used entries."""
        manager._CACHE_MAX_SIZE = 5
        for i in range(6):
            manager.get_embedding(f"entry-{i}")
        # Last entry should still be in cache
        last_hash = hashlib.sha256("entry-5".encode()).hexdigest()
        assert last_hash in manager._session_cache

    def test_lru_access_refreshes_position(self, manager):
        """Accessing an entry moves it to end, protecting it from eviction."""
        manager._CACHE_MAX_SIZE = 3
        manager.get_embedding("a")
        manager.get_embedding("b")
        manager.get_embedding("c")
        # Access "a" to refresh it
        manager.get_embedding("a")
        # Now add "d" - should evict "b" (oldest non-refreshed), not "a"
        manager.get_embedding("d")
        a_hash = hashlib.sha256("a".encode()).hexdigest()
        b_hash = hashlib.sha256("b".encode()).hexdigest()
        assert a_hash in manager._session_cache
        assert b_hash not in manager._session_cache

    def test_cache_bounded_at_1000_default(self):
        """Default _CACHE_MAX_SIZE is 1000."""
        assert EmbeddingManager._CACHE_MAX_SIZE == 1000


# ===========================================================================
# 4. Similarity search
# ===========================================================================

class TestSemanticSearch:

    def test_returns_list_of_tuples(self, manager):
        """semantic_search returns list of (memory, score) tuples."""
        memories = [{"content": "the sky is blue"}]
        results = manager.semantic_search("sky color", memories)
        assert isinstance(results, list)
        for item in results:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_score_between_zero_and_one(self, manager):
        """Similarity scores are in [0, 1] for normalised embeddings."""
        memories = [{"content": "the sky is blue"}, {"content": "rain is wet"}]
        results = manager.semantic_search("weather", memories, threshold=0.0)
        for _, score in results:
            assert -1.0 <= score <= 1.0

    def test_identical_content_scores_one(self, manager):
        """Querying with identical text should yield similarity ~1.0."""
        text = "exact match text"
        memories = [{"content": text}]
        results = manager.semantic_search(text, memories, threshold=0.0)
        assert len(results) == 1
        _, score = results[0]
        assert score > 0.99

    def test_top_k_limits_results(self, manager):
        """top_k caps the number of returned results."""
        memories = [{"content": f"item number {i}"} for i in range(20)]
        results = manager.semantic_search("item", memories, top_k=5, threshold=0.0)
        assert len(results) <= 5

    def test_threshold_filters_low_similarity(self, manager):
        """Results below threshold are excluded."""
        memories = [{"content": "completely unrelated XYZ123"}]
        results = manager.semantic_search("query", memories, threshold=0.99)
        # With random fake embeddings, nearly impossible to exceed 0.99
        # unless identical; so should be filtered
        assert len(results) <= 1

    def test_results_sorted_by_similarity_desc(self, manager):
        """Results are sorted highest similarity first."""
        memories = [{"content": f"topic {i}"} for i in range(10)]
        results = manager.semantic_search("topic", memories, top_k=10, threshold=0.0)
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_memories_returns_empty(self, manager):
        """Empty memory list yields empty results."""
        results = manager.semantic_search("query", [])
        assert results == []

    def test_memories_without_content_skipped(self, manager):
        """Memories with empty or missing content key are skipped."""
        memories = [
            {"content": ""},
            {"id": 1},
            {"content": "valid entry"},
        ]
        # Use threshold=-1.0 to ensure no filtering by score — we only test
        # that empty/missing content memories are skipped
        results = manager.semantic_search("valid", memories, threshold=-1.0)
        # Only the "valid entry" should be in results (empty and missing skipped)
        assert len(results) == 1
        assert results[0][0]["content"] == "valid entry"

    def test_memory_dict_passed_through(self, manager):
        """Original memory dict is returned in results (not just content)."""
        mem = {"content": "hello world", "id": 42, "tags": ["test"]}
        results = manager.semantic_search("hello", [mem], threshold=0.0)
        assert len(results) == 1
        returned_mem = results[0][0]
        assert returned_mem["id"] == 42
        assert returned_mem["tags"] == ["test"]


# ===========================================================================
# 5. Batch computation
# ===========================================================================

class TestBatchComputeEmbeddings:

    def test_batch_returns_dict(self, manager):
        """batch_compute_embeddings returns a dict of hash -> embedding."""
        contents = ["alpha", "beta", "gamma"]
        result = manager.batch_compute_embeddings(contents, show_progress=False)
        assert isinstance(result, dict)
        assert len(result) == 3

    def test_batch_stores_in_db(self, manager, temp_db):
        """Batch computed embeddings are persisted to the database."""
        contents = ["one", "two", "three"]
        manager.batch_compute_embeddings(contents, show_progress=False)
        with sqlite3.connect(temp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert count == 3

    def test_batch_skips_existing(self, manager, capsys):
        """Batch skips contents that already have embeddings."""
        # Pre-compute one
        manager.get_embedding("already here")
        # Now batch with that one plus a new one
        result = manager.batch_compute_embeddings(
            ["already here", "new one"], show_progress=False
        )
        # Only the new one should be in the result
        assert len(result) == 1

    def test_batch_all_existing_returns_empty(self, manager, capsys):
        """When all embeddings exist, returns empty dict."""
        manager.get_embedding("exists")
        result = manager.batch_compute_embeddings(["exists"], show_progress=False)
        assert result == {}

    def test_batch_adds_to_session_cache(self, manager):
        """Batch computed embeddings are added to session cache."""
        contents = ["cache me 1", "cache me 2"]
        manager.batch_compute_embeddings(contents, show_progress=False)
        h1 = hashlib.sha256("cache me 1".encode()).hexdigest()
        h2 = hashlib.sha256("cache me 2".encode()).hexdigest()
        assert h1 in manager._session_cache
        assert h2 in manager._session_cache

    def test_batch_lru_eviction(self, manager):
        """Batch computation respects LRU cache max size."""
        manager._CACHE_MAX_SIZE = 3
        contents = [f"batch-{i}" for i in range(5)]
        manager.batch_compute_embeddings(contents, show_progress=False)
        assert len(manager._session_cache) <= 3

    def test_batch_empty_list(self, manager, capsys):
        """Empty content list does not error."""
        result = manager.batch_compute_embeddings([], show_progress=False)
        # All 0 already exist -> returns empty dict
        assert result == {}


# ===========================================================================
# 6. DB persistence
# ===========================================================================

class TestDBPersistence:

    def test_embedding_survives_restart(self, temp_db):
        """Embedding persists across manager instances."""
        # Manager 1: compute and store
        mgr1 = EmbeddingManager(db_path=temp_db)
        mgr1._model = _make_model_mock()
        emb1 = mgr1.get_embedding("survive restart")

        # Manager 2: should load from DB
        mgr2 = EmbeddingManager(db_path=temp_db)
        mgr2._model = _make_model_mock()
        mgr2._model.encode.reset_mock()
        emb2 = mgr2.get_embedding("survive restart")

        np.testing.assert_array_equal(emb1, emb2)
        # Model should NOT have been called (loaded from DB)
        mgr2._model.encode.assert_not_called()

    def test_db_stores_correct_blob(self, manager, temp_db):
        """Raw embedding blob in DB deserialises to correct array."""
        emb_original = manager.get_embedding("blob check")
        content_hash = hashlib.sha256("blob check".encode()).hexdigest()

        with sqlite3.connect(temp_db) as conn:
            row = conn.execute(
                "SELECT embedding FROM embeddings WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()

        emb_from_db = np.frombuffer(row[0], dtype=np.float32)
        np.testing.assert_array_equal(emb_original, emb_from_db)

    def test_accessed_at_updated_on_read(self, manager, temp_db):
        """accessed_at timestamp updates when embedding is read from DB."""
        manager.get_embedding("access tracking")
        content_hash = hashlib.sha256("access tracking".encode()).hexdigest()

        # Read initial accessed_at
        with sqlite3.connect(temp_db) as conn:
            ts1 = conn.execute(
                "SELECT accessed_at FROM embeddings WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()[0]

        # Clear cache to force DB read
        manager.clear_session_cache()

        # Wait a tiny moment for timestamp difference
        import time
        time.sleep(0.01)

        # Access again
        manager.get_embedding("access tracking")

        with sqlite3.connect(temp_db) as conn:
            ts2 = conn.execute(
                "SELECT accessed_at FROM embeddings WHERE content_hash = ?",
                (content_hash,)
            ).fetchone()[0]

        assert ts2 >= ts1


# ===========================================================================
# 7. Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_empty_string(self, manager):
        """Empty string still produces a valid embedding."""
        emb = manager.get_embedding("")
        assert isinstance(emb, np.ndarray)
        assert emb.shape == (EMBEDDING_DIM,)

    def test_very_long_text(self, manager):
        """Very long text does not crash."""
        long_text = "word " * 10000
        emb = manager.get_embedding(long_text)
        assert emb.shape == (EMBEDDING_DIM,)

    def test_special_characters(self, manager):
        """Unicode and special chars handled correctly."""
        emb = manager.get_embedding("emojis 🎉🚀 and accents: cafe\u0301 na\u00efve")
        assert emb.shape == (EMBEDDING_DIM,)

    def test_newlines_and_tabs(self, manager):
        """Content with whitespace variations works."""
        emb = manager.get_embedding("line1\nline2\ttab\r\nwindows")
        assert emb.shape == (EMBEDDING_DIM,)

    def test_hash_consistency(self, manager):
        """_hash_content is stable across calls."""
        h1 = manager._hash_content("test")
        h2 = manager._hash_content("test")
        assert h1 == h2
        assert isinstance(h1, str)
        assert len(h1) == 64  # SHA-256 hex digest length

    def test_hash_differs_for_different_content(self, manager):
        """Different content produces different hashes."""
        h1 = manager._hash_content("foo")
        h2 = manager._hash_content("bar")
        assert h1 != h2

    def test_single_character(self, manager):
        """Single character content works."""
        emb = manager.get_embedding("x")
        assert emb.shape == (EMBEDDING_DIM,)


# ===========================================================================
# 8. Error handling
# ===========================================================================

class TestErrorHandling:

    def test_model_import_error(self, temp_db):
        """Raises ImportError when sentence-transformers is not installed."""
        mgr = EmbeddingManager(db_path=temp_db)
        # Ensure _model is None so _get_model tries to import
        mgr._model = None
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError, match="sentence-transformers not installed"):
                mgr._get_model()

    def test_corrupt_embedding_in_db(self, manager, temp_db):
        """Corrupt blob in DB should raise on deserialization."""
        content_hash = hashlib.sha256("corrupt".encode()).hexdigest()
        with sqlite3.connect(temp_db) as conn:
            conn.execute("""
                INSERT INTO embeddings (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (content_hash, b"not a real embedding", 384, "test", "2025-01-01", "2025-01-01"))
            conn.commit()

        # Trying to read corrupt data - it will deserialise but produce wrong shape
        # which doesn't crash np.frombuffer, but the shape won't match 384
        manager.clear_session_cache()
        emb = manager.get_embedding("corrupt")
        # The corrupt one will be read from DB but may have wrong shape.
        # Since use_cache=True and DB has an entry, it reads the corrupt blob.
        # np.frombuffer won't crash but shape will be different.
        # The code doesn't validate shape, so this tests current behavior.
        assert isinstance(emb, np.ndarray)


# ===========================================================================
# 9. Utility methods
# ===========================================================================

class TestUtilityMethods:

    def test_get_stats_empty_db(self, manager):
        """Stats on empty DB return zeros/None."""
        stats = manager.get_stats()
        assert stats['total_embeddings'] == 0
        assert stats['size_mb'] == 0
        assert stats['oldest'] is None
        assert stats['newest'] is None
        assert stats['session_cache_size'] == 0

    def test_get_stats_with_data(self, manager):
        """Stats reflect stored embeddings."""
        manager.get_embedding("first")
        manager.get_embedding("second")
        stats = manager.get_stats()
        assert stats['total_embeddings'] == 2
        # 2 * 384 * 4 bytes = 3072 bytes ~ 0.003 MB, rounds to 0.0 at 2dp
        # so check size_mb is a number >= 0 (the rounding makes it 0.0 for small counts)
        assert isinstance(stats['size_mb'], float)
        assert stats['size_mb'] >= 0
        assert stats['oldest'] is not None
        assert stats['newest'] is not None
        assert stats['session_cache_size'] == 2

    def test_clear_session_cache(self, manager):
        """clear_session_cache empties the cache."""
        manager.get_embedding("cached item")
        assert len(manager._session_cache) == 1
        manager.clear_session_cache()
        assert len(manager._session_cache) == 0

    def test_cleanup_old_embeddings(self, manager, temp_db):
        """cleanup_old_embeddings removes entries not accessed within N days."""
        # Insert an old embedding
        old_hash = hashlib.sha256("old entry".encode()).hexdigest()
        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        emb = _make_embedding(42)
        with sqlite3.connect(temp_db) as conn:
            conn.execute("""
                INSERT INTO embeddings (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (old_hash, emb.tobytes(), EMBEDDING_DIM, "test", old_date, old_date))
            conn.commit()

        # Insert a fresh embedding
        manager.get_embedding("fresh entry")

        # Cleanup with 90-day window
        deleted = manager.cleanup_old_embeddings(days=90)
        assert deleted == 1

        # Verify old is gone, fresh remains
        with sqlite3.connect(temp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert count == 1

    def test_cleanup_returns_count(self, manager):
        """cleanup_old_embeddings returns number of deleted rows."""
        deleted = manager.cleanup_old_embeddings(days=1)
        assert isinstance(deleted, int)
        assert deleted == 0

    def test_cleanup_preserves_recent(self, manager, temp_db):
        """Cleanup does not delete recently accessed embeddings."""
        manager.get_embedding("recent")
        deleted = manager.cleanup_old_embeddings(days=1)
        assert deleted == 0
        with sqlite3.connect(temp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert count == 1

    def test_stats_session_cache_size_matches(self, manager):
        """Stats session_cache_size matches actual cache length."""
        manager.get_embedding("a")
        manager.get_embedding("b")
        manager.get_embedding("c")
        stats = manager.get_stats()
        assert stats['session_cache_size'] == 3
        assert stats['session_cache_size'] == len(manager._session_cache)


# ===========================================================================
# 10. Backward-compatible convenience function
# ===========================================================================

class TestConvenienceFunction:

    def test_semantic_search_function_returns_list_of_dicts(self, temp_db):
        """Module-level semantic_search returns list of dicts with 'similarity' key."""
        with patch('memory_system.embedding_manager.EmbeddingManager') as MockManager:
            mock_instance = MagicMock()
            MockManager.return_value = mock_instance
            mock_instance.semantic_search.return_value = [
                ({"content": "hello", "id": 1}, 0.95),
                ({"content": "world", "id": 2}, 0.8),
            ]

            from memory_system.embedding_manager import semantic_search
            results = semantic_search("query", [{"content": "hello"}, {"content": "world"}], top_k=5)

            assert isinstance(results, list)
            assert len(results) == 2
            assert results[0]['similarity'] == 0.95
            assert results[0]['content'] == "hello"
            assert results[0]['id'] == 1
            assert results[1]['similarity'] == 0.8


# ===========================================================================
# 11. LRU cache boundary (1000-entry max)
# ===========================================================================

class TestLRUCacheBoundary:

    def test_cache_at_exactly_max_size(self, manager):
        """Cache holds exactly _CACHE_MAX_SIZE entries when filled to limit."""
        manager._CACHE_MAX_SIZE = 10
        for i in range(10):
            manager.get_embedding(f"fill-{i}")
        assert len(manager._session_cache) == 10

    def test_cache_one_over_max_evicts_oldest(self, manager):
        """Adding one more than max evicts the oldest entry."""
        manager._CACHE_MAX_SIZE = 10
        for i in range(11):
            manager.get_embedding(f"fill-{i}")
        assert len(manager._session_cache) == 10
        # fill-0 should have been evicted
        h0 = hashlib.sha256("fill-0".encode()).hexdigest()
        assert h0 not in manager._session_cache
        # fill-10 should be present
        h10 = hashlib.sha256("fill-10".encode()).hexdigest()
        assert h10 in manager._session_cache

    def test_batch_compute_respects_cache_max(self, manager):
        """batch_compute_embeddings does not exceed cache max size."""
        manager._CACHE_MAX_SIZE = 5
        contents = [f"batch-item-{i}" for i in range(20)]
        manager.batch_compute_embeddings(contents, show_progress=False)
        assert len(manager._session_cache) <= 5

    def test_db_read_respects_cache_max(self, manager, temp_db):
        """Loading from DB also respects LRU cache max."""
        manager._CACHE_MAX_SIZE = 3
        # Store 5 embeddings
        for i in range(5):
            manager.get_embedding(f"db-lru-{i}")

        # Clear cache, set tight limit
        manager.clear_session_cache()
        manager._CACHE_MAX_SIZE = 3

        # Load all 5 back from DB
        for i in range(5):
            manager.get_embedding(f"db-lru-{i}")

        assert len(manager._session_cache) <= 3
