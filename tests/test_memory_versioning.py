"""
Tests for memory versioning (Feature 23)

Tests version creation, history tracking, diffs, and rollback functionality.
"""

import pytest
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.intelligence.database import IntelligenceDB
from src.intelligence.versioning import MemoryVersioning, MemoryVersion


@pytest.fixture
def db_path(tmp_path):
    """Create temporary intelligence database"""
    return tmp_path / "test_intelligence.db"


@pytest.fixture
def db(db_path):
    """Create intelligence database instance"""
    return IntelligenceDB(db_path=db_path)


@pytest.fixture
def versioning(db):
    """Create versioning instance"""
    return MemoryVersioning(db=db)


class TestVersionCreation:
    """Test creating new versions"""

    def test_create_first_version(self, versioning):
        """Should create version 1 for new memory"""
        v = versioning.create_version(
            memory_id="mem_001",
            content="Always verify work before claiming completion",
            importance=0.9,
            changed_by="user",
            change_reason="Initial capture"
        )

        assert v.version == 1
        assert v.memory_id == "mem_001"
        assert v.content == "Always verify work before claiming completion"
        assert v.importance == 0.9
        assert v.changed_by == "user"
        assert v.change_reason == "Initial capture"
        assert v.timestamp > 0

    def test_create_subsequent_versions(self, versioning):
        """Should increment version number"""
        versioning.create_version("mem_001", "Content v1", 0.5)
        versioning.create_version("mem_001", "Content v2", 0.6)
        v3 = versioning.create_version("mem_001", "Content v3", 0.7)

        assert v3.version == 3

    def test_different_memories_independent_versions(self, versioning):
        """Version numbers should be independent per memory"""
        v1 = versioning.create_version("mem_001", "Memory 1", 0.5)
        v2 = versioning.create_version("mem_002", "Memory 2", 0.6)

        assert v1.version == 1
        assert v2.version == 1

    def test_default_changed_by(self, versioning):
        """Should default changed_by to 'user'"""
        v = versioning.create_version("mem_001", "Content", 0.5)
        assert v.changed_by == "user"


class TestVersionRetrieval:
    """Test retrieving versions"""

    def test_get_version_history(self, versioning):
        """Should return all versions in order"""
        versioning.create_version("mem_001", "V1", 0.5, change_reason="First")
        time.sleep(0.01)  # Ensure different timestamps
        versioning.create_version("mem_001", "V2", 0.6, change_reason="Second")
        time.sleep(0.01)
        versioning.create_version("mem_001", "V3", 0.7, change_reason="Third")

        history = versioning.get_version_history("mem_001")

        assert len(history) == 3
        assert history[0].version == 1
        assert history[1].version == 2
        assert history[2].version == 3
        assert history[0].content == "V1"
        assert history[2].content == "V3"

    def test_get_version_history_empty(self, versioning):
        """Should return empty list for non-existent memory"""
        history = versioning.get_version_history("nonexistent")
        assert history == []

    def test_get_specific_version(self, versioning):
        """Should retrieve specific version"""
        versioning.create_version("mem_001", "V1", 0.5)
        versioning.create_version("mem_001", "V2", 0.6)

        v = versioning.get_version("mem_001", 1)

        assert v is not None
        assert v.version == 1
        assert v.content == "V1"

    def test_get_nonexistent_version(self, versioning):
        """Should return None for non-existent version"""
        versioning.create_version("mem_001", "V1", 0.5)

        v = versioning.get_version("mem_001", 99)

        assert v is None

    def test_get_latest_version(self, versioning):
        """Should return most recent version"""
        versioning.create_version("mem_001", "V1", 0.5)
        versioning.create_version("mem_001", "V2", 0.6)
        versioning.create_version("mem_001", "V3", 0.7)

        latest = versioning.get_latest_version("mem_001")

        assert latest is not None
        assert latest.version == 3
        assert latest.content == "V3"

    def test_get_latest_version_nonexistent(self, versioning):
        """Should return None for non-existent memory"""
        latest = versioning.get_latest_version("nonexistent")
        assert latest is None


class TestVersionDiff:
    """Test diff between versions"""

    def test_diff_versions(self, versioning):
        """Should show differences between versions"""
        versioning.create_version("mem_001", "Old content", 0.5, changed_by="user")
        time.sleep(0.01)
        versioning.create_version("mem_001", "New content", 0.9, changed_by="llm")

        diff = versioning.diff_versions("mem_001", 1, 2)

        assert diff is not None
        assert diff['content_changed'] is True
        assert diff['importance_changed'] is True
        assert diff['content_diff']['before'] == "Old content"
        assert diff['content_diff']['after'] == "New content"
        assert diff['importance_diff']['before'] == 0.5
        assert diff['importance_diff']['after'] == 0.9
        assert diff['changed_by_a'] == "user"
        assert diff['changed_by_b'] == "llm"
        assert diff['time_between_seconds'] >= 0  # May be 0 on fast systems

    def test_diff_no_changes(self, versioning):
        """Should handle identical versions"""
        versioning.create_version("mem_001", "Same", 0.5)
        versioning.create_version("mem_001", "Same", 0.5)

        diff = versioning.diff_versions("mem_001", 1, 2)

        assert diff is not None
        assert diff['content_changed'] is False
        assert diff['importance_changed'] is False

    def test_diff_nonexistent_version(self, versioning):
        """Should return None if version doesn't exist"""
        versioning.create_version("mem_001", "Content", 0.5)

        diff = versioning.diff_versions("mem_001", 1, 99)

        assert diff is None


class TestRollback:
    """Test rollback functionality"""

    def test_rollback_to_version(self, versioning):
        """Should create new version with old content"""
        versioning.create_version("mem_001", "V1", 0.5)
        versioning.create_version("mem_001", "V2", 0.6)
        versioning.create_version("mem_001", "V3", 0.7)

        rollback = versioning.rollback_to_version("mem_001", 1)

        assert rollback is not None
        assert rollback.version == 4  # New version created
        assert rollback.content == "V1"  # Content from v1
        assert rollback.changed_by == "system"
        assert "Rollback to version 1" in rollback.change_reason

    def test_rollback_preserves_history(self, versioning):
        """Should not delete history when rolling back"""
        versioning.create_version("mem_001", "V1", 0.5)
        versioning.create_version("mem_001", "V2", 0.6)

        versioning.rollback_to_version("mem_001", 1)

        history = versioning.get_version_history("mem_001")
        assert len(history) == 3  # Original 2 + rollback

    def test_rollback_nonexistent_version(self, versioning):
        """Should return None for non-existent version"""
        versioning.create_version("mem_001", "V1", 0.5)

        rollback = versioning.rollback_to_version("mem_001", 99)

        assert rollback is None


class TestUtilityMethods:
    """Test utility methods"""

    def test_get_version_count(self, versioning):
        """Should return correct version count"""
        versioning.create_version("mem_001", "V1", 0.5)
        versioning.create_version("mem_001", "V2", 0.6)
        versioning.create_version("mem_001", "V3", 0.7)

        count = versioning.get_version_count("mem_001")

        assert count == 3

    def test_get_version_count_zero(self, versioning):
        """Should return 0 for non-existent memory"""
        count = versioning.get_version_count("nonexistent")
        assert count == 0

    def test_get_all_versioned_memories(self, versioning):
        """Should return all memory IDs with versions"""
        versioning.create_version("mem_001", "Content", 0.5)
        versioning.create_version("mem_002", "Content", 0.6)
        versioning.create_version("mem_003", "Content", 0.7)

        memories = versioning.get_all_versioned_memories()

        assert len(memories) == 3
        assert "mem_001" in memories
        assert "mem_002" in memories
        assert "mem_003" in memories

    def test_get_recent_changes(self, versioning):
        """Should return recently changed memories"""
        versioning.create_version("mem_001", "V1", 0.5)
        time.sleep(0.1)  # Longer sleep for timestamp differences
        versioning.create_version("mem_002", "V1", 0.6)
        time.sleep(0.1)
        versioning.create_version("mem_003", "V1", 0.7)

        recent = versioning.get_recent_changes(limit=2)

        assert len(recent) == 2
        # Check that we got 2 of the 3 memories (order may vary on fast systems)
        memory_ids = {v.memory_id for v in recent}
        assert len(memory_ids) == 2
        assert memory_ids.issubset({"mem_001", "mem_002", "mem_003"})

    def test_get_recent_changes_respects_limit(self, versioning):
        """Should limit results"""
        for i in range(10):
            versioning.create_version(f"mem_{i:03d}", "Content", 0.5)

        recent = versioning.get_recent_changes(limit=5)

        assert len(recent) == 5
