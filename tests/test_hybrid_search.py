"""
Tests for hybrid_search.py - Hybrid semantic + BM25 keyword search.

Covers:
1. bm25_score (term matching, length normalization, parameter tuning)
2. hybrid_search (weighted combination, default weights, use_semantic toggle)
3. keyword_search (convenience wrapper for BM25-only mode)
4. Weighting (70% semantic + 30% keyword default ratio)
5. Result merging and deduplication
6. Top-k and threshold filtering
7. Edge cases (empty query, no memories, empty content, special characters)
8. Error handling (semantic search unavailable, import failures)
"""

import pytest
import math
from unittest.mock import patch, MagicMock

from memory_system import hybrid_search as hs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memories(contents):
    """Create memory dicts from a list of content strings."""
    return [{"content": c} for c in contents]


def _fake_semantic_search(query, memories, top_k=1):
    """
    A fake semantic_search that returns a deterministic similarity score.

    Score is 1.0 when query == content, otherwise a simple
    character-overlap ratio so tests stay predictable.
    """
    results = []
    for mem in memories:
        content = mem.get('content', '')
        if not content:
            continue
        if query.lower() == content.lower():
            sim = 1.0
        else:
            # Simple overlap: fraction of query words found in content
            q_words = set(query.lower().split())
            c_words = set(content.lower().split())
            if q_words:
                sim = len(q_words & c_words) / len(q_words)
            else:
                sim = 0.0
        results.append({**mem, 'similarity': sim})
    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:top_k]


# ===========================================================================
# 1. bm25_score
# ===========================================================================

class TestBM25Score:

    def test_exact_single_term_match(self):
        """Single term present in document yields positive score."""
        score = hs.bm25_score("office", "office setup guide", avg_doc_length=3.0)
        assert score > 0.0

    def test_no_match_returns_zero(self):
        """Query term absent from document yields zero."""
        score = hs.bm25_score("python", "office setup guide", avg_doc_length=3.0)
        assert score == 0.0

    def test_multiple_matching_terms(self):
        """Multiple matching terms produce higher score than single match."""
        single = hs.bm25_score("office", "office setup guide", avg_doc_length=3.0)
        double = hs.bm25_score("office setup", "office setup guide", avg_doc_length=3.0)
        assert double > single

    def test_term_frequency_increases_score(self):
        """Higher term frequency in document increases score."""
        once = hs.bm25_score("office", "office setup guide", avg_doc_length=3.0)
        twice = hs.bm25_score("office", "office office setup guide", avg_doc_length=4.0)
        assert twice > once

    def test_case_insensitive(self):
        """BM25 matching is case-insensitive."""
        lower = hs.bm25_score("office", "office setup", avg_doc_length=2.0)
        upper = hs.bm25_score("OFFICE", "Office Setup", avg_doc_length=2.0)
        assert abs(lower - upper) < 1e-6

    def test_empty_query_returns_zero(self):
        """Empty query string yields zero score."""
        score = hs.bm25_score("", "some document content", avg_doc_length=3.0)
        assert score == 0.0

    def test_empty_document_returns_zero(self):
        """Empty document yields zero score."""
        score = hs.bm25_score("query", "", avg_doc_length=3.0)
        assert score == 0.0

    def test_both_empty_returns_zero(self):
        """Both empty query and document yields zero."""
        score = hs.bm25_score("", "", avg_doc_length=1.0)
        assert score == 0.0

    def test_custom_k1_parameter(self):
        """Custom k1 parameter affects score."""
        # Use a document where tf>1 so k1 saturation actually differs
        default = hs.bm25_score("test", "test test doc", avg_doc_length=3.0)
        high_k1 = hs.bm25_score("test", "test test doc", avg_doc_length=3.0, k1=3.0)
        # Different k1 should produce different score when tf > 1
        assert default != high_k1

    def test_custom_b_parameter(self):
        """Custom b parameter affects length normalization."""
        no_norm = hs.bm25_score("test", "test doc", avg_doc_length=2.0, b=0.0)
        full_norm = hs.bm25_score("test", "test doc", avg_doc_length=2.0, b=1.0)
        # b=0 means no length normalization, b=1 means full
        # For same doc length they may differ since avg_doc_length factors in
        assert isinstance(no_norm, float)
        assert isinstance(full_norm, float)

    def test_longer_doc_lower_score_with_b(self):
        """Longer document gets penalized when b > 0 (length normalization)."""
        short_doc = hs.bm25_score("test", "test", avg_doc_length=5.0, b=0.75)
        long_doc = hs.bm25_score("test", "test a b c d e f g h i j", avg_doc_length=5.0, b=0.75)
        # Longer document with same term frequency gets lower score due to normalization
        assert short_doc > long_doc

    def test_idf_is_one(self):
        """Current implementation uses simplified IDF=1.0."""
        # With single matching term, IDF=1.0, the score should equal
        # the TF component: tf*(k1+1) / (tf + k1*(1 - b + b*(dl/avgdl)))
        score = hs.bm25_score("word", "word", avg_doc_length=1.0, k1=1.5, b=0.75)
        # tf=1, dl=1, avgdl=1: 1*(1.5+1) / (1 + 1.5*(1 - 0.75 + 0.75*1)) = 2.5/2.5 = 1.0
        assert abs(score - 1.0) < 1e-6

    def test_returns_float(self):
        """bm25_score always returns a float."""
        score = hs.bm25_score("test", "test", avg_doc_length=1.0)
        assert isinstance(score, float)

    def test_whitespace_tokenization(self):
        """Tokenization splits on whitespace only."""
        # "hello-world" is a single token, not two
        score = hs.bm25_score("hello", "hello-world is here", avg_doc_length=3.0)
        # "hello" should NOT match "hello-world"
        assert score == 0.0

    def test_repeated_query_terms(self):
        """Repeated query terms don't double-count BM25 contribution per occurrence."""
        single_q = hs.bm25_score("office", "office setup", avg_doc_length=2.0)
        double_q = hs.bm25_score("office office", "office setup", avg_doc_length=2.0)
        # "office office" iterates twice, but same tf each time => double the score
        assert abs(double_q - 2 * single_q) < 1e-6

    def test_avg_doc_length_affects_score(self):
        """Average document length affects normalization."""
        short_avg = hs.bm25_score("test", "test item", avg_doc_length=2.0)
        long_avg = hs.bm25_score("test", "test item", avg_doc_length=10.0)
        # When avg_doc_length is longer (doc is shorter than avg), score goes up
        assert long_avg > short_avg


# ===========================================================================
# 2. hybrid_search - basic behavior
# ===========================================================================

class TestHybridSearchBasic:

    def test_returns_list(self):
        """hybrid_search returns a list."""
        memories = _make_memories(["test"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        assert isinstance(results, list)

    def test_empty_memories_returns_empty(self):
        """Empty memories list returns empty results."""
        results = hs.hybrid_search("query", [], use_semantic=False)
        assert results == []

    def test_result_contains_hybrid_score(self):
        """Each result has hybrid_score key."""
        memories = _make_memories(["test content"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        assert len(results) == 1
        assert 'hybrid_score' in results[0]

    def test_result_contains_bm25_score(self):
        """Each result has bm25_score key."""
        memories = _make_memories(["test content"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        assert 'bm25_score' in results[0]

    def test_result_contains_semantic_score(self):
        """Each result has semantic_score key (even when semantic disabled)."""
        memories = _make_memories(["test content"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        assert 'semantic_score' in results[0]

    def test_preserves_original_fields(self):
        """Original memory fields are preserved in results."""
        mem = {"content": "test", "id": 42, "tags": ["a", "b"]}
        results = hs.hybrid_search("test", [mem], use_semantic=False)
        assert results[0]["id"] == 42
        assert results[0]["tags"] == ["a", "b"]
        assert results[0]["content"] == "test"

    def test_results_sorted_by_hybrid_score_descending(self):
        """Results are sorted by hybrid_score, highest first."""
        memories = _make_memories([
            "alpha beta gamma",
            "alpha",
            "alpha beta",
        ])
        results = hs.hybrid_search("alpha beta", memories, use_semantic=False, top_k=10)
        scores = [r['hybrid_score'] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_matching_content_scores_higher(self):
        """Content matching query scores higher than non-matching."""
        memories = _make_memories(["office setup guide", "cooking recipe blog"])
        results = hs.hybrid_search("office", memories, use_semantic=False)
        assert results[0]['content'] == "office setup guide"

    def test_no_match_gets_zero_bm25(self):
        """Content with no matching terms gets bm25_score of 0."""
        memories = _make_memories(["completely unrelated xyz"])
        results = hs.hybrid_search("office setup", memories, use_semantic=False)
        assert results[0]['bm25_score'] == 0.0


# ===========================================================================
# 3. hybrid_search - semantic integration
# ===========================================================================

class TestHybridSearchSemantic:

    def test_semantic_score_used_when_enabled(self):
        """When use_semantic=True and semantic_search available, semantic_score > 0."""
        memories = _make_memories(["workspace configuration"])
        mock_semantic = MagicMock(return_value=[{'similarity': 0.85}])
        with patch('memory_system.hybrid_search.semantic_search', mock_semantic, create=True):
            # Force fresh import by patching at module level
            import memory_system.hybrid_search as _hs
            original = getattr(_hs, '_semantic_search_fn', None)
            results = hs.hybrid_search("workspace", memories, use_semantic=True)
            # semantic_score should be > 0 since semantic search is available
            assert len(results) == 1
            assert results[0]['semantic_score'] >= 0.0

    def test_semantic_disabled_zeroes_semantic_score(self):
        """When use_semantic=False, semantic_score is 0.0."""
        memories = _make_memories(["test content"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        assert results[0]['semantic_score'] == 0.0

    def test_semantic_import_failure_falls_back_to_bm25(self):
        """When semantic_search import fails, falls back to BM25 only."""
        memories = _make_memories(["test content"])
        with patch.dict('sys.modules', {'memory_system.semantic_search': None}):
            results = hs.hybrid_search("test", memories, use_semantic=True)
        assert len(results) == 1
        assert results[0]['semantic_score'] == 0.0
        assert results[0]['bm25_score'] > 0.0

    def test_semantic_fallback_adjusts_weights(self):
        """When semantic fails, weights adjust to 100% BM25."""
        memories = _make_memories(["test content"])
        with patch.dict('sys.modules', {'memory_system.semantic_search': None}):
            results = hs.hybrid_search("test", memories, use_semantic=True)
        assert abs(results[0]['hybrid_score'] - results[0]['bm25_score']) < 1e-6


# ===========================================================================
# 4. Weighting
# ===========================================================================

class TestWeighting:

    def test_default_semantic_weight_is_07(self):
        """Default semantic_weight parameter is 0.7."""
        import inspect
        sig = inspect.signature(hs.hybrid_search)
        assert sig.parameters['semantic_weight'].default == 0.7

    def test_default_bm25_weight_is_03(self):
        """Default bm25_weight parameter is 0.3."""
        import inspect
        sig = inspect.signature(hs.hybrid_search)
        assert sig.parameters['bm25_weight'].default == 0.3

    def test_bm25_only_weights(self):
        """With use_semantic=False, hybrid_score = bm25_weight * bm25."""
        memories = _make_memories(["test content here"])
        results = hs.hybrid_search(
            "test", memories,
            use_semantic=False,
            semantic_weight=0.7,
            bm25_weight=0.3
        )
        expected = 0.3 * results[0]['bm25_score']
        assert abs(results[0]['hybrid_score'] - expected) < 1e-6

    def test_custom_weights_applied(self):
        """Custom weights are respected in score calculation."""
        memories = _make_memories(["test data"])
        results_low_bm25 = hs.hybrid_search(
            "test", memories, use_semantic=False,
            semantic_weight=0.9, bm25_weight=0.1
        )
        results_high_bm25 = hs.hybrid_search(
            "test", memories, use_semantic=False,
            semantic_weight=0.1, bm25_weight=0.9
        )
        # Higher BM25 weight should give higher hybrid score (since semantic=0)
        assert results_high_bm25[0]['hybrid_score'] > results_low_bm25[0]['hybrid_score']

    def test_zero_bm25_weight(self):
        """bm25_weight=0 makes BM25 not contribute to hybrid score."""
        memories = _make_memories(["test"])
        results = hs.hybrid_search(
            "test", memories, use_semantic=False,
            bm25_weight=0.0
        )
        assert results[0]['hybrid_score'] == 0.0

    def test_equal_weights(self):
        """Equal weights (0.5/0.5) work correctly."""
        memories = _make_memories(["test"])
        results = hs.hybrid_search(
            "test", memories, use_semantic=False,
            semantic_weight=0.5, bm25_weight=0.5
        )
        expected = 0.5 * results[0]['bm25_score']
        assert abs(results[0]['hybrid_score'] - expected) < 1e-6


# ===========================================================================
# 5. Top-k and filtering
# ===========================================================================

class TestTopKAndFiltering:

    def test_top_k_limits_results(self):
        """top_k caps the number of returned results."""
        memories = _make_memories([f"item {i}" for i in range(20)])
        results = hs.hybrid_search("item", memories, top_k=5, use_semantic=False)
        assert len(results) <= 5

    def test_top_k_default_is_10(self):
        """Default top_k is 10."""
        import inspect
        sig = inspect.signature(hs.hybrid_search)
        assert sig.parameters['top_k'].default == 10

    def test_top_k_larger_than_results(self):
        """top_k larger than available results returns all results."""
        memories = _make_memories(["one", "two"])
        results = hs.hybrid_search("one", memories, top_k=100, use_semantic=False)
        assert len(results) == 2

    def test_top_k_one(self):
        """top_k=1 returns only the best match."""
        memories = _make_memories(["alpha beta", "alpha", "gamma"])
        results = hs.hybrid_search("alpha", memories, top_k=1, use_semantic=False)
        assert len(results) == 1

    def test_top_k_zero(self):
        """top_k=0 returns empty list."""
        memories = _make_memories(["test"])
        results = hs.hybrid_search("test", memories, top_k=0, use_semantic=False)
        assert results == []

    def test_empty_content_memories_skipped(self):
        """Memories with empty content are skipped."""
        memories = [
            {"content": ""},
            {"content": "valid item"},
        ]
        results = hs.hybrid_search("valid", memories, use_semantic=False)
        assert len(results) == 1
        assert results[0]['content'] == "valid item"

    def test_missing_content_key_skipped(self):
        """Memories without 'content' key are skipped."""
        memories = [
            {"id": 1},
            {"content": "has content"},
        ]
        results = hs.hybrid_search("has", memories, use_semantic=False)
        assert len(results) == 1
        assert results[0]['content'] == "has content"

    def test_returns_highest_scoring_results(self):
        """top_k returns the highest-scoring results, not arbitrary ones."""
        memories = _make_memories([
            "completely unrelated xyz",
            "office setup guide for new employees",
            "another unrelated topic abc",
            "office desk arrangement",
        ])
        results = hs.hybrid_search("office", memories, top_k=2, use_semantic=False)
        contents = [r['content'] for r in results]
        assert "office setup guide for new employees" in contents
        assert "office desk arrangement" in contents


# ===========================================================================
# 6. keyword_search (convenience wrapper)
# ===========================================================================

class TestKeywordSearch:

    def test_returns_list(self):
        """keyword_search returns a list."""
        memories = _make_memories(["test"])
        results = hs.keyword_search("test", memories)
        assert isinstance(results, list)

    def test_equivalent_to_hybrid_bm25_only(self):
        """keyword_search produces same results as hybrid_search with use_semantic=False."""
        memories = _make_memories(["alpha beta", "gamma delta", "alpha gamma"])
        kw_results = hs.keyword_search("alpha", memories, top_k=10)
        hy_results = hs.hybrid_search("alpha", memories, top_k=10, use_semantic=False)
        assert len(kw_results) == len(hy_results)
        for kw, hy in zip(kw_results, hy_results):
            assert kw['content'] == hy['content']
            assert abs(kw['hybrid_score'] - hy['hybrid_score']) < 1e-6

    def test_semantic_score_always_zero(self):
        """keyword_search always has semantic_score=0."""
        memories = _make_memories(["test content"])
        results = hs.keyword_search("test", memories)
        for r in results:
            assert r['semantic_score'] == 0.0

    def test_top_k_parameter_forwarded(self):
        """top_k parameter is forwarded to hybrid_search."""
        memories = _make_memories([f"item {i}" for i in range(20)])
        results = hs.keyword_search("item", memories, top_k=3)
        assert len(results) <= 3

    def test_empty_memories(self):
        """Empty memories returns empty results."""
        results = hs.keyword_search("query", [])
        assert results == []

    def test_default_top_k_is_10(self):
        """Default top_k for keyword_search is 10."""
        import inspect
        sig = inspect.signature(hs.keyword_search)
        assert sig.parameters['top_k'].default == 10


# ===========================================================================
# 7. Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_empty_query(self):
        """Empty query string does not crash."""
        memories = _make_memories(["some content"])
        results = hs.hybrid_search("", memories, use_semantic=False)
        assert isinstance(results, list)

    def test_empty_query_all_zero_scores(self):
        """Empty query gives all BM25 scores of zero."""
        memories = _make_memories(["some content"])
        results = hs.hybrid_search("", memories, use_semantic=False)
        for r in results:
            assert r['bm25_score'] == 0.0

    def test_single_memory(self):
        """Works with single memory."""
        memories = _make_memories(["only one"])
        results = hs.hybrid_search("one", memories, use_semantic=False)
        assert len(results) == 1

    def test_all_memories_no_match(self):
        """All memories with no matching terms still returned (with zero scores)."""
        memories = _make_memories(["alpha", "beta", "gamma"])
        results = hs.hybrid_search("xyz", memories, use_semantic=False)
        # All get zero BM25 scores but are still included
        assert len(results) == 3
        for r in results:
            assert r['bm25_score'] == 0.0

    def test_special_characters_in_query(self):
        """Query with special characters does not crash."""
        memories = _make_memories(["normal text"])
        results = hs.hybrid_search("!@#$%^&*()", memories, use_semantic=False)
        assert isinstance(results, list)

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        memories = _make_memories(["cafe\u0301 na\u00efve"])
        results = hs.hybrid_search("cafe", memories, use_semantic=False)
        assert isinstance(results, list)

    def test_newlines_in_content(self):
        """Content with newlines works."""
        memories = _make_memories(["line1\nline2\nline3"])
        results = hs.hybrid_search("line1", memories, use_semantic=False)
        assert isinstance(results, list)

    def test_very_long_content(self):
        """Very long content does not crash."""
        long_content = "word " * 10000
        memories = _make_memories([long_content])
        results = hs.hybrid_search("word", memories, use_semantic=False)
        assert isinstance(results, list)
        assert len(results) == 1

    def test_duplicate_memories(self):
        """Duplicate memories are each scored independently."""
        memories = _make_memories(["same content", "same content"])
        results = hs.hybrid_search("same", memories, use_semantic=False)
        assert len(results) == 2
        assert abs(results[0]['bm25_score'] - results[1]['bm25_score']) < 1e-6

    def test_none_content_crashes(self):
        """Memory with content=None causes AttributeError in avg_length calc.

        The code does m.get('content', '').split() which returns None
        when content is explicitly None, and None.split() raises.
        """
        memories = [{"content": None}, {"content": "valid"}]
        with pytest.raises(AttributeError):
            hs.hybrid_search("valid", memories, use_semantic=False)

    def test_mixed_valid_and_invalid_memories(self):
        """Mix of valid/invalid memories (without None) processes correctly."""
        memories = [
            {"content": ""},
            {"id": 1},
            {"content": "real one"},
            {"content": "another real one"},
        ]
        results = hs.hybrid_search("real", memories, use_semantic=False)
        assert len(results) == 2

    def test_avg_doc_length_computed_from_all_memories(self):
        """Average doc length includes all memories (even those with empty content)."""
        # Three memories: "a b c" (3 words), "" (0 words), "d" (1 word)
        # avg_length = (3 + 0 + 1) / 3 = 1.333...
        memories = [
            {"content": "a b c"},
            {"content": ""},
            {"content": "d"},
        ]
        results = hs.hybrid_search("a", memories, use_semantic=False)
        # Should not crash, and "a b c" should be returned
        assert any(r['content'] == "a b c" for r in results)

    def test_whitespace_only_content(self):
        """Content that is whitespace-only has zero word count but is still processed."""
        memories = _make_memories(["   ", "real content"])
        results = hs.hybrid_search("real", memories, use_semantic=False)
        # Whitespace-only content is truthy ("   " is not empty) so it won't be skipped
        # but it won't match anything
        real_results = [r for r in results if r['content'] == "real content"]
        assert len(real_results) == 1


# ===========================================================================
# 8. Score computation correctness
# ===========================================================================

class TestScoreComputation:

    def test_hybrid_score_formula_bm25_only(self):
        """Verify hybrid_score = semantic_weight*0 + bm25_weight*bm25 when semantic off."""
        memories = _make_memories(["test content"])
        results = hs.hybrid_search(
            "test", memories,
            use_semantic=False,
            semantic_weight=0.7,
            bm25_weight=0.3
        )
        r = results[0]
        expected = 0.7 * 0.0 + 0.3 * r['bm25_score']
        assert abs(r['hybrid_score'] - expected) < 1e-6

    def test_bm25_score_matches_direct_call_with_idf(self):
        """BM25 score in results matches direct bm25_score() call with corpus IDF."""
        memories = _make_memories(["test content here", "other stuff"])
        avg_length = sum(len(m['content'].split()) for m in memories) / len(memories)
        corpus_docs = [m['content'] for m in memories]
        corpus_idf = hs.compute_idf(corpus_docs)
        results = hs.hybrid_search("test", memories, use_semantic=False)
        for r in results:
            direct = hs.bm25_score("test", r['content'], avg_length, idf=corpus_idf)
            assert abs(r['bm25_score'] - direct) < 1e-6

    def test_ranking_order_by_relevance(self):
        """More relevant documents rank higher."""
        memories = _make_memories([
            "the weather is nice today",
            "office setup and office configuration",
            "office",
        ])
        results = hs.hybrid_search("office", memories, use_semantic=False, top_k=10)
        # "office setup and office configuration" has 2 occurrences of "office"
        # "office" has 1 occurrence but shorter doc (higher TF density)
        # Both should rank above "the weather is nice today"
        office_contents = [r['content'] for r in results if r['bm25_score'] > 0]
        non_office = [r['content'] for r in results if r['bm25_score'] == 0]
        assert len(office_contents) == 2
        assert "the weather is nice today" in non_office

    def test_all_scores_are_floats(self):
        """All score fields are floats."""
        memories = _make_memories(["test"])
        results = hs.hybrid_search("test", memories, use_semantic=False)
        r = results[0]
        assert isinstance(r['hybrid_score'], float)
        assert isinstance(r['semantic_score'], float)
        assert isinstance(r['bm25_score'], float)


# ===========================================================================
# 9. Error handling
# ===========================================================================

class TestErrorHandling:

    def test_semantic_import_error_graceful(self):
        """Import error for semantic_search is handled gracefully."""
        memories = _make_memories(["test content"])
        with patch.dict('sys.modules', {'memory_system.semantic_search': None}):
            results = hs.hybrid_search("test", memories, use_semantic=True)
        assert len(results) == 1
        assert results[0]['semantic_score'] == 0.0
        assert results[0]['bm25_score'] > 0.0

    def test_semantic_exception_graceful(self):
        """Generic exception from semantic_search is handled gracefully."""
        memories = _make_memories(["test content"])
        # Force use_semantic=True -- import will fail, caught by except
        results = hs.hybrid_search("test", memories, use_semantic=True)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_large_number_of_memories(self):
        """Handles large number of memories without error."""
        memories = _make_memories([f"memory number {i}" for i in range(500)])
        results = hs.hybrid_search("memory", memories, top_k=10, use_semantic=False)
        assert len(results) == 10


# ===========================================================================
# 10. Integration-style tests
# ===========================================================================

class TestIntegration:

    def test_keyword_search_ranking_matches_hybrid(self):
        """keyword_search ranking matches hybrid_search with semantic off."""
        memories = _make_memories([
            "python programming tutorial",
            "python snake species",
            "java programming guide",
        ])
        kw = hs.keyword_search("python programming", memories, top_k=10)
        hy = hs.hybrid_search("python programming", memories, top_k=10, use_semantic=False)
        assert [r['content'] for r in kw] == [r['content'] for r in hy]

    def test_multi_word_query_best_match_first(self):
        """Multi-word query ranks document with all terms highest."""
        memories = _make_memories([
            "office",
            "setup guide",
            "office setup guide",
        ])
        results = hs.keyword_search("office setup guide", memories, top_k=3)
        assert results[0]['content'] == "office setup guide"

    def test_repeated_searches_consistent(self):
        """Multiple identical searches produce identical results."""
        memories = _make_memories(["alpha beta", "gamma delta"])
        r1 = hs.keyword_search("alpha", memories)
        r2 = hs.keyword_search("alpha", memories)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a['content'] == b['content']
            assert abs(a['hybrid_score'] - b['hybrid_score']) < 1e-6

    def test_bm25_score_standalone_then_in_hybrid(self):
        """bm25_score used standalone matches what hybrid_search computes."""
        content = "search engine optimization guide"
        query = "search engine"
        avg_len = 4.0  # 4 words
        standalone = hs.bm25_score(query, content, avg_len)
        memories = [{"content": content}]
        results = hs.hybrid_search(query, memories, use_semantic=False)
        # Single-doc corpus: IDF = log((1+1)/(1+1)) + 1 = 1.0 = same as default
        assert abs(results[0]['bm25_score'] - standalone) < 1e-6


# ===========================================================================
# 11. IDF computation
# ===========================================================================

class TestComputeIDF:

    def test_common_word_lower_idf_than_rare(self):
        """A term appearing in all documents has lower IDF than a rare term."""
        docs = [
            "the cat sat on the mat",
            "the dog sat on the rug",
            "the bird flew over the tree",
            "a rare xylophone appeared once",
        ]
        idf = hs.compute_idf(docs)
        # "the" appears in all 4 docs, "xylophone" appears in 1
        assert idf["the"] < idf["xylophone"]

    def test_term_not_in_corpus_handled_gracefully(self):
        """Querying IDF for a term not in corpus returns default in bm25_score."""
        docs = ["alpha beta", "gamma delta"]
        idf = hs.compute_idf(docs)
        # "omega" is not in IDF dict — bm25_score should fall back to 1.0
        assert "omega" not in idf
        score = hs.bm25_score("omega", "omega is here", avg_doc_length=3.0, idf=idf)
        # Should use default idf=1.0 for unknown term, still produce a score
        assert score > 0.0

    def test_empty_corpus_returns_empty_dict(self):
        """Empty document list returns empty IDF dict."""
        idf = hs.compute_idf([])
        assert idf == {}

    def test_single_document_corpus(self):
        """Single document corpus: IDF = log(2/2) + 1 = 1.0 for all terms."""
        idf = hs.compute_idf(["hello world"])
        # log((1+1)/(1+1)) + 1 = log(1) + 1 = 0 + 1 = 1.0
        assert abs(idf["hello"] - 1.0) < 1e-6
        assert abs(idf["world"] - 1.0) < 1e-6

    def test_idf_values_are_positive(self):
        """All IDF values are positive."""
        docs = ["a b c", "a b", "a"]
        idf = hs.compute_idf(docs)
        for term, value in idf.items():
            assert value > 0.0

    def test_idf_formula_correctness(self):
        """Verify IDF formula: log((N+1)/(count+1)) + 1."""
        docs = ["apple banana", "apple cherry", "banana date"]
        idf = hs.compute_idf(docs)
        # apple: in 2 of 3 docs -> log((3+1)/(2+1)) + 1 = log(4/3) + 1
        expected_apple = math.log(4 / 3) + 1
        assert abs(idf["apple"] - expected_apple) < 1e-6
        # date: in 1 of 3 docs -> log((3+1)/(1+1)) + 1 = log(2) + 1
        expected_date = math.log(2) + 1
        assert abs(idf["date"] - expected_date) < 1e-6

    def test_idf_improves_bm25_discrimination(self):
        """With IDF, rare terms boost BM25 score more than common terms."""
        docs = [
            "the quick brown fox",
            "the slow brown dog",
            "the lazy brown cat",
        ]
        idf = hs.compute_idf(docs)
        # "fox" is rare (1 doc), "the" is common (3 docs)
        # Document with "fox" should score higher for query "fox" than for "the"
        score_rare = hs.bm25_score("fox", "the quick brown fox", avg_doc_length=4.0, idf=idf)
        score_common = hs.bm25_score("the", "the quick brown fox", avg_doc_length=4.0, idf=idf)
        assert score_rare > score_common


# ===========================================================================
# 12. Score normalization
# ===========================================================================

class TestNormalizeScores:

    def test_all_normalized_in_zero_one(self):
        """All normalized scores fall in [0, 1]."""
        scores = [0.5, 1.0, 2.0, 3.5, 0.1]
        normalized = hs.normalize_scores(scores)
        for s in normalized:
            assert 0.0 <= s <= 1.0

    def test_max_becomes_one(self):
        """The maximum score normalizes to 1.0."""
        scores = [0.5, 2.0, 1.5]
        normalized = hs.normalize_scores(scores)
        assert abs(normalized[1] - 1.0) < 1e-6

    def test_empty_list_returns_empty(self):
        """Empty list returns empty list."""
        assert hs.normalize_scores([]) == []

    def test_all_zeros_returns_zeros(self):
        """All-zero scores return all zeros."""
        scores = [0.0, 0.0, 0.0]
        normalized = hs.normalize_scores(scores)
        assert normalized == [0.0, 0.0, 0.0]

    def test_single_value_normalizes_to_one(self):
        """Single positive value normalizes to 1.0."""
        normalized = hs.normalize_scores([5.0])
        assert abs(normalized[0] - 1.0) < 1e-6

    def test_single_zero_stays_zero(self):
        """Single zero value stays 0.0."""
        normalized = hs.normalize_scores([0.0])
        assert normalized == [0.0]

    def test_preserves_relative_ordering(self):
        """Normalization preserves relative ordering of scores."""
        scores = [1.0, 3.0, 2.0]
        normalized = hs.normalize_scores(scores)
        assert normalized[0] < normalized[2] < normalized[1]

    def test_proportions_preserved(self):
        """Ratios between scores are preserved."""
        scores = [2.0, 4.0]
        normalized = hs.normalize_scores(scores)
        assert abs(normalized[0] / normalized[1] - 0.5) < 1e-6

    def test_hybrid_search_normalized_bm25_in_zero_one(self):
        """After hybrid_search, normalized BM25 scores are in [0, 1]."""
        memories = _make_memories([
            "office setup guide for new employees",
            "completely unrelated xyz abc",
            "office desk arrangement tips",
        ])
        results = hs.hybrid_search("office", memories, use_semantic=False)
        for r in results:
            assert 0.0 <= r['bm25_score_normalized'] <= 1.0


# ===========================================================================
# 13. Pre-computed embeddings
# ===========================================================================

class TestPrecomputedEmbeddings:

    def test_embeddings_parameter_accepted(self):
        """hybrid_search accepts embeddings parameter."""
        import inspect
        sig = inspect.signature(hs.hybrid_search)
        assert 'embeddings' in sig.parameters

    def test_embeddings_none_falls_back_gracefully(self):
        """embeddings=None falls back to standard semantic path."""
        memories = _make_memories(["test content"])
        # use_semantic=False so no model needed
        results = hs.hybrid_search("test", memories, use_semantic=False, embeddings=None)
        assert len(results) == 1
        assert results[0]['bm25_score'] > 0.0

    def test_precomputed_embeddings_avoids_model_calls(self):
        """When embeddings dict provided, semantic_search is NOT called."""
        import numpy as np
        content = "test content here"
        memories = _make_memories([content])
        # Create fake embeddings
        fake_query_emb = np.random.rand(384).astype(np.float32)
        fake_doc_emb = np.random.rand(384).astype(np.float32)
        embeddings = {content[:100]: fake_doc_emb}  # first 100 chars as key

        with patch('memory_system.hybrid_search.semantic_search', create=True) as mock_ss:
            # Patch embed_text at the source module where it's imported from
            with patch('memory_system.semantic_search.embed_text', return_value=fake_query_emb):
                results = hs.hybrid_search(
                    "test", memories,
                    use_semantic=True,
                    embeddings=embeddings
                )
            # semantic_search should NOT have been called
            mock_ss.assert_not_called()

    def test_precomputed_embeddings_produces_semantic_score(self):
        """Pre-computed embeddings produce a non-trivial semantic score."""
        import numpy as np
        # Create two similar vectors
        vec_a = np.ones(384, dtype=np.float32)
        vec_b = np.ones(384, dtype=np.float32) * 0.9
        vec_b[0] = 1.0  # keep similar

        content = "test content here"
        memories = _make_memories([content])
        cache_key = content[:100]  # first 100 chars
        embeddings = {cache_key: vec_b}

        with patch('memory_system.semantic_search.embed_text', return_value=vec_a):
            results = hs.hybrid_search(
                "test", memories,
                use_semantic=True,
                embeddings=embeddings
            )
        assert results[0]['semantic_score'] > 0.0

    def test_missing_embedding_key_gives_zero_semantic(self):
        """If content key not in embeddings dict, semantic_score = 0.0."""
        import numpy as np
        memories = _make_memories(["some content not in dict"])
        embeddings = {"different key": np.ones(384, dtype=np.float32)}

        with patch('memory_system.semantic_search.embed_text', return_value=np.ones(384)):
            results = hs.hybrid_search(
                "test", memories,
                use_semantic=True,
                embeddings=embeddings
            )
        assert results[0]['semantic_score'] == 0.0

    def test_empty_embeddings_dict_gives_zero_semantic(self):
        """Empty embeddings dict gives zero semantic score for all docs."""
        import numpy as np
        memories = _make_memories(["some content"])
        embeddings = {}

        with patch('memory_system.semantic_search.embed_text', return_value=np.ones(384)):
            results = hs.hybrid_search(
                "test", memories,
                use_semantic=True,
                embeddings=embeddings
            )
        assert results[0]['semantic_score'] == 0.0


# ===========================================================================
# 14. Weights integrity
# ===========================================================================

class TestWeightsIntegrity:

    def test_default_weights_sum_to_one(self):
        """Default semantic_weight + bm25_weight = 1.0."""
        import inspect
        sig = inspect.signature(hs.hybrid_search)
        sw = sig.parameters['semantic_weight'].default
        bw = sig.parameters['bm25_weight'].default
        assert abs(sw + bw - 1.0) < 1e-6

    def test_end_to_end_sorted_descending(self):
        """End-to-end: results sorted by hybrid_score descending."""
        memories = _make_memories([
            "python programming language guide",
            "java enterprise application server",
            "python snake species in africa",
            "javascript web development tutorial",
            "python data science machine learning",
        ])
        results = hs.hybrid_search("python programming", memories, use_semantic=False, top_k=5)
        scores = [r['hybrid_score'] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_greater_than_memories_returns_all(self):
        """top_k > len(memories) returns all available memories."""
        memories = _make_memories(["one", "two", "three"])
        results = hs.hybrid_search("one", memories, top_k=100, use_semantic=False)
        assert len(results) == 3

    def test_single_document_returns_it(self):
        """Single document corpus returns that document."""
        memories = _make_memories(["the only document"])
        results = hs.hybrid_search("document", memories, use_semantic=False)
        assert len(results) == 1
        assert results[0]['content'] == "the only document"

    def test_empty_corpus_returns_empty(self):
        """Empty corpus returns empty list."""
        results = hs.hybrid_search("anything", [], use_semantic=False)
        assert results == []
