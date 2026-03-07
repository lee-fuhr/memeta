"""Tests for correction_velocity.py — TDD red phase.

Correction velocity metric: tracks how quickly corrections move from
first detection to confirmed behavioral change (graduation to CLAUDE.md).
Measures pipeline health and surfaces stuck corrections.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.correction_velocity import (
    CorrectionVelocityTracker,
    PipelineSnapshot,
)
from memory_system.memory_ts_client import MemoryTSClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path):
    d = tmp_path / "memories"
    d.mkdir()
    return d


@pytest.fixture
def memory_client(memory_dir):
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def tracker(memory_dir):
    return CorrectionVelocityTracker(memory_dir=memory_dir)


def make_correction(memory_client, content="Always do X", confirmations=0, graduated=False):
    """Create a correction memory, optionally marked graduated."""
    tags = ["#correction"]
    if graduated:
        tags.append("#graduated")
    return memory_client.create(
        content=content,
        project_id="test",
        importance=0.9,
        context_type="correction",
        tags=tags,
        confirmations=confirmations,
    )


# ---------------------------------------------------------------------------
# PipelineSnapshot dataclass
# ---------------------------------------------------------------------------

class TestPipelineSnapshot:
    def test_has_required_fields(self):
        s = PipelineSnapshot(
            total=10,
            graduated=4,
            pending=3,    # 1-2 confirmations (approaching threshold)
            new=3,        # 0 confirmations
            graduation_rate=0.4,
            avg_days_to_graduate=None,
        )
        assert s.total == 10
        assert s.graduated == 4
        assert s.graduation_rate == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# get_snapshot()
# ---------------------------------------------------------------------------

class TestGetSnapshot:
    def test_returns_pipeline_snapshot(self, tracker):
        result = tracker.get_snapshot()
        assert isinstance(result, PipelineSnapshot)

    def test_zero_totals_when_empty(self, tracker):
        result = tracker.get_snapshot()
        assert result.total == 0
        assert result.graduated == 0
        assert result.graduation_rate == 0.0

    def test_counts_corrections(self, tracker, memory_client):
        make_correction(memory_client, "Rule A")
        make_correction(memory_client, "Rule B")
        result = tracker.get_snapshot()
        assert result.total == 2

    def test_counts_graduated(self, tracker, memory_client):
        make_correction(memory_client, "Rule A", confirmations=3, graduated=True)
        make_correction(memory_client, "Rule B", confirmations=1)
        result = tracker.get_snapshot()
        assert result.graduated == 1

    def test_counts_new_zero_confirmations(self, tracker, memory_client):
        make_correction(memory_client, "Brand new correction", confirmations=0)
        result = tracker.get_snapshot()
        assert result.new == 1

    def test_counts_pending_has_some_confirmations(self, tracker, memory_client):
        make_correction(memory_client, "Pending", confirmations=1)
        make_correction(memory_client, "Also pending", confirmations=2)
        result = tracker.get_snapshot()
        assert result.pending == 2

    def test_graduation_rate(self, tracker, memory_client):
        make_correction(memory_client, "Graduated", confirmations=3, graduated=True)
        make_correction(memory_client, "Not yet", confirmations=1)
        result = tracker.get_snapshot()
        assert result.graduation_rate == pytest.approx(0.5)

    def test_graduation_rate_zero_when_no_corrections(self, tracker):
        result = tracker.get_snapshot()
        assert result.graduation_rate == 0.0

    def test_ignores_non_correction_memories(self, tracker, memory_client):
        memory_client.create(
            content="Just a knowledge memory",
            project_id="test",
            importance=0.5,
            context_type="knowledge",
            tags=["#knowledge"],
        )
        result = tracker.get_snapshot()
        assert result.total == 0

    def test_avg_days_to_graduate_none_when_no_graduated(self, tracker, memory_client):
        make_correction(memory_client, "Not graduated", confirmations=1)
        result = tracker.get_snapshot()
        assert result.avg_days_to_graduate is None

    def test_avg_days_to_graduate_is_float_when_graduated(self, tracker, memory_client):
        make_correction(memory_client, "Rule A", confirmations=3, graduated=True)
        result = tracker.get_snapshot()
        # May be very small (just created) but should be a float
        assert isinstance(result.avg_days_to_graduate, float)


# ---------------------------------------------------------------------------
# get_stuck_corrections()
# ---------------------------------------------------------------------------

class TestGetStuckCorrections:
    def test_returns_list(self, tracker):
        result = tracker.get_stuck_corrections()
        assert isinstance(result, list)

    def test_empty_when_no_corrections(self, tracker):
        result = tracker.get_stuck_corrections()
        assert result == []

    def test_recently_created_not_stuck(self, tracker, memory_client):
        make_correction(memory_client, "New correction", confirmations=0)
        result = tracker.get_stuck_corrections(days=30)
        # Just created — not old enough to be stuck
        assert result == []

    def test_graduated_not_stuck(self, tracker, memory_client):
        make_correction(memory_client, "Rule A", confirmations=3, graduated=True)
        result = tracker.get_stuck_corrections(days=0)
        # Graduated corrections should never appear as stuck
        stuck_contents = [m.content for m in result]
        assert "Rule A" not in stuck_contents


# ---------------------------------------------------------------------------
# graduation_rate()
# ---------------------------------------------------------------------------

class TestGraduationRate:
    def test_returns_float(self, tracker):
        result = tracker.graduation_rate()
        assert isinstance(result, float)

    def test_zero_when_no_corrections(self, tracker):
        assert tracker.graduation_rate() == 0.0

    def test_one_when_all_graduated(self, tracker, memory_client):
        make_correction(memory_client, "Rule A", confirmations=3, graduated=True)
        make_correction(memory_client, "Rule B", confirmations=3, graduated=True)
        assert tracker.graduation_rate() == pytest.approx(1.0)

    def test_partial_graduation(self, tracker, memory_client):
        make_correction(memory_client, "Graduated", confirmations=3, graduated=True)
        make_correction(memory_client, "Not yet", confirmations=1)
        assert tracker.graduation_rate() == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# stage_distribution()
# ---------------------------------------------------------------------------

class TestStageDistribution:
    def test_returns_dict(self, tracker):
        result = tracker.stage_distribution()
        assert isinstance(result, dict)

    def test_empty_dict_when_no_corrections(self, tracker):
        result = tracker.stage_distribution()
        assert result == {}

    def test_has_correct_stages(self, tracker, memory_client):
        make_correction(memory_client, "New", confirmations=0)
        make_correction(memory_client, "Pending", confirmations=2)
        make_correction(memory_client, "Graduated", confirmations=3, graduated=True)
        dist = tracker.stage_distribution()
        assert "new" in dist or 0 in dist
        # Should account for all 3 corrections
        total = sum(dist.values())
        assert total == 3

    def test_counts_per_stage(self, tracker, memory_client):
        make_correction(memory_client, "A", confirmations=0)
        make_correction(memory_client, "B", confirmations=0)
        make_correction(memory_client, "C", confirmations=3, graduated=True)
        dist = tracker.stage_distribution()
        assert dist.get("new", dist.get(0, 0)) == 2
        assert dist.get("graduated", 0) == 1
