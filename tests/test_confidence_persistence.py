"""
Tests for confidence persistence — ConfidenceManager + Memory field round-tripping.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Force imports from THIS worktree's src/ via the memory_system symlink.
# Other worktrees may have editable installs competing for the same package name.
_worktree_root = str(Path(__file__).resolve().parent.parent)
# Remove any stale memory_system entries so our path takes priority
for _key in list(sys.modules.keys()):
    if _key.startswith("memory_system"):
        del sys.modules[_key]
sys.path.insert(0, _worktree_root)

import pytest

from memory_system.confidence_persistence import ConfidenceManager
from memory_system.memory_ts_client import MemoryTSClient, Memory
from memory_system.confidence_scoring import calculate_confidence


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create a temporary memory directory for test isolation."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def client(tmp_memory_dir):
    """Create a MemoryTSClient pointing at temp dir."""
    c = MemoryTSClient(memory_dir=tmp_memory_dir)
    # Disable temporal logging to avoid side effects
    c._enable_access_logging = False
    return c


@pytest.fixture
def manager(client):
    """Create a ConfidenceManager wrapping the test client."""
    return ConfidenceManager(client)


@pytest.fixture
def sample_memory(client):
    """Create a single sample memory and return it."""
    return client.create(
        content="Python list comprehensions are faster than for loops for simple transforms.",
        project_id="test-project",
        tags=["#python", "#performance"],
        importance=0.7,
    )


# ---------------------------------------------------------------------------
# confirm() tests
# ---------------------------------------------------------------------------

class TestConfirm:

    def test_confirm_increments_from_zero(self, manager, sample_memory):
        """confirm() increments confirmations from 0 to 1."""
        updated = manager.confirm(sample_memory.id)
        assert updated.confirmations == 1

    def test_confirm_three_times(self, manager, sample_memory):
        """confirm() 3x results in confirmations=3."""
        for _ in range(3):
            updated = manager.confirm(sample_memory.id)
        assert updated.confirmations == 3

    def test_confirm_recalculates_score(self, manager, sample_memory):
        """confirm() recalculates confidence_score using calculate_confidence."""
        updated = manager.confirm(sample_memory.id)
        expected = calculate_confidence(1, 0)
        assert updated.confidence_score == pytest.approx(expected)

    def test_confirm_does_not_touch_contradictions(self, manager, sample_memory):
        """confirm() leaves contradictions at 0."""
        updated = manager.confirm(sample_memory.id)
        assert updated.contradictions == 0

    def test_confirm_high_existing_confirmations(self, manager, client):
        """confirm() on memory that already has high confirmations still works."""
        mem = client.create(
            content="Well-known fact.",
            project_id="test",
            tags=["#fact"],
            importance=0.5,
        )
        # Manually set high confirmations
        client.update(mem.id, confirmations=10, confidence_score=0.9)
        updated = manager.confirm(mem.id)
        assert updated.confirmations == 11
        expected = calculate_confidence(11, 0)
        assert updated.confidence_score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# contradict() tests
# ---------------------------------------------------------------------------

class TestContradict:

    def test_contradict_increments_from_zero(self, manager, sample_memory):
        """contradict() increments contradictions from 0 to 1."""
        updated = manager.contradict(sample_memory.id)
        assert updated.contradictions == 1

    def test_contradict_recalculates_score(self, manager, sample_memory):
        """contradict() recalculates confidence_score using calculate_confidence."""
        updated = manager.contradict(sample_memory.id)
        expected = calculate_confidence(0, 1)
        assert updated.confidence_score == pytest.approx(expected)

    def test_contradict_does_not_touch_confirmations(self, manager, sample_memory):
        """contradict() leaves confirmations at 0."""
        updated = manager.contradict(sample_memory.id)
        assert updated.confirmations == 0


# ---------------------------------------------------------------------------
# Mixed confirm + contradict
# ---------------------------------------------------------------------------

class TestMixed:

    def test_confirm_then_contradict(self, manager, sample_memory):
        """confirm() then contradict() — both counts reflected."""
        manager.confirm(sample_memory.id)
        updated = manager.contradict(sample_memory.id)
        assert updated.confirmations == 1
        assert updated.contradictions == 1
        expected = calculate_confidence(1, 1)
        assert updated.confidence_score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Persistence (disk round-trip)
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_confirm_persists_to_disk(self, manager, client, sample_memory):
        """confirm(), then reload from disk — counts persisted."""
        manager.confirm(sample_memory.id)
        manager.confirm(sample_memory.id)

        # Re-read directly from disk (fresh get)
        reloaded = client.get(sample_memory.id)
        assert reloaded.confirmations == 2
        assert reloaded.contradictions == 0
        expected = calculate_confidence(2, 0)
        assert reloaded.confidence_score == pytest.approx(expected)

    def test_contradict_persists_to_disk(self, manager, client, sample_memory):
        """contradict(), then reload from disk — counts persisted."""
        manager.contradict(sample_memory.id)

        reloaded = client.get(sample_memory.id)
        assert reloaded.contradictions == 1
        expected = calculate_confidence(0, 1)
        assert reloaded.confidence_score == pytest.approx(expected)

    def test_new_memory_defaults_zero(self, client):
        """Freshly created memory has confirmations=0, contradictions=0."""
        mem = client.create(
            content="Brand new memory.",
            project_id="test",
            tags=["#new"],
            importance=0.5,
        )
        reloaded = client.get(mem.id)
        assert reloaded.confirmations == 0
        assert reloaded.contradictions == 0


# ---------------------------------------------------------------------------
# Score boundaries
# ---------------------------------------------------------------------------

class TestScoreBoundaries:

    def test_many_confirmations_capped_at_09(self, manager, sample_memory):
        """Many confirmations don't exceed 0.9 (the cap in calculate_confidence)."""
        for _ in range(20):
            updated = manager.confirm(sample_memory.id)
        assert updated.confidence_score <= 0.9

    def test_many_contradictions_floor_at_01(self, manager, sample_memory):
        """Many contradictions don't go below 0.1 (the floor in calculate_confidence)."""
        for _ in range(10):
            updated = manager.contradict(sample_memory.id)
        assert updated.confidence_score >= 0.1


# ---------------------------------------------------------------------------
# get_summary()
# ---------------------------------------------------------------------------

class TestGetSummary:

    def test_summary_correct_total(self, manager, client):
        """get_summary() returns correct total count."""
        for i in range(3):
            client.create(
                content=f"Memory number {i}",
                project_id="test",
                tags=["#test"],
                importance=0.5,
            )
        summary = manager.get_summary()
        assert summary['total'] == 3

    def test_summary_empty_corpus(self, manager):
        """get_summary() on empty corpus returns total=0."""
        summary = manager.get_summary()
        assert summary['total'] == 0
        assert summary['avg_confidence'] == 0.0

    def test_summary_reflects_confirmations(self, manager, client):
        """get_summary() avg_confidence changes after confirmations."""
        # Create a memory and set its confidence to the baseline (0.5) so
        # that confirmations actually increase it.
        mem = client.create(
            content="Test memory for summary.",
            project_id="test",
            tags=["#test"],
            importance=0.5,
        )
        # Reset confidence to the natural baseline (no confirmations/contradictions)
        client.update(mem.id, confidence_score=calculate_confidence(0, 0))
        before = manager.get_summary()
        assert before['avg_confidence'] == pytest.approx(0.5)

        manager.confirm(mem.id)
        after = manager.get_summary()
        # 1 confirmation -> score = 0.6, which is > 0.5
        assert after['avg_confidence'] > before['avg_confidence']
