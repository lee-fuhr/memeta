"""Tests for FSRS context-relevance weighting.

Combines FSRS time-based due score with content-based context relevance.
A memory that's due for review but irrelevant to the current context
should yield to a highly relevant memory that's not quite due.
"""
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory_system.fsrs_context_weighting import (
    FsrsContextWeighter,
    WeightedMemory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_weighter(tmp_path):
    db_path = tmp_path / "fsrs.db"
    return FsrsContextWeighter(db_path=db_path)


def _make_state(memory_id, stability=3.0, due_days_offset=0):
    """Build a mock FSRS state dict."""
    due = (datetime.now(timezone.utc) + timedelta(days=due_days_offset)).isoformat()
    return {
        "memory_id": memory_id,
        "stability": stability,
        "due_date": due,
        "review_count": 5,
    }


def _make_memory(memory_id, content):
    return {"id": memory_id, "content": content}


# ---------------------------------------------------------------------------
# Import + instantiation
# ---------------------------------------------------------------------------

class TestImport:
    def test_imports(self):
        from memory_system.fsrs_context_weighting import FsrsContextWeighter
        assert FsrsContextWeighter is not None

    def test_weighted_memory_importable(self):
        from memory_system.fsrs_context_weighting import WeightedMemory
        assert WeightedMemory is not None

    def test_instantiates(self, tmp_path):
        w = _make_weighter(tmp_path)
        assert w is not None


# ---------------------------------------------------------------------------
# compute_fsrs_score
# ---------------------------------------------------------------------------

class TestComputeFsrsScore:
    def test_returns_float(self, tmp_path):
        w = _make_weighter(tmp_path)
        state = _make_state("m1", stability=3.0, due_days_offset=0)
        score = w.compute_fsrs_score(state)
        assert isinstance(score, float)

    def test_score_between_zero_and_one(self, tmp_path):
        w = _make_weighter(tmp_path)
        for offset in [-7, -3, 0, 3, 10]:
            state = _make_state("m1", due_days_offset=offset)
            score = w.compute_fsrs_score(state)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for offset {offset}"

    def test_overdue_scores_higher_than_not_due(self, tmp_path):
        w = _make_weighter(tmp_path)
        overdue = w.compute_fsrs_score(_make_state("m1", due_days_offset=-5))
        not_due = w.compute_fsrs_score(_make_state("m2", due_days_offset=5))
        assert overdue > not_due

    def test_no_due_date_returns_midrange(self, tmp_path):
        w = _make_weighter(tmp_path)
        state = {"memory_id": "m1", "stability": 3.0, "due_date": None, "review_count": 0}
        score = w.compute_fsrs_score(state)
        assert 0.0 <= score <= 1.0

    def test_high_stability_reduces_urgency_when_not_due(self, tmp_path):
        """High-stability memory that's not due should score lower than low-stability due."""
        w = _make_weighter(tmp_path)
        high_stable_not_due = w.compute_fsrs_score(_make_state("m1", stability=9.0, due_days_offset=10))
        low_stable_due = w.compute_fsrs_score(_make_state("m2", stability=0.5, due_days_offset=-1))
        assert low_stable_due > high_stable_not_due


# ---------------------------------------------------------------------------
# compute_context_score
# ---------------------------------------------------------------------------

class TestComputeContextScore:
    def test_returns_float(self, tmp_path):
        w = _make_weighter(tmp_path)
        score = w.compute_context_score("BM25 search algorithms", "BM25 hybrid search")
        assert isinstance(score, float)

    def test_score_between_zero_and_one(self, tmp_path):
        w = _make_weighter(tmp_path)
        score = w.compute_context_score("completely unrelated content here", "fix a bug")
        assert 0.0 <= score <= 1.0

    def test_identical_content_scores_one(self, tmp_path):
        w = _make_weighter(tmp_path)
        content = "BM25 hybrid search improves memory recall"
        score = w.compute_context_score(content, content)
        assert score == 1.0

    def test_no_overlap_scores_zero(self, tmp_path):
        w = _make_weighter(tmp_path)
        score = w.compute_context_score("cooking dinner recipes pasta", "deploy kubernetes production")
        assert score == 0.0

    def test_partial_overlap_scores_between(self, tmp_path):
        w = _make_weighter(tmp_path)
        score = w.compute_context_score("BM25 search algorithms", "BM25 semantic vector search")
        assert 0.0 < score < 1.0

    def test_empty_content_scores_zero(self, tmp_path):
        w = _make_weighter(tmp_path)
        assert w.compute_context_score("", "fix a bug") == 0.0

    def test_empty_query_scores_zero(self, tmp_path):
        w = _make_weighter(tmp_path)
        assert w.compute_context_score("BM25 search algorithms", "") == 0.0


# ---------------------------------------------------------------------------
# weight_memories
# ---------------------------------------------------------------------------

class TestWeightMemories:
    def test_returns_list(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [_make_memory("m1", "BM25 search")]
        states = {"m1": _make_state("m1")}
        result = w.weight_memories(memories, "search", states)
        assert isinstance(result, list)

    def test_returns_weighted_memory_objects(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [_make_memory("m1", "BM25 search")]
        states = {"m1": _make_state("m1")}
        result = w.weight_memories(memories, "search", states)
        assert all(isinstance(r, WeightedMemory) for r in result)

    def test_sorted_by_combined_score_descending(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [
            _make_memory("m1", "BM25 search algorithms hybrid"),
            _make_memory("m2", "cooking dinner recipes"),
        ]
        states = {
            "m1": _make_state("m1", stability=3.0, due_days_offset=0),
            "m2": _make_state("m2", stability=3.0, due_days_offset=0),
        }
        result = w.weight_memories(memories, "BM25 search", states)
        scores = [r.combined_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_relevant_memory_beats_irrelevant_due_memory(self, tmp_path):
        """A highly relevant but not-quite-due memory should beat an irrelevant overdue one."""
        w = _make_weighter(tmp_path)
        memories = [
            _make_memory("relevant", "BM25 hybrid search memory recall algorithms"),
            _make_memory("overdue", "cooking pasta dinner recipes Italian"),
        ]
        states = {
            "relevant": _make_state("relevant", stability=3.0, due_days_offset=2),  # not yet due
            "overdue": _make_state("overdue", stability=3.0, due_days_offset=-10),  # very overdue
        }
        result = w.weight_memories(memories, "BM25 search recall", states)
        # With high context weighting, relevant should win
        top = result[0]
        assert top.memory_id == "relevant"

    def test_empty_memories_returns_empty(self, tmp_path):
        w = _make_weighter(tmp_path)
        assert w.weight_memories([], "query", {}) == []

    def test_memory_without_state_uses_neutral_fsrs_score(self, tmp_path):
        """Memories with no FSRS state should still be scored (neutral FSRS)."""
        w = _make_weighter(tmp_path)
        memories = [_make_memory("m1", "BM25 search")]
        result = w.weight_memories(memories, "BM25 search", states={})
        assert len(result) == 1

    def test_weighted_memory_has_required_fields(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [_make_memory("m1", "BM25 search")]
        states = {"m1": _make_state("m1")}
        result = w.weight_memories(memories, "BM25", states)
        wm = result[0]
        assert hasattr(wm, "memory_id")
        assert hasattr(wm, "fsrs_score")
        assert hasattr(wm, "context_score")
        assert hasattr(wm, "combined_score")
        assert hasattr(wm, "memory")

    def test_respects_top_k(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [_make_memory(f"m{i}", f"memory content {i}") for i in range(10)]
        states = {f"m{i}": _make_state(f"m{i}") for i in range(10)}
        result = w.weight_memories(memories, "memory content", states, top_k=3)
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# Custom weights
# ---------------------------------------------------------------------------

class TestCustomWeights:
    def test_accepts_custom_weights(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [_make_memory("m1", "BM25 search")]
        states = {"m1": _make_state("m1")}
        # 100% FSRS, 0% context
        result = w.weight_memories(memories, "unrelated", states, weights=(1.0, 0.0))
        assert len(result) == 1
        # combined_score should equal fsrs_score
        wm = result[0]
        assert abs(wm.combined_score - wm.fsrs_score) < 0.001

    def test_zero_fsrs_weight_ignores_due_date(self, tmp_path):
        w = _make_weighter(tmp_path)
        memories = [
            _make_memory("relevant", "BM25 hybrid search algorithms"),
            _make_memory("overdue", "completely unrelated topic"),
        ]
        states = {
            "relevant": _make_state("relevant", due_days_offset=10),
            "overdue": _make_state("overdue", due_days_offset=-30),
        }
        result = w.weight_memories(
            memories, "BM25 search", states, weights=(0.0, 1.0)
        )
        assert result[0].memory_id == "relevant"
