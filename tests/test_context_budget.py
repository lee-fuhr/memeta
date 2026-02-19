"""
Tests for the context budget optimizer.

Covers:
- Token estimation (normal, empty, whitespace)
- Memory scoring (full fields, partial fields, missing fields, defaults)
- Recency decay (today, old, future, missing)
- Access frequency normalisation
- Greedy packing (fits, overflow, exact budget)
- Edge cases (empty list, zero budget)
- Stats accumulation across calls
- Score ordering (highest score selected first)
- Explanation string content
"""

import math
from datetime import datetime, timedelta

import pytest

from memory_system.context_budget import ContextBudgetOptimizer, SCORE_WEIGHTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(
    content: str = "some test content here",
    importance: float | None = None,
    confidence: float | None = None,
    access_count: int | None = None,
    created: str | None = None,
    updated: str | None = None,
    **extra,
) -> dict:
    """Build a minimal memory dict for testing."""
    mem: dict = {"content": content}
    if importance is not None:
        mem["importance"] = importance
    if confidence is not None:
        mem["confidence"] = confidence
    if access_count is not None:
        mem["access_count"] = access_count
    if created is not None:
        mem["created"] = created
    if updated is not None:
        mem["updated"] = updated
    mem.update(extra)
    return mem


@pytest.fixture
def optimizer():
    return ContextBudgetOptimizer()


# ---------------------------------------------------------------------------
# 1. Token estimation
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_normal_text(self):
        text = "hello world foo bar"
        expected = math.ceil(4 * 1.3)  # 6
        assert ContextBudgetOptimizer.estimate_tokens(text) == expected

    def test_empty_string(self):
        assert ContextBudgetOptimizer.estimate_tokens("") == 0

    def test_whitespace_only(self):
        assert ContextBudgetOptimizer.estimate_tokens("   \n\t  ") == 0

    def test_single_word(self):
        assert ContextBudgetOptimizer.estimate_tokens("hello") == math.ceil(1 * 1.3)  # 2

    def test_long_text(self):
        words = ["word"] * 100
        text = " ".join(words)
        assert ContextBudgetOptimizer.estimate_tokens(text) == math.ceil(100 * 1.3)


# ---------------------------------------------------------------------------
# 2. Memory scoring — field extraction and defaults
# ---------------------------------------------------------------------------

class TestScoreMemory:
    def test_all_fields_present(self, optimizer):
        mem = _make_memory(
            importance=0.8,
            confidence=0.9,
            access_count=5,
            updated=datetime.now().isoformat(),
        )
        score = optimizer.score_memory(mem)
        # importance: 0.4*0.8 = 0.32
        # recency: 0.3*~1.0 ≈ 0.30
        # access_freq: 0.2*0.5 = 0.10
        # confidence: 0.1*0.9 = 0.09
        assert 0.7 < score < 0.85

    def test_all_defaults_when_empty(self, optimizer):
        """Empty dict (no fields) should use 0.5 defaults everywhere."""
        score = optimizer.score_memory({})
        expected = (
            0.4 * 0.5  # importance default
            + 0.3 * 0.5  # recency default
            + 0.2 * 0.5  # access_freq default
            + 0.1 * 0.5  # confidence default
        )
        assert score == pytest.approx(expected)

    def test_importance_score_alias(self, optimizer):
        """importance_score should be used if importance is absent."""
        mem = _make_memory(importance_score=0.9)
        # importance_score not set via helper kwarg, so use extra
        mem2 = {"content": "test", "importance_score": 0.9}
        score = optimizer.score_memory(mem2)
        # importance component = 0.4 * 0.9 = 0.36
        # rest defaults to 0.5
        expected_rest = 0.3 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(0.36 + expected_rest)

    def test_confidence_score_alias(self, optimizer):
        mem = {"content": "test", "confidence_score": 0.7}
        score = optimizer.score_memory(mem)
        # confidence component = 0.1 * 0.7 = 0.07
        expected = 0.4 * 0.5 + 0.3 * 0.5 + 0.2 * 0.5 + 0.1 * 0.7
        assert score == pytest.approx(expected)

    def test_high_access_count_caps_at_one(self, optimizer):
        mem = _make_memory(access_count=100)
        score = optimizer.score_memory(mem)
        # access_freq = min(100/10, 1.0) = 1.0 -> component = 0.2
        component = 0.2 * 1.0
        # other defaults
        rest = 0.4 * 0.5 + 0.3 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(component + rest)


# ---------------------------------------------------------------------------
# 3. Recency scoring
# ---------------------------------------------------------------------------

class TestRecency:
    def test_today_is_one(self, optimizer):
        mem = _make_memory(updated=datetime.now().isoformat())
        score = optimizer.score_memory(mem)
        # recency component should be ~0.3 * 1.0
        # importance/access/confidence default 0.5
        rest = 0.4 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(0.3 * 1.0 + rest, abs=0.01)

    def test_90_days_ago_is_zero(self, optimizer):
        old_date = (datetime.now() - timedelta(days=90)).isoformat()
        mem = _make_memory(updated=old_date)
        score = optimizer.score_memory(mem)
        rest = 0.4 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(0.3 * 0.0 + rest, abs=0.01)

    def test_45_days_half(self, optimizer):
        mid_date = (datetime.now() - timedelta(days=45)).isoformat()
        mem = _make_memory(updated=mid_date)
        score = optimizer.score_memory(mem)
        expected_recency = 1.0 - 45.0 / 90.0  # 0.5
        rest = 0.4 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(0.3 * expected_recency + rest, abs=0.02)

    def test_future_date_clamps_to_one(self, optimizer):
        future = (datetime.now() + timedelta(days=10)).isoformat()
        mem = _make_memory(updated=future)
        score = optimizer.score_memory(mem)
        rest = 0.4 * 0.5 + 0.2 * 0.5 + 0.1 * 0.5
        assert score == pytest.approx(0.3 * 1.0 + rest, abs=0.01)


# ---------------------------------------------------------------------------
# 4. Optimize — greedy packing
# ---------------------------------------------------------------------------

class TestOptimize:
    def test_all_fit(self, optimizer):
        memories = [
            _make_memory(content="a b c", importance=0.9),
            _make_memory(content="d e f", importance=0.5),
        ]
        result = optimizer.optimize(memories, budget_tokens=100)
        assert len(result["selected"]) == 2
        assert len(result["excluded"]) == 0
        assert result["total_tokens"] > 0
        assert 0 < result["budget_used_pct"] <= 100.0

    def test_overflow_excludes_lowest(self, optimizer):
        # Two memories, budget only fits one
        high = _make_memory(content="word " * 10, importance=0.9)
        low = _make_memory(content="word " * 10, importance=0.1)
        # Each ~13 tokens, budget = 15
        result = optimizer.optimize([low, high], budget_tokens=15)
        assert len(result["selected"]) == 1
        assert len(result["excluded"]) == 1
        # Selected should be the higher-scored one
        assert result["selected"][0]["importance"] == 0.9

    def test_exact_budget(self, optimizer):
        mem = _make_memory(content="a b c")  # 3 words -> ceil(3*1.3) = 4 tokens
        result = optimizer.optimize([mem], budget_tokens=4)
        assert len(result["selected"]) == 1
        assert result["total_tokens"] == 4

    def test_empty_memories(self, optimizer):
        result = optimizer.optimize([], budget_tokens=100)
        assert result["selected"] == []
        assert result["excluded"] == []
        assert result["total_tokens"] == 0
        assert result["budget_used_pct"] == 0.0

    def test_zero_budget(self, optimizer):
        memories = [_make_memory(content="hello world", importance=1.0)]
        result = optimizer.optimize(memories, budget_tokens=0)
        assert len(result["selected"]) == 0
        assert len(result["excluded"]) == 1
        assert result["total_tokens"] == 0

    def test_selected_entries_have_score_and_tokens(self, optimizer):
        mem = _make_memory(content="test data here", importance=0.7)
        result = optimizer.optimize([mem], budget_tokens=1000)
        entry = result["selected"][0]
        assert "score" in entry
        assert "tokens" in entry
        assert isinstance(entry["score"], float)
        assert isinstance(entry["tokens"], int)


# ---------------------------------------------------------------------------
# 5. Stats accumulation
# ---------------------------------------------------------------------------

class TestStats:
    def test_initial_stats(self, optimizer):
        stats = optimizer.get_stats()
        assert stats["optimizations"] == 0
        assert stats["total_selected"] == 0
        assert stats["total_excluded"] == 0

    def test_stats_accumulate(self, optimizer):
        mems = [_make_memory(content="word " * 10, importance=0.5)]
        optimizer.optimize(mems, budget_tokens=1000)
        optimizer.optimize(mems, budget_tokens=1000)
        stats = optimizer.get_stats()
        assert stats["optimizations"] == 2
        assert stats["total_selected"] == 2
        assert stats["total_excluded"] == 0

    def test_stats_count_excluded(self, optimizer):
        mems = [_make_memory(content="word " * 50, importance=0.5)]
        optimizer.optimize(mems, budget_tokens=1)  # won't fit
        stats = optimizer.get_stats()
        assert stats["total_excluded"] == 1
        assert stats["total_selected"] == 0


# ---------------------------------------------------------------------------
# 6. Explanation string
# ---------------------------------------------------------------------------

class TestExplanation:
    def test_explanation_contains_counts(self, optimizer):
        mems = [_make_memory(content="a b c")]
        result = optimizer.optimize(mems, budget_tokens=1000)
        assert "1 of 1" in result["explanation"]

    def test_explanation_zero_budget(self, optimizer):
        mems = [_make_memory(content="a b c")]
        result = optimizer.optimize(mems, budget_tokens=0)
        assert "zero" in result["explanation"].lower() or "excluded" in result["explanation"].lower()


# ---------------------------------------------------------------------------
# 7. Weight configuration
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(SCORE_WEIGHTS.values())
        assert total == pytest.approx(1.0)
