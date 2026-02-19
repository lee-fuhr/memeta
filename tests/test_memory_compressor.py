"""
Tests for memory_compressor — rule-based compression pipeline.

Covers:
    - extract_atomic_facts: splitting, dedup, empty handling
    - compress: filler removal, hedging removal, ratio, token counts
    - compress_batch: batch processing with compressed_content key
    - estimate_tokens: word-to-token approximation
    - get_stats: cumulative statistics tracking
"""

import math
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable directly from this worktree
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memory_compressor import MemoryCompressor


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mc():
    """Fresh compressor instance for each test."""
    return MemoryCompressor()


# ── extract_atomic_facts ────────────────────────────────────────────────────


class TestExtractAtomicFacts:
    def test_splits_on_sentence_boundaries(self, mc):
        text = "First sentence. Second sentence. Third sentence."
        facts = mc.extract_atomic_facts(text)
        assert len(facts) == 3
        assert facts[0] == "First sentence."
        assert facts[1] == "Second sentence."
        assert facts[2] == "Third sentence."

    def test_handles_exclamation_and_question(self, mc):
        text = "This works! Does it? Yes."
        facts = mc.extract_atomic_facts(text)
        assert len(facts) == 3

    def test_empty_string(self, mc):
        assert mc.extract_atomic_facts("") == []

    def test_whitespace_only(self, mc):
        assert mc.extract_atomic_facts("   \n\t  ") == []

    def test_deduplicates_case_insensitive(self, mc):
        text = "The API is broken. The api is broken."
        facts = mc.extract_atomic_facts(text)
        assert len(facts) == 1

    def test_preserves_order(self, mc):
        text = "Alpha. Beta. Gamma."
        facts = mc.extract_atomic_facts(text)
        assert facts == ["Alpha.", "Beta.", "Gamma."]

    def test_single_sentence_no_period(self, mc):
        text = "Just one fact"
        facts = mc.extract_atomic_facts(text)
        assert len(facts) == 1
        assert facts[0] == "Just one fact"


# ── compress ────────────────────────────────────────────────────────────────


class TestCompress:
    def test_removes_filler_basically(self, mc):
        result = mc.compress("The system is basically broken")
        assert "basically" not in result["compressed"].lower()

    def test_removes_filler_essentially(self, mc):
        result = mc.compress("This is essentially a wrapper")
        assert "essentially" not in result["compressed"].lower()

    def test_removes_hedging_i_think(self, mc):
        result = mc.compress("I think the API is broken")
        assert "i think" not in result["compressed"].lower()
        assert "API" in result["compressed"]

    def test_removes_hedging_probably(self, mc):
        result = mc.compress("The bug is probably in the parser")
        assert "probably" not in result["compressed"].lower()
        assert "parser" in result["compressed"]

    def test_removes_hedging_might_be(self, mc):
        result = mc.compress("It might be a race condition")
        assert "might be" not in result["compressed"].lower()

    def test_removes_multiple_fillers(self, mc):
        text = "I think basically the API is essentially really broken"
        result = mc.compress(text)
        compressed = result["compressed"].lower()
        assert "i think" not in compressed
        assert "basically" not in compressed
        assert "essentially" not in compressed
        assert "really" not in compressed

    def test_compression_ratio_decreases(self, mc):
        text = "I think basically essentially the system is actually really very broken"
        result = mc.compress(text)
        assert result["compression_ratio"] < 1.0

    def test_compression_ratio_for_clean_text(self, mc):
        text = "The database uses B-tree indexes for fast lookups."
        result = mc.compress(text)
        # Clean text should have ratio close to 1.0
        assert result["compression_ratio"] >= 0.9

    def test_empty_content(self, mc):
        result = mc.compress("")
        assert result["compressed"] == ""
        assert result["facts"] == []
        assert result["compression_ratio"] == 1.0
        assert result["original_tokens"] == 0
        assert result["compressed_tokens"] == 0

    def test_returns_all_keys(self, mc):
        result = mc.compress("Some content here.")
        assert "compressed" in result
        assert "facts" in result
        assert "compression_ratio" in result
        assert "original_tokens" in result
        assert "compressed_tokens" in result

    def test_token_counts_are_integers(self, mc):
        result = mc.compress("The memory system stores knowledge.")
        assert isinstance(result["original_tokens"], int)
        assert isinstance(result["compressed_tokens"], int)

    def test_compressed_tokens_lte_original(self, mc):
        text = "I believe the system is essentially quite broken and probably needs fixing"
        result = mc.compress(text)
        assert result["compressed_tokens"] <= result["original_tokens"]

    def test_facts_extracted_from_compressed(self, mc):
        text = "I think the API works. It seems like the tests pass."
        result = mc.compress(text)
        # Facts should come from the compressed text, not original
        for fact in result["facts"]:
            assert "i think" not in fact.lower()
            assert "it seems like" not in fact.lower()


# ── compress_batch ──────────────────────────────────────────────────────────


class TestCompressBatch:
    def test_adds_compressed_content_key(self, mc):
        memories = [
            {"id": "1", "content": "I think the API is broken"},
            {"id": "2", "content": "The database is fast"},
        ]
        results = mc.compress_batch(memories)
        assert len(results) == 2
        for r in results:
            assert "compressed_content" in r

    def test_preserves_original_keys(self, mc):
        memories = [{"id": "abc", "content": "Test content", "tags": ["#dev"]}]
        results = mc.compress_batch(memories)
        assert results[0]["id"] == "abc"
        assert results[0]["tags"] == ["#dev"]
        assert results[0]["content"] == "Test content"

    def test_empty_batch(self, mc):
        assert mc.compress_batch([]) == []

    def test_does_not_mutate_input(self, mc):
        original = {"id": "1", "content": "Some text"}
        mc.compress_batch([original])
        assert "compressed_content" not in original

    def test_missing_content_key(self, mc):
        memories = [{"id": "1"}]
        results = mc.compress_batch(memories)
        assert results[0]["compressed_content"]["compressed"] == ""


# ── estimate_tokens ─────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_basic_estimation(self, mc):
        text = "one two three four five"
        # 5 words * 1.3 = 6.5 -> ceil -> 7
        assert mc.estimate_tokens(text) == 7

    def test_single_word(self, mc):
        # 1 * 1.3 = 1.3 -> ceil -> 2
        assert mc.estimate_tokens("hello") == 2

    def test_empty_string(self, mc):
        assert mc.estimate_tokens("") == 0

    def test_whitespace_only(self, mc):
        assert mc.estimate_tokens("   ") == 0

    def test_formula_ceil_word_count_times_1_3(self, mc):
        text = "a b c d e f g h i j"  # 10 words
        expected = math.ceil(10 * 1.3)  # 13
        assert mc.estimate_tokens(text) == expected


# ── get_stats ───────────────────────────────────────────────────────────────


class TestGetStats:
    def test_initial_stats(self, mc):
        stats = mc.get_stats()
        assert stats["total_compressed"] == 0
        assert stats["avg_ratio"] == 0.0
        assert stats["total_tokens_saved"] == 0

    def test_stats_after_single_compress(self, mc):
        mc.compress("I think basically the system works")
        stats = mc.get_stats()
        assert stats["total_compressed"] == 1
        assert stats["total_tokens_saved"] > 0

    def test_stats_accumulate(self, mc):
        mc.compress("I think the first thing is important")
        mc.compress("Basically the second thing matters")
        stats = mc.get_stats()
        assert stats["total_compressed"] == 2

    def test_avg_ratio_between_zero_and_one(self, mc):
        mc.compress("I think basically essentially the API is really very broken")
        stats = mc.get_stats()
        assert 0.0 < stats["avg_ratio"] < 1.0

    def test_stats_returns_all_keys(self, mc):
        stats = mc.get_stats()
        assert "total_compressed" in stats
        assert "avg_ratio" in stats
        assert "total_tokens_saved" in stats
