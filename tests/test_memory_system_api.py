"""
Tests for the unified MemorySystem API (src/api.py).

Covers:
- save() basics, session_id, contradiction check toggle
- search() ranking, empty results, top_k
- get_recent() ordering and boundary
- get_stats() completeness
- run_maintenance() result shape
- Integration: save-then-search, multiple-save ordering
"""

import sys
import os
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional
from unittest.mock import patch, MagicMock

# Ensure this worktree's src/ is used for memory_system imports,
# regardless of which editable install is active.
_THIS_DIR = Path(__file__).resolve().parent
_SRC_DIR = str(_THIS_DIR.parent / "src")
# Remove any stale memory_system entries so our path wins
for key in list(sys.modules.keys()):
    if key == "memory_system" or key.startswith("memory_system."):
        del sys.modules[key]
sys.path.insert(0, str(_THIS_DIR.parent))
# Register memory_system as a package alias for src/
import importlib
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "memory_system", os.path.join(_SRC_DIR, "__init__.py"),
    submodule_search_locations=[_SRC_DIR],
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["memory_system"] = _mod
_spec.loader.exec_module(_mod)

import pytest

from memory_system.api import MemorySystem


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create an isolated temporary memory directory."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def ms(tmp_memory_dir):
    """Create a MemorySystem instance with isolated temp dir."""
    return MemorySystem(memory_dir=tmp_memory_dir, project_id="test-project")


# ── save() tests ──────────────────────────────────────────────────────────


class TestSave:

    def test_save_creates_memory_and_returns_memory_object(self, ms):
        """save() creates a memory file and returns a Memory object."""
        memory = ms.save(
            "prefers dark mode",
            tags=["#pref"],
            importance=0.8,
            check_contradictions=False,
        )

        assert memory.content == "prefers dark mode"
        assert memory.importance == 0.8
        assert "#pref" in memory.tags
        assert memory.project_id == "test-project"
        assert memory.id  # non-empty

    def test_save_with_session_id_sets_source_session_id(self, ms):
        """save() with session_id populates source_session_id."""
        memory = ms.save(
            "session context test",
            session_id="sess-abc-123",
            check_contradictions=False,
        )

        assert memory.source_session_id == "sess-abc-123"

    def test_save_without_session_id_has_none_source(self, ms):
        """save() without session_id leaves source_session_id as None."""
        memory = ms.save(
            "no session",
            check_contradictions=False,
        )

        assert memory.source_session_id is None

    def test_save_with_contradiction_check_calls_detector(self, ms):
        """save() with check_contradictions=True invokes contradiction detector."""
        # Seed an existing memory so there's something to check against
        ms.save("old fact", check_contradictions=False, importance=0.5)

        with patch("memory_system.api.MemorySystem.save.__module__"):
            # We patch at the import target inside api.py
            pass

        # Use a mock for the detector
        mock_result = MagicMock()
        mock_result.contradicts = False
        mock_result.action = "save"

        with patch(
            "memory_system.contradiction_detector.check_contradictions",
            return_value=mock_result,
        ) as mock_check:
            memory = ms.save(
                "new fact",
                importance=0.6,
                check_contradictions=True,
            )

            mock_check.assert_called_once()
            assert memory.content == "new fact"

    def test_save_with_contradiction_check_false_skips_detector(self, ms):
        """save() with check_contradictions=False never calls detector."""
        with patch(
            "memory_system.contradiction_detector.check_contradictions",
        ) as mock_check:
            ms.save(
                "skip check",
                importance=0.5,
                check_contradictions=False,
            )

            mock_check.assert_not_called()

    def test_save_default_tags_and_importance(self, ms):
        """save() with no tags/importance uses defaults."""
        memory = ms.save(
            "default values test",
            check_contradictions=False,
        )

        assert isinstance(memory.tags, list)
        assert isinstance(memory.importance, float)
        assert 0.0 <= memory.importance <= 1.0

    def test_save_with_custom_project_id(self, ms):
        """save() with explicit project_id overrides the instance default."""
        memory = ms.save(
            "custom project",
            project_id="other-project",
            check_contradictions=False,
        )

        assert memory.project_id == "other-project"

    def test_save_contradiction_replace_archives_old(self, ms):
        """When contradiction detector returns action='replace', old memory is archived."""
        old = ms.save("prefer mornings", importance=0.7, check_contradictions=False)

        mock_result = MagicMock()
        mock_result.contradicts = True
        mock_result.action = "replace"
        mock_result.contradicted_memory = {"id": old.id, "content": old.content}

        with patch(
            "memory_system.contradiction_detector.check_contradictions",
            return_value=mock_result,
        ):
            new = ms.save("prefer afternoons", importance=0.7, check_contradictions=True)

        assert new.content == "prefer afternoons"

        # Old memory should no longer appear in active list
        active_ids = [m.id for m in ms.client.list()]
        assert old.id not in active_ids


# ── search() tests ────────────────────────────────────────────────────────


class TestSearch:

    def test_search_returns_results_ranked_by_score(self, ms):
        """search() returns results sorted by hybrid_score descending."""
        ms.save("python is great for scripting", importance=0.8, check_contradictions=False)
        ms.save("javascript for frontend", importance=0.7, check_contradictions=False)
        ms.save("python data analysis", importance=0.6, check_contradictions=False)

        results = ms.search("python scripting")

        assert len(results) > 0
        # Scores should be descending
        scores = [r["hybrid_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_no_matches_returns_empty(self, ms):
        """search() returns empty list when no memories exist."""
        results = ms.search("nonexistent topic")
        assert results == []

    def test_search_top_k_limits_results(self, ms):
        """search() respects top_k limit."""
        for i in range(5):
            ms.save(f"memory about topic {i}", importance=0.5, check_contradictions=False)

        results = ms.search("topic", top_k=2)
        assert len(results) <= 2


# ── get_recent() tests ────────────────────────────────────────────────────


class TestGetRecent:

    def test_get_recent_sorted_by_date_descending(self, ms):
        """get_recent() returns memories newest-first."""
        m1 = ms.save("first memory", importance=0.5, check_contradictions=False)
        time.sleep(0.01)  # Ensure distinct timestamps
        m2 = ms.save("second memory", importance=0.5, check_contradictions=False)
        time.sleep(0.01)
        m3 = ms.save("third memory", importance=0.5, check_contradictions=False)

        recent = ms.get_recent(n=3)

        assert len(recent) == 3
        assert recent[0].content == "third memory"
        assert recent[1].content == "second memory"
        assert recent[2].content == "first memory"

    def test_get_recent_with_n_greater_than_total(self, ms):
        """get_recent() with n > total returns all available."""
        ms.save("only one", importance=0.5, check_contradictions=False)

        recent = ms.get_recent(n=100)
        assert len(recent) == 1


# ── get_stats() tests ─────────────────────────────────────────────────────


class TestGetStats:

    def test_get_stats_includes_total_memories(self, ms):
        """get_stats() reports correct total_memories count."""
        ms.save("stat test 1", importance=0.5, check_contradictions=False)
        ms.save("stat test 2", importance=0.7, check_contradictions=False)

        stats = ms.get_stats()
        assert stats["total_memories"] == 2

    def test_get_stats_includes_avg_importance(self, ms):
        """get_stats() calculates average importance correctly."""
        ms.save("imp 0.4", importance=0.4, check_contradictions=False)
        ms.save("imp 0.8", importance=0.8, check_contradictions=False)

        stats = ms.get_stats()
        assert abs(stats["avg_importance"] - 0.6) < 0.01

    def test_get_stats_includes_confidence_distribution(self, ms):
        """get_stats() includes confidence_distribution from scoring module."""
        ms.save("conf test", importance=0.5, check_contradictions=False)

        stats = ms.get_stats()
        assert "confidence_distribution" in stats
        assert "total" in stats["confidence_distribution"]

    def test_get_stats_includes_tag_counts(self, ms):
        """get_stats() counts tags across all memories."""
        ms.save("tagged 1", tags=["#pref", "#ui"], importance=0.5, check_contradictions=False)
        ms.save("tagged 2", tags=["#pref"], importance=0.5, check_contradictions=False)

        stats = ms.get_stats()
        assert stats["tag_counts"]["#pref"] == 2
        assert stats["tag_counts"]["#ui"] == 1

    def test_get_stats_includes_project_counts(self, ms):
        """get_stats() counts memories per project."""
        ms.save("proj a", project_id="alpha", importance=0.5, check_contradictions=False)
        ms.save("proj b", project_id="alpha", importance=0.5, check_contradictions=False)
        ms.save("proj c", project_id="beta", importance=0.5, check_contradictions=False)

        stats = ms.get_stats()
        assert stats["project_counts"]["alpha"] == 2
        assert stats["project_counts"]["beta"] == 1

    def test_get_stats_empty_system(self, ms):
        """get_stats() on empty system returns zeroed stats."""
        stats = ms.get_stats()
        assert stats["total_memories"] == 0
        assert stats["avg_importance"] == 0.0


# ── run_maintenance() tests ───────────────────────────────────────────────


class TestRunMaintenance:

    def test_run_maintenance_returns_result_dict(self, ms):
        """run_maintenance() returns a dict with expected keys."""
        result = ms.run_maintenance(dry_run=True)

        assert isinstance(result, dict)
        assert "timestamp" in result
        assert "duration_ms" in result
        assert "decay_count" in result
        assert "archived_count" in result
        assert "stats" in result
        assert "health" in result


# ── Integration tests ─────────────────────────────────────────────────────


class TestIntegration:

    def test_save_then_search_finds_memory(self, ms):
        """Saving a memory then searching for it returns a match (BM25)."""
        ms.save(
            "prefers dark mode in all editors",
            tags=["#pref"],
            importance=0.8,
            check_contradictions=False,
        )

        results = ms.search("dark mode editors")
        assert len(results) >= 1
        assert any("dark mode" in r["content"] for r in results)

    def test_multiple_saves_then_get_recent_correct_order(self, ms):
        """Multiple saves then get_recent returns correct chronological order."""
        contents = []
        for i in range(5):
            m = ms.save(
                f"memory number {i}",
                importance=0.5,
                check_contradictions=False,
            )
            contents.append(m.content)
            time.sleep(0.01)

        recent = ms.get_recent(n=5)
        recent_contents = [m.content for m in recent]

        # Should be reversed (newest first)
        assert recent_contents == list(reversed(contents))
