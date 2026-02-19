"""
Tests for relevance_explanation.py - Human-readable search result explanations.

Covers:
1. explain_relevance with high semantic score
2. explain_relevance with high BM25 / keyword overlap
3. get_matching_keywords finds common words
4. get_matching_keywords skips stopwords
5. get_matching_keywords is case-insensitive
6. add_explanations_to_results adds 'explanation' to each dict
7. Explanation for high-confidence memory mentions confidence
8. Explanation for low-confidence memory doesn't overstate
9. Empty query produces graceful explanation
10. Memory with no tags: explanation still works (no crash)
11. Integration with hybrid_search (explanation field present)
12. Edge cases (empty content, no scores, etc.)
"""

import pytest

from memory_system.relevance_explanation import (
    explain_relevance,
    get_matching_keywords,
    add_explanations_to_results,
    STOPWORDS,
)


# ---------------------------------------------------------------------------
# 1. explain_relevance - high semantic score
# ---------------------------------------------------------------------------

class TestExplainRelevanceSemanticScore:

    def test_high_semantic_score_mentions_strong(self):
        """High semantic score (>0.8) mentions 'Strong' or percentage."""
        scores = {'semantic_score': 0.87, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'dark mode preferences'}
        result = explain_relevance('dark mode', memory, scores)
        assert 'Strong' in result or '87%' in result

    def test_high_semantic_score_includes_percentage(self):
        """High semantic score includes percentage value."""
        scores = {'semantic_score': 0.92, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'something'}
        result = explain_relevance('query', memory, scores)
        assert '92%' in result

    def test_medium_semantic_score_shows_percentage(self):
        """Medium semantic score (0.5-0.8) shows percentage without 'Strong'."""
        scores = {'semantic_score': 0.65, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'some content'}
        result = explain_relevance('query', memory, scores)
        assert '65%' in result
        assert 'Strong' not in result

    def test_low_semantic_score_shows_weak(self):
        """Low semantic score (>0 but <0.5) shows 'Weak'."""
        scores = {'semantic_score': 0.25, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'some content'}
        result = explain_relevance('query', memory, scores)
        assert 'Weak' in result or '25%' in result


# ---------------------------------------------------------------------------
# 2. explain_relevance - high BM25 / keyword overlap
# ---------------------------------------------------------------------------

class TestExplainRelevanceBM25:

    def test_high_bm25_mentions_strong_keyword_overlap(self):
        """High BM25 normalized score (>0.7) mentions 'Strong keyword overlap'."""
        scores = {'semantic_score': 0, 'bm25_score': 3.5, 'bm25_score_normalized': 0.85}
        memory = {'content': 'dark mode settings for the application'}
        result = explain_relevance('dark mode', memory, scores)
        assert 'Strong keyword overlap' in result

    def test_moderate_bm25_mentions_keywords(self):
        """Moderate BM25 with matching keywords lists them."""
        scores = {'semantic_score': 0, 'bm25_score': 1.5, 'bm25_score_normalized': 0.5}
        memory = {'content': 'dark mode settings'}
        result = explain_relevance('dark mode', memory, scores)
        assert 'Keywords' in result or 'dark' in result

    def test_keywords_listed_in_explanation(self):
        """Matching keywords appear in the explanation text."""
        scores = {'semantic_score': 0, 'bm25_score': 2.0, 'bm25_score_normalized': 0.9}
        memory = {'content': 'configure dark mode theme settings'}
        result = explain_relevance('dark mode', memory, scores)
        assert 'dark' in result
        assert 'mode' in result


# ---------------------------------------------------------------------------
# 3. get_matching_keywords - common words
# ---------------------------------------------------------------------------

class TestGetMatchingKeywords:

    def test_finds_common_words(self):
        """Finds words that appear in both query and content."""
        result = get_matching_keywords('dark mode settings', 'enable dark mode in app')
        assert 'dark' in result
        assert 'mode' in result

    def test_no_overlap_returns_empty(self):
        """No overlapping words returns empty list."""
        result = get_matching_keywords('alpha beta', 'gamma delta')
        assert result == []

    def test_single_match(self):
        """Single matching word is found."""
        result = get_matching_keywords('python', 'learn python programming')
        assert result == ['python']


# ---------------------------------------------------------------------------
# 4. get_matching_keywords - stopwords
# ---------------------------------------------------------------------------

class TestGetMatchingKeywordsStopwords:

    def test_skips_stopwords(self):
        """Stopwords like 'the', 'a', 'is' are not included."""
        result = get_matching_keywords('the dark is here', 'the dark side is strong')
        assert 'the' not in result
        assert 'is' not in result
        assert 'dark' in result

    def test_all_stopwords_returns_empty(self):
        """Query of only stopwords returns empty list."""
        result = get_matching_keywords('the a is are', 'the a is are but')
        assert result == []

    def test_stopwords_constant_has_common_words(self):
        """STOPWORDS set contains expected common words."""
        assert 'the' in STOPWORDS
        assert 'a' in STOPWORDS
        assert 'is' in STOPWORDS
        assert 'and' in STOPWORDS
        assert 'of' in STOPWORDS


# ---------------------------------------------------------------------------
# 5. get_matching_keywords - case insensitive
# ---------------------------------------------------------------------------

class TestGetMatchingKeywordsCaseInsensitive:

    def test_case_insensitive_matching(self):
        """Matching is case-insensitive."""
        result = get_matching_keywords('Dark Mode', 'dark mode settings')
        assert 'dark' in result
        assert 'mode' in result

    def test_mixed_case_content(self):
        """Mixed case in content still matches."""
        result = get_matching_keywords('python', 'Learn PYTHON Programming')
        assert 'python' in result

    def test_uppercase_query(self):
        """All uppercase query matches lowercase content."""
        result = get_matching_keywords('OFFICE SETUP', 'office setup guide')
        assert 'office' in result
        assert 'setup' in result


# ---------------------------------------------------------------------------
# 6. add_explanations_to_results
# ---------------------------------------------------------------------------

class TestAddExplanationsToResults:

    def test_adds_explanation_field(self):
        """Adds 'explanation' field to each result dict."""
        results = [
            {'content': 'dark mode', 'semantic_score': 0.8, 'bm25_score': 1.0,
             'bm25_score_normalized': 0.5},
            {'content': 'light mode', 'semantic_score': 0.3, 'bm25_score': 0.5,
             'bm25_score_normalized': 0.2},
        ]
        updated = add_explanations_to_results('dark mode', results)
        assert all('explanation' in r for r in updated)

    def test_modifies_in_place(self):
        """Modifies results in place (same objects)."""
        results = [
            {'content': 'test', 'semantic_score': 0.5, 'bm25_score': 1.0,
             'bm25_score_normalized': 0.5},
        ]
        original_id = id(results[0])
        add_explanations_to_results('test', results)
        assert id(results[0]) == original_id

    def test_returns_same_list(self):
        """Returns the same list object."""
        results = [{'content': 'test', 'semantic_score': 0, 'bm25_score': 0,
                     'bm25_score_normalized': 0}]
        returned = add_explanations_to_results('test', results)
        assert returned is results

    def test_empty_results_list(self):
        """Empty results list returns empty list without error."""
        result = add_explanations_to_results('query', [])
        assert result == []

    def test_explanation_is_string(self):
        """Explanation field is always a string."""
        results = [{'content': 'test', 'semantic_score': 0.5, 'bm25_score': 1.0,
                     'bm25_score_normalized': 0.5}]
        add_explanations_to_results('test', results)
        assert isinstance(results[0]['explanation'], str)


# ---------------------------------------------------------------------------
# 7. High-confidence memory
# ---------------------------------------------------------------------------

class TestHighConfidenceExplanation:

    def test_high_confidence_mentioned(self):
        """High confidence memory mentions confidence in explanation."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test data', 'confidence_score': 0.85, 'confirmations': 3}
        result = explain_relevance('test', memory, scores)
        assert 'confidence' in result.lower()

    def test_confirmations_count_shown(self):
        """Confirmation count is shown for high-confidence memories."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test data', 'confidence_score': 0.85, 'confirmations': 3}
        result = explain_relevance('test', memory, scores)
        assert '3x' in result or 'confirmed 3' in result

    def test_very_high_confidence(self):
        """Very high confidence (>=0.9) is reflected in explanation."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test', 'confidence_score': 0.95, 'confirmations': 5}
        result = explain_relevance('test', memory, scores)
        assert 'confidence' in result.lower()


# ---------------------------------------------------------------------------
# 8. Low-confidence memory - doesn't overstate
# ---------------------------------------------------------------------------

class TestLowConfidenceExplanation:

    def test_medium_confidence_not_overstated(self):
        """Medium confidence (0.5) does not overstate reliability."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test data', 'confidence_score': 0.5, 'confirmations': 0}
        result = explain_relevance('test', memory, scores)
        # Should NOT say "High confidence" for medium confidence
        assert 'High confidence' not in result
        assert 'Very high confidence' not in result

    def test_low_confidence_not_called_high(self):
        """Low confidence memory is not described as high confidence."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test data', 'confidence_score': 0.25}
        result = explain_relevance('test', memory, scores)
        assert 'High' not in result


# ---------------------------------------------------------------------------
# 9. Empty query
# ---------------------------------------------------------------------------

class TestEmptyQuery:

    def test_empty_query_no_crash(self):
        """Empty query produces a graceful explanation without crashing."""
        scores = {'semantic_score': 0, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'some stored memory'}
        result = explain_relevance('', memory, scores)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_query_says_weak_or_partial(self):
        """Empty query with zero scores says 'Weak match' or 'Partial match'."""
        scores = {'semantic_score': 0, 'bm25_score': 0, 'bm25_score_normalized': 0}
        memory = {'content': 'some stored memory'}
        result = explain_relevance('', memory, scores)
        assert 'match' in result.lower()


# ---------------------------------------------------------------------------
# 10. Memory with no tags
# ---------------------------------------------------------------------------

class TestNoTags:

    def test_no_tags_no_crash(self):
        """Memory without 'semantic_tags' key does not crash."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test content'}
        result = explain_relevance('test', memory, scores)
        assert isinstance(result, str)

    def test_empty_tags_list_no_crash(self):
        """Memory with empty tags list does not crash."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test content', 'semantic_tags': []}
        result = explain_relevance('test', memory, scores)
        assert isinstance(result, str)

    def test_none_tags_no_crash(self):
        """Memory with tags=None does not crash."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test content', 'semantic_tags': None}
        result = explain_relevance('test', memory, scores)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 11. Tag relevance in explanation
# ---------------------------------------------------------------------------

class TestTagRelevance:

    def test_matching_tags_shown(self):
        """Tags matching query words appear in explanation."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'user preference', 'semantic_tags': ['preference', 'settings']}
        result = explain_relevance('preference settings', memory, scores)
        assert '#preference' in result or '#settings' in result

    def test_non_matching_tags_not_shown(self):
        """Tags not matching query are not listed."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test data', 'semantic_tags': ['unrelated-tag']}
        result = explain_relevance('test', memory, scores)
        assert '#unrelated-tag' not in result


# ---------------------------------------------------------------------------
# 12. Integration with hybrid_search
# ---------------------------------------------------------------------------

class TestHybridSearchIntegration:

    def test_hybrid_search_results_have_explanation(self):
        """hybrid_search results include 'explanation' field."""
        from memory_system.hybrid_search import hybrid_search
        memories = [{'content': 'dark mode user preference'}]
        results = hybrid_search('dark mode', memories, use_semantic=False)
        assert len(results) == 1
        assert 'explanation' in results[0]
        assert isinstance(results[0]['explanation'], str)

    def test_keyword_search_results_have_explanation(self):
        """keyword_search results also include 'explanation' field."""
        from memory_system.hybrid_search import keyword_search
        memories = [{'content': 'office setup guide'}]
        results = keyword_search('office', memories)
        assert len(results) == 1
        assert 'explanation' in results[0]

    def test_empty_search_returns_empty(self):
        """Empty memories list still works with explanation integration."""
        from memory_system.hybrid_search import hybrid_search
        results = hybrid_search('query', [], use_semantic=False)
        assert results == []


# ---------------------------------------------------------------------------
# 13. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_get_matching_keywords_empty_query(self):
        """Empty query returns empty keyword list."""
        result = get_matching_keywords('', 'some content here')
        assert result == []

    def test_get_matching_keywords_empty_content(self):
        """Empty content returns empty keyword list."""
        result = get_matching_keywords('dark mode', '')
        assert result == []

    def test_get_matching_keywords_both_empty(self):
        """Both empty returns empty keyword list."""
        result = get_matching_keywords('', '')
        assert result == []

    def test_explain_relevance_missing_scores(self):
        """Missing score keys default to 0 gracefully."""
        result = explain_relevance('test', {'content': 'test'}, {})
        assert isinstance(result, str)

    def test_explain_relevance_no_content_key(self):
        """Memory with no 'content' key does not crash."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        result = explain_relevance('test', {}, scores)
        assert isinstance(result, str)

    def test_explanation_ends_with_period(self):
        """All explanations end with a period."""
        scores = {'semantic_score': 0.87, 'bm25_score': 2.0, 'bm25_score_normalized': 0.9}
        memory = {'content': 'dark mode settings', 'confidence_score': 0.85, 'confirmations': 2}
        result = explain_relevance('dark mode', memory, scores)
        assert result.endswith('.')

    def test_deduplicates_keywords(self):
        """Duplicate query words do not produce duplicate keyword matches."""
        result = get_matching_keywords('dark dark dark', 'dark mode settings')
        assert result.count('dark') == 1

    def test_string_tags_handled(self):
        """Tags stored as comma-separated string are handled."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test', 'semantic_tags': 'preference, settings, dark'}
        result = explain_relevance('dark settings', memory, scores)
        assert isinstance(result, str)

    def test_confirmations_none_handled(self):
        """confirmations=None does not crash."""
        scores = {'semantic_score': 0.5, 'bm25_score': 1.0, 'bm25_score_normalized': 0.5}
        memory = {'content': 'test', 'confidence_score': 0.85, 'confirmations': None}
        result = explain_relevance('test', memory, scores)
        assert isinstance(result, str)
