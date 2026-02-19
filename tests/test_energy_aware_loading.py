"""Tests for energy-aware memory loading.

Verifies that EnergyAwareLoader correctly selects time windows,
filters/ranks memories by priority tags, and respects max_memories.
"""

import os
import tempfile
from pathlib import Path

import pytest

from memory_system.energy_aware_loading import EnergyAwareLoader, TimeWindow
from memory_system.memory_ts_client import MemoryTSClient


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create a temp directory for memory files."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


def _create_memory(mem_dir, content, tags, importance=0.5, created=None):
    """Helper to create a memory file in the temp directory."""
    client = MemoryTSClient(memory_dir=mem_dir)
    # Disable temporal logging for tests
    client._enable_access_logging = False
    mem = client.create(
        content=content,
        project_id="test",
        tags=tags,
        importance=importance,
    )
    if created:
        # Rewrite with a custom created timestamp for ordering tests
        mem.created = created
        client._write_memory(mem)
    return mem


class TestTimeWindows:
    """Tests for get_current_window() and time window boundaries."""

    def test_morning_window_at_9am(self, tmp_memory_dir):
        """9am should be in the morning window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        window = loader.get_current_window()
        assert window.name == "morning"
        assert window.start_hour == 6
        assert window.end_hour == 12

    def test_afternoon_window_at_2pm(self, tmp_memory_dir):
        """2pm (14) should be in the afternoon window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=14)
        window = loader.get_current_window()
        assert window.name == "afternoon"

    def test_evening_window_at_8pm(self, tmp_memory_dir):
        """8pm (20) should be in the evening window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=20)
        window = loader.get_current_window()
        assert window.name == "evening"

    def test_night_window_at_3am(self, tmp_memory_dir):
        """3am should be in the night window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=3)
        window = loader.get_current_window()
        assert window.name == "night"

    def test_boundary_noon_is_afternoon(self, tmp_memory_dir):
        """Hour 12 (noon) should be afternoon, not morning."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=12)
        window = loader.get_current_window()
        assert window.name == "afternoon"

    def test_boundary_6am_is_morning(self, tmp_memory_dir):
        """Hour 6 is the start of the morning window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=6)
        window = loader.get_current_window()
        assert window.name == "morning"

    def test_boundary_18_is_evening(self, tmp_memory_dir):
        """Hour 18 is the start of the evening window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=18)
        window = loader.get_current_window()
        assert window.name == "evening"

    def test_boundary_0_is_night(self, tmp_memory_dir):
        """Hour 0 (midnight) is the start of the night window."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=0)
        window = loader.get_current_window()
        assert window.name == "night"

    def test_override_hour_works(self, tmp_memory_dir):
        """override_hour should control which window is selected."""
        for hour, expected in [(7, "morning"), (15, "afternoon"), (22, "evening"), (2, "night")]:
            loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=hour)
            assert loader.get_current_window().name == expected, f"Hour {hour} should be {expected}"


class TestLoadContext:
    """Tests for load_context() scoring and filtering."""

    def test_empty_corpus_returns_empty(self, tmp_memory_dir):
        """No memories should return empty list."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        result = loader.load_context()
        assert result == []

    def test_morning_prioritizes_strategy_tags(self, tmp_memory_dir):
        """Morning window should rank #strategy memories higher."""
        _create_memory(tmp_memory_dir, "Strategy doc", ["#strategy"], importance=0.5)
        _create_memory(tmp_memory_dir, "Task doc", ["#task"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        result = loader.load_context()

        assert len(result) == 2
        # Strategy should be first (score: 0.5 + 2.0 = 2.5 vs 0.5)
        assert result[0]["content"] == "Strategy doc"

    def test_afternoon_prioritizes_task_tags(self, tmp_memory_dir):
        """Afternoon window should rank #task memories higher."""
        _create_memory(tmp_memory_dir, "Strategy doc", ["#strategy"], importance=0.5)
        _create_memory(tmp_memory_dir, "Task doc", ["#task"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=14)
        result = loader.load_context()

        assert len(result) == 2
        # Task should be first (score: 0.5 + 2.0 = 2.5 vs 0.5)
        assert result[0]["content"] == "Task doc"

    def test_evening_prioritizes_learning_tags(self, tmp_memory_dir):
        """Evening window should rank #learning memories higher."""
        _create_memory(tmp_memory_dir, "Task doc", ["#task"], importance=0.8)
        _create_memory(tmp_memory_dir, "Learning doc", ["#learning"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=20)
        result = loader.load_context()

        assert len(result) == 2
        # Learning should be first (score: 0.5 + 2.0 = 2.5 vs 0.8)
        assert result[0]["content"] == "Learning doc"

    def test_night_returns_all_unfiltered(self, tmp_memory_dir):
        """Night window should return all memories without tag filtering."""
        _create_memory(tmp_memory_dir, "A", ["#strategy"], importance=0.9)
        _create_memory(tmp_memory_dir, "B", ["#task"], importance=0.1)
        _create_memory(tmp_memory_dir, "C", ["#learning"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=3)
        result = loader.load_context()

        assert len(result) == 3

    def test_memories_without_priority_tags_still_included(self, tmp_memory_dir):
        """Memories without matching priority tags are included, just lower ranked."""
        _create_memory(tmp_memory_dir, "Priority", ["#strategy"], importance=0.3)
        _create_memory(tmp_memory_dir, "No priority", ["#random"], importance=0.3)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        result = loader.load_context()

        assert len(result) == 2
        # Both included, but priority-tagged one first
        assert result[0]["content"] == "Priority"
        assert result[1]["content"] == "No priority"

    def test_mixed_tag_memory_included_in_both_windows(self, tmp_memory_dir):
        """A memory with both #strategy and #task should rank high in both windows."""
        _create_memory(tmp_memory_dir, "Mixed", ["#strategy", "#task"], importance=0.5)
        _create_memory(tmp_memory_dir, "Plain", ["#other"], importance=0.5)

        # Morning: #strategy is priority
        loader_morning = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        morning_result = loader_morning.load_context()
        assert morning_result[0]["content"] == "Mixed"

        # Afternoon: #task is priority
        loader_afternoon = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=14)
        afternoon_result = loader_afternoon.load_context()
        assert afternoon_result[0]["content"] == "Mixed"

    def test_max_memories_limits_output(self, tmp_memory_dir):
        """max_memories should cap the returned list size."""
        for i in range(10):
            _create_memory(tmp_memory_dir, f"Memory {i}", ["#strategy"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9, max_memories=3)
        result = loader.load_context()

        assert len(result) == 3

    def test_high_importance_no_tag_beats_low_importance_with_tag(self, tmp_memory_dir):
        """A very high importance memory without priority tags can still rank above
        a low importance memory with priority tags if importance difference > 2."""
        _create_memory(tmp_memory_dir, "High imp", ["#other"], importance=3.0)
        _create_memory(tmp_memory_dir, "Low with tag", ["#strategy"], importance=0.1)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        result = loader.load_context()

        # High imp: score = 3.0, Low with tag: score = 0.1 + 2.0 = 2.1
        assert result[0]["content"] == "High imp"

    def test_load_returns_dicts_not_memory_objects(self, tmp_memory_dir):
        """load_context should return plain dicts, not Memory dataclass instances."""
        _create_memory(tmp_memory_dir, "Test", ["#strategy"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        result = loader.load_context()

        assert isinstance(result[0], dict)
        assert "id" in result[0]
        assert "content" in result[0]
        assert "tags" in result[0]
        assert "importance" in result[0]


class TestExplainLoading:
    """Tests for explain_loading() human-readable output."""

    def test_explain_returns_nonempty_string(self, tmp_memory_dir):
        """explain_loading() should return a non-empty string."""
        _create_memory(tmp_memory_dir, "Test", ["#strategy"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        loader.load_context()
        explanation = loader.explain_loading()

        assert isinstance(explanation, str)
        assert len(explanation) > 0

    def test_explain_mentions_window_name(self, tmp_memory_dir):
        """explain_loading() should mention the current window name."""
        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        loader.load_context()
        explanation = loader.explain_loading()

        assert "morning" in explanation

    def test_explain_without_prior_load(self, tmp_memory_dir):
        """explain_loading() should work even if load_context hasn't been called."""
        _create_memory(tmp_memory_dir, "Test", ["#strategy"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        explanation = loader.explain_loading()

        assert isinstance(explanation, str)
        assert len(explanation) > 0
        assert "morning" in explanation

    def test_explain_shows_memory_count(self, tmp_memory_dir):
        """explain_loading() should show how many memories were loaded."""
        for i in range(5):
            _create_memory(tmp_memory_dir, f"Mem {i}", ["#strategy"], importance=0.5)

        loader = EnergyAwareLoader(memory_dir=tmp_memory_dir, override_hour=9)
        loader.load_context()
        explanation = loader.explain_loading()

        assert "5" in explanation
