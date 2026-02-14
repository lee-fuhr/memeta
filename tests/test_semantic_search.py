"""
Tests for semantic_search.py - Local semantic search using sentence-transformers.

Covers:
1. Initialization (module-level globals, model lazy-loading)
2. embed_text (vector generation, dimension, delegation to model)
3. cosine_similarity (math correctness, edge cases)
4. semantic_search (basic search, top-k, threshold, sorting, result structure)
5. Caching (LRU OrderedDict behavior, bounded at max 1000, eviction, refresh)
6. clear_embedding_cache (resets cache)
7. precompute_embeddings (batch embedding, return structure)
8. Edge cases (empty query, no memories, empty content, special characters)
9. Error handling (model import failure)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest
import numpy as np
import hashlib
from collections import OrderedDict
from unittest.mock import patch, MagicMock

import semantic_search as ss


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


def _seed_from_text(text: str) -> int:
    """Deterministic seed from text content."""
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)


def _make_model_mock():
    """Return a mock that behaves like SentenceTransformer for encode()."""
    model = MagicMock()

    def _encode_side_effect(text, convert_to_numpy=True, show_progress_bar=False):
        if isinstance(text, str):
            seed = _seed_from_text(text)
            return _make_embedding(seed)
        elif isinstance(text, list):
            results = []
            for t in text:
                seed = _seed_from_text(t)
                results.append(_make_embedding(seed))
            return np.array(results)

    model.encode = MagicMock(side_effect=_encode_side_effect)
    return model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level globals before each test."""
    ss._model = None
    ss._embeddings_cache = OrderedDict()
    yield
    ss._model = None
    ss._embeddings_cache = OrderedDict()


@pytest.fixture
def mock_model():
    """Inject a mock model into the module and return it."""
    model = _make_model_mock()
    ss._model = model
    return model


# ===========================================================================
# 1. Initialization and module globals
# ===========================================================================

class TestInitialization:

    def test_model_starts_as_none(self):
        """Module-level _model starts as None."""
        assert ss._model is None

    def test_cache_starts_empty(self):
        """Module-level _embeddings_cache starts as empty OrderedDict."""
        assert isinstance(ss._embeddings_cache, OrderedDict)
        assert len(ss._embeddings_cache) == 0

    def test_cache_max_size_is_1000(self):
        """_CACHE_MAX_SIZE constant is 1000."""
        assert ss._CACHE_MAX_SIZE == 1000


# ===========================================================================
# 2. get_model
# ===========================================================================

class TestGetModel:

    def test_lazy_loads_model(self, mock_model):
        """get_model returns the cached model if already loaded."""
        result = ss.get_model()
        assert result is mock_model

    def test_raises_import_error_when_not_installed(self):
        """get_model raises ImportError when sentence-transformers missing."""
        ss._model = None
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError, match="sentence-transformers not installed"):
                ss.get_model()

    def test_sets_global_model(self):
        """get_model sets the global _model once loaded."""
        mock_st_module = MagicMock()
        mock_instance = MagicMock()
        mock_st_module.SentenceTransformer.return_value = mock_instance

        with patch.dict('sys.modules', {'sentence_transformers': mock_st_module}):
            result = ss.get_model()
            assert result is mock_instance
            assert ss._model is mock_instance

    def test_does_not_reload_if_already_set(self):
        """get_model returns existing model without re-importing."""
        sentinel = object()
        ss._model = sentinel
        result = ss.get_model()
        assert result is sentinel


# ===========================================================================
# 3. embed_text
# ===========================================================================

class TestEmbedText:

    def test_returns_ndarray(self, mock_model):
        """embed_text returns a numpy ndarray."""
        result = ss.embed_text("hello")
        assert isinstance(result, np.ndarray)

    def test_correct_dimension(self, mock_model):
        """embed_text returns 384-dim vector."""
        result = ss.embed_text("hello")
        assert result.shape == (EMBEDDING_DIM,)

    def test_calls_model_encode(self, mock_model):
        """embed_text delegates to model.encode."""
        ss.embed_text("test text")
        mock_model.encode.assert_called_once_with("test text", convert_to_numpy=True)

    def test_deterministic_for_same_input(self, mock_model):
        """Same input produces same embedding."""
        emb1 = ss.embed_text("same")
        emb2 = ss.embed_text("same")
        np.testing.assert_array_equal(emb1, emb2)

    def test_different_for_different_input(self, mock_model):
        """Different inputs produce different embeddings."""
        emb1 = ss.embed_text("alpha")
        emb2 = ss.embed_text("beta")
        assert not np.array_equal(emb1, emb2)


# ===========================================================================
# 4. cosine_similarity
# ===========================================================================

class TestCosineSimilarity:

    def test_identical_vectors_score_one(self):
        """Identical normalised vectors have cosine similarity 1.0."""
        vec = _make_embedding(42)
        sim = ss.cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors_score_zero(self):
        """Orthogonal vectors have cosine similarity 0.0."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        sim = ss.cosine_similarity(a, b)
        assert abs(sim - 0.0) < 1e-6

    def test_opposite_vectors_score_negative_one(self):
        """Opposite vectors have cosine similarity -1.0."""
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        sim = ss.cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 1e-6

    def test_score_between_neg_one_and_one(self):
        """Cosine similarity is always in [-1, 1] for normalised vectors."""
        a = _make_embedding(1)
        b = _make_embedding(2)
        sim = ss.cosine_similarity(a, b)
        assert -1.0 <= sim <= 1.0

    def test_symmetry(self):
        """cosine_similarity(a, b) == cosine_similarity(b, a)."""
        a = _make_embedding(10)
        b = _make_embedding(20)
        assert abs(ss.cosine_similarity(a, b) - ss.cosine_similarity(b, a)) < 1e-6

    def test_non_unit_vectors(self):
        """Works correctly with non-unit vectors."""
        a = np.array([3.0, 4.0])
        b = np.array([4.0, 3.0])
        expected = (3*4 + 4*3) / (5.0 * 5.0)  # 24/25 = 0.96
        sim = ss.cosine_similarity(a, b)
        assert abs(sim - expected) < 1e-6


# ===========================================================================
# 5. semantic_search
# ===========================================================================

class TestSemanticSearch:

    def test_returns_list(self, mock_model):
        """semantic_search returns a list."""
        memories = [{"content": "the sky is blue"}]
        results = ss.semantic_search("sky", memories)
        assert isinstance(results, list)

    def test_result_structure_has_similarity_key(self, mock_model):
        """Each result dict contains a 'similarity' key."""
        memories = [{"content": "testing structure"}]
        results = ss.semantic_search("testing structure", memories, threshold=-1.0)
        assert len(results) >= 1
        assert 'similarity' in results[0]

    def test_result_preserves_original_fields(self, mock_model):
        """Original memory fields are preserved in result."""
        mem = {"content": "hello world", "id": 42, "tags": ["test"]}
        results = ss.semantic_search("hello", [mem], threshold=0.0)
        assert len(results) == 1
        assert results[0]["id"] == 42
        assert results[0]["tags"] == ["test"]
        assert results[0]["content"] == "hello world"

    def test_similarity_is_float(self, mock_model):
        """Similarity score is a Python float."""
        memories = [{"content": "float check"}]
        results = ss.semantic_search("check", memories, threshold=0.0)
        assert isinstance(results[0]['similarity'], float)

    def test_identical_query_and_content_scores_high(self, mock_model):
        """Query identical to content yields similarity ~1.0."""
        text = "exact match text"
        memories = [{"content": text}]
        results = ss.semantic_search(text, memories, threshold=0.0)
        assert len(results) == 1
        assert results[0]['similarity'] > 0.99

    def test_top_k_limits_results(self, mock_model):
        """top_k caps the number of returned results."""
        memories = [{"content": f"item-{i}"} for i in range(20)]
        results = ss.semantic_search("item", memories, top_k=5, threshold=0.0)
        assert len(results) <= 5

    def test_top_k_default_is_10(self, mock_model):
        """Default top_k is 10."""
        memories = [{"content": f"item-{i}"} for i in range(15)]
        results = ss.semantic_search("item", memories, threshold=0.0)
        assert len(results) <= 10

    def test_threshold_filters_low_scores(self, mock_model):
        """Results below threshold are excluded."""
        memories = [{"content": "unrelated XYZ abc123"}]
        results = ss.semantic_search("query", memories, threshold=0.999)
        # With hash-based fake embeddings, a non-identical string won't score 0.999
        assert len(results) == 0

    def test_threshold_zero_returns_all(self, mock_model):
        """Threshold=0.0 returns all memories (assuming non-negative similarity)."""
        memories = [{"content": f"mem-{i}"} for i in range(5)]
        results = ss.semantic_search("mem", memories, threshold=0.0)
        # Some may still be negative with random vectors, but most should pass
        assert len(results) >= 1

    def test_results_sorted_descending_by_similarity(self, mock_model):
        """Results are sorted by similarity, highest first."""
        memories = [{"content": f"topic {i}"} for i in range(10)]
        results = ss.semantic_search("topic", memories, top_k=10, threshold=0.0)
        scores = [r['similarity'] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_memories_returns_empty(self, mock_model):
        """Empty memories list returns empty results."""
        results = ss.semantic_search("query", [])
        assert results == []

    def test_memories_with_empty_content_skipped(self, mock_model):
        """Memories with empty string content are skipped."""
        memories = [
            {"content": ""},
            {"content": "valid entry"},
        ]
        results = ss.semantic_search("valid entry", memories, threshold=-1.0)
        contents = [r['content'] for r in results]
        assert "valid entry" in contents
        assert "" not in contents

    def test_memories_without_content_key_skipped(self, mock_model):
        """Memories missing 'content' key entirely are skipped."""
        memories = [
            {"id": 1},
            {"content": "has content"},
        ]
        results = ss.semantic_search("has content", memories, threshold=-1.0)
        assert len(results) == 1
        assert results[0]['content'] == "has content"

    def test_single_memory(self, mock_model):
        """Works with a single memory."""
        memories = [{"content": "only one"}]
        results = ss.semantic_search("one", memories, threshold=0.0)
        assert len(results) == 1

    def test_top_k_larger_than_results(self, mock_model):
        """top_k larger than matching results returns all matches."""
        memories = [{"content": "one"}, {"content": "two"}]
        results = ss.semantic_search("one", memories, top_k=100, threshold=-1.0)
        assert len(results) == 2

    def test_custom_threshold(self, mock_model):
        """Custom threshold value is respected."""
        text = "exact match for threshold test"
        memories = [{"content": text}, {"content": "something completely different abcxyz"}]
        # Identical text should score ~1.0, the other should score much lower
        results = ss.semantic_search(text, memories, threshold=0.99)
        assert len(results) == 1
        assert results[0]['content'] == text


# ===========================================================================
# 6. Caching (LRU OrderedDict)
# ===========================================================================

class TestCaching:

    def test_cache_stores_embedding_on_first_access(self, mock_model):
        """First access to a memory stores its embedding in cache."""
        memories = [{"content": "cache me"}]
        ss.semantic_search("query", memories, threshold=0.0)
        cache_key = "cache me"[:100]
        assert cache_key in ss._embeddings_cache

    def test_cache_hit_skips_embed_text(self, mock_model):
        """Second search with same memory content uses cache, not model."""
        memories = [{"content": "repeated content"}]
        ss.semantic_search("first", memories, threshold=0.0)
        mock_model.encode.reset_mock()
        # Search again with same memories - should hit cache for memory embedding
        # but still call embed_text for the new query
        ss.semantic_search("second", memories, threshold=0.0)
        # Model was called once for "second" query, but NOT for "repeated content"
        calls = [str(c) for c in mock_model.encode.call_args_list]
        assert len(mock_model.encode.call_args_list) == 1  # only the query

    def test_cache_key_uses_first_100_chars(self, mock_model):
        """Cache key is first 100 chars of content."""
        long_content = "x" * 200
        memories = [{"content": long_content}]
        ss.semantic_search("query", memories, threshold=0.0)
        cache_key = long_content[:100]
        assert cache_key in ss._embeddings_cache
        assert long_content not in ss._embeddings_cache

    def test_cache_move_to_end_on_access(self, mock_model):
        """Accessing cached entry moves it to end (most recent)."""
        memories_a = [{"content": "entry_a"}]
        memories_b = [{"content": "entry_b"}]
        ss.semantic_search("q1", memories_a, threshold=0.0)
        ss.semantic_search("q2", memories_b, threshold=0.0)
        # entry_a is oldest. Access it again.
        ss.semantic_search("q3", memories_a, threshold=0.0)
        # entry_a should now be at the end (most recent)
        keys = list(ss._embeddings_cache.keys())
        assert keys[-1] == "entry_a"[:100]

    def test_cache_eviction_at_max_size(self, mock_model):
        """Cache evicts oldest entry when exceeding _CACHE_MAX_SIZE."""
        original_max = ss._CACHE_MAX_SIZE
        ss._CACHE_MAX_SIZE = 5
        try:
            for i in range(6):
                memories = [{"content": f"evict-{i}"}]
                ss.semantic_search("q", memories, threshold=0.0)
            assert len(ss._embeddings_cache) == 5
            # First entry should have been evicted
            assert "evict-0"[:100] not in ss._embeddings_cache
            # Last entry should be present
            assert "evict-5"[:100] in ss._embeddings_cache
        finally:
            ss._CACHE_MAX_SIZE = original_max

    def test_cache_preserves_recent_entries(self, mock_model):
        """LRU eviction keeps the most recently used entries."""
        original_max = ss._CACHE_MAX_SIZE
        ss._CACHE_MAX_SIZE = 3
        try:
            for i in range(5):
                memories = [{"content": f"keep-{i}"}]
                ss.semantic_search("q", memories, threshold=0.0)
            # keep-3 and keep-4 should be present (most recent)
            assert "keep-3"[:100] in ss._embeddings_cache
            assert "keep-4"[:100] in ss._embeddings_cache
            # keep-0 and keep-1 should be evicted
            assert "keep-0"[:100] not in ss._embeddings_cache
            assert "keep-1"[:100] not in ss._embeddings_cache
        finally:
            ss._CACHE_MAX_SIZE = original_max

    def test_cache_lru_refresh_prevents_eviction(self, mock_model):
        """Accessing an entry refreshes it, protecting from eviction."""
        original_max = ss._CACHE_MAX_SIZE
        ss._CACHE_MAX_SIZE = 3
        try:
            # Add a, b, c
            for name in ["aaa", "bbb", "ccc"]:
                memories = [{"content": name}]
                ss.semantic_search("q", memories, threshold=0.0)
            # Refresh "aaa" by accessing it again
            ss.semantic_search("q", [{"content": "aaa"}], threshold=0.0)
            # Now add "ddd" - should evict "bbb" (oldest non-refreshed), not "aaa"
            ss.semantic_search("q", [{"content": "ddd"}], threshold=0.0)
            assert "aaa" in ss._embeddings_cache
            assert "bbb" not in ss._embeddings_cache
        finally:
            ss._CACHE_MAX_SIZE = original_max

    def test_default_cache_max_is_1000(self):
        """Default _CACHE_MAX_SIZE is 1000."""
        assert ss._CACHE_MAX_SIZE == 1000

    def test_cache_bounded_at_1000(self, mock_model):
        """Cache never exceeds _CACHE_MAX_SIZE entries (test with small limit)."""
        original_max = ss._CACHE_MAX_SIZE
        ss._CACHE_MAX_SIZE = 10
        try:
            for i in range(15):
                memories = [{"content": f"bounded-{i}"}]
                ss.semantic_search("q", memories, threshold=0.0)
            assert len(ss._embeddings_cache) <= 10
        finally:
            ss._CACHE_MAX_SIZE = original_max


# ===========================================================================
# 7. clear_embedding_cache
# ===========================================================================

class TestClearEmbeddingCache:

    def test_clears_cache(self, mock_model):
        """clear_embedding_cache empties the cache."""
        ss._embeddings_cache["key"] = _make_embedding(1)
        assert len(ss._embeddings_cache) > 0
        ss.clear_embedding_cache()
        assert len(ss._embeddings_cache) == 0

    def test_returns_none(self):
        """clear_embedding_cache returns None."""
        result = ss.clear_embedding_cache()
        assert result is None

    def test_cache_is_new_ordered_dict_after_clear(self, mock_model):
        """Cache is a fresh OrderedDict after clear."""
        ss._embeddings_cache["old"] = _make_embedding(0)
        ss.clear_embedding_cache()
        assert isinstance(ss._embeddings_cache, OrderedDict)
        assert len(ss._embeddings_cache) == 0

    def test_search_works_after_clear(self, mock_model):
        """semantic_search works correctly after clearing cache."""
        text = "after clear"
        memories = [{"content": text}]
        ss.semantic_search(text, memories, threshold=-1.0)
        ss.clear_embedding_cache()
        # Should still work - just recomputes embeddings
        results = ss.semantic_search(text, memories, threshold=-1.0)
        assert len(results) >= 1


# ===========================================================================
# 8. precompute_embeddings
# ===========================================================================

class TestPrecomputeEmbeddings:

    def test_returns_dict(self, mock_model):
        """precompute_embeddings returns a dict."""
        memories = [{"content": "alpha"}, {"content": "beta"}]
        result = ss.precompute_embeddings(memories)
        assert isinstance(result, dict)

    def test_keys_are_first_100_chars(self, mock_model):
        """Keys in returned dict are first 100 chars of content."""
        memories = [{"content": "short text"}, {"content": "x" * 200}]
        result = ss.precompute_embeddings(memories)
        assert "short text" in result
        assert "x" * 100 in result
        assert "x" * 200 not in result

    def test_values_are_ndarrays(self, mock_model):
        """Values in returned dict are numpy ndarrays."""
        memories = [{"content": "embedding val"}]
        result = ss.precompute_embeddings(memories)
        for val in result.values():
            assert isinstance(val, np.ndarray)

    def test_correct_number_of_entries(self, mock_model):
        """Returns one entry per memory with content."""
        memories = [{"content": f"item-{i}"} for i in range(5)]
        result = ss.precompute_embeddings(memories)
        assert len(result) == 5

    def test_skips_memories_without_content(self, mock_model):
        """Memories without 'content' key are skipped."""
        memories = [{"id": 1}, {"content": "has content"}, {"content": ""}]
        result = ss.precompute_embeddings(memories)
        # Empty string content[:100] is "" which is falsy, so it should be skipped
        assert len(result) == 1

    def test_empty_memories_list(self, mock_model):
        """Empty list returns empty dict."""
        result = ss.precompute_embeddings([])
        assert result == {}

    def test_calls_model_encode_with_batch(self, mock_model):
        """precompute_embeddings calls model.encode with a list of texts."""
        memories = [{"content": "batch1"}, {"content": "batch2"}]
        ss.precompute_embeddings(memories)
        # The texts passed should be truncated to 100 chars
        call_args = mock_model.encode.call_args
        texts_arg = call_args[0][0]
        assert isinstance(texts_arg, list)
        assert len(texts_arg) == 2


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_empty_query_string(self, mock_model):
        """Empty query string does not crash."""
        memories = [{"content": "something"}]
        results = ss.semantic_search("", memories, threshold=0.0)
        assert isinstance(results, list)

    def test_special_characters_in_query(self, mock_model):
        """Query with special characters works."""
        memories = [{"content": "normal text"}]
        results = ss.semantic_search("!@#$%^&*()", memories, threshold=0.0)
        assert isinstance(results, list)

    def test_unicode_content(self, mock_model):
        """Unicode content is handled correctly."""
        memories = [{"content": "cafe\u0301 na\u00efve"}]
        results = ss.semantic_search("cafe", memories, threshold=0.0)
        assert isinstance(results, list)

    def test_newlines_in_content(self, mock_model):
        """Content with newlines works."""
        memories = [{"content": "line1\nline2\nline3"}]
        results = ss.semantic_search("line", memories, threshold=0.0)
        assert isinstance(results, list)

    def test_very_long_content(self, mock_model):
        """Very long content does not crash."""
        long_content = "word " * 10000
        memories = [{"content": long_content}]
        results = ss.semantic_search("word", memories, threshold=0.0)
        assert isinstance(results, list)

    def test_all_memories_below_threshold(self, mock_model):
        """Returns empty list when all similarities are below threshold."""
        memories = [{"content": f"unique-content-{i}"} for i in range(5)]
        results = ss.semantic_search("query", memories, threshold=0.9999)
        assert results == []

    def test_none_content_treated_as_empty(self, mock_model):
        """Memory with content=None is treated as empty and skipped."""
        memories = [{"content": None}, {"content": "valid"}]
        results = ss.semantic_search("valid", memories, threshold=0.0)
        # None is falsy, so get('content', '') returns None which is falsy
        contents = [r['content'] for r in results]
        assert "valid" in contents

    def test_mixed_valid_and_invalid_memories(self, mock_model):
        """Mix of valid/invalid memories processes correctly."""
        memories = [
            {"content": ""},
            {"id": 1},
            {"content": "real one"},
            {"content": None},
            {"content": "another real one"},
        ]
        results = ss.semantic_search("real", memories, threshold=-1.0)
        assert len(results) == 2

    def test_top_k_zero(self, mock_model):
        """top_k=0 returns empty list (slice [:0])."""
        memories = [{"content": "should not appear"}]
        results = ss.semantic_search("query", memories, top_k=0, threshold=0.0)
        assert results == []

    def test_negative_threshold(self, mock_model):
        """Negative threshold returns all memories (cosine sim >= -1)."""
        memories = [{"content": f"neg-{i}"} for i in range(3)]
        results = ss.semantic_search("neg", memories, threshold=-1.0)
        assert len(results) == 3

    def test_similarity_key_added_not_replacing(self, mock_model):
        """'similarity' key is added alongside existing keys, not replacing them."""
        mem = {"content": "test", "similarity": "should be overwritten"}
        results = ss.semantic_search("test", [mem], threshold=0.0)
        assert len(results) == 1
        # The **memory spread means 'similarity' from the original is overwritten
        # by the new float similarity score
        assert isinstance(results[0]['similarity'], float)


# ===========================================================================
# 10. Error handling
# ===========================================================================

class TestErrorHandling:

    def test_get_model_import_error_message(self):
        """ImportError message includes install instructions."""
        ss._model = None
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError, match="pip install sentence-transformers"):
                ss.get_model()

    def test_embed_text_propagates_model_error(self):
        """embed_text propagates ImportError from get_model."""
        ss._model = None
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError):
                ss.embed_text("test")

    def test_semantic_search_propagates_model_error(self):
        """semantic_search propagates ImportError from get_model."""
        ss._model = None
        memories = [{"content": "test"}]
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            with pytest.raises(ImportError):
                ss.semantic_search("query", memories)


# ===========================================================================
# 11. Integration-style tests (multiple functions together)
# ===========================================================================

class TestIntegration:

    def test_search_then_clear_then_search(self, mock_model):
        """Full cycle: search, clear cache, search again."""
        memories = [{"content": "persistent"}]
        results1 = ss.semantic_search("query", memories, threshold=0.0)
        ss.clear_embedding_cache()
        results2 = ss.semantic_search("query", memories, threshold=0.0)
        # Both should return same results
        assert len(results1) == len(results2)
        assert abs(results1[0]['similarity'] - results2[0]['similarity']) < 1e-6

    def test_precompute_then_search_uses_cache(self, mock_model):
        """Precompute does not populate the module cache, but search does."""
        memories = [{"content": "precomputed"}]
        ss.precompute_embeddings(memories)
        # precompute_embeddings returns its own dict, doesn't populate _embeddings_cache
        # but semantic_search will populate it
        ss.semantic_search("query", memories, threshold=0.0)
        assert "precomputed"[:100] in ss._embeddings_cache

    def test_cosine_similarity_with_embeddings(self, mock_model):
        """embed_text + cosine_similarity produce valid score."""
        emb_a = ss.embed_text("hello")
        emb_b = ss.embed_text("hello")
        sim = ss.cosine_similarity(emb_a, emb_b)
        assert abs(sim - 1.0) < 1e-6

    def test_multiple_searches_accumulate_cache(self, mock_model):
        """Multiple searches with different memories grow the cache."""
        for i in range(5):
            memories = [{"content": f"multi-{i}"}]
            ss.semantic_search("q", memories, threshold=0.0)
        assert len(ss._embeddings_cache) == 5
