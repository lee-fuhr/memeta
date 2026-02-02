"""
Tests for daily_memory_maintenance.py - TDD approach (RED phase)

Testing daily maintenance tasks:
- Decay application (0.99^days)
- Low-importance archival (<0.2)
- Stats collection
- Health checks
- Memory clustering integration
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from src.daily_memory_maintenance import (
    MaintenanceRunner,
    apply_decay_to_all,
    archive_low_importance,
    collect_stats,
    health_check,
    run_daily_maintenance
)


@pytest.fixture
def temp_memory_dir():
    """Create temporary directory for test memories"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def runner(temp_memory_dir):
    """Create maintenance runner with temp directory"""
    return MaintenanceRunner(memory_dir=temp_memory_dir)


class TestDecayApplication:
    """Test applying decay to all memories"""

    def test_decay_applied_to_old_memories(self, runner):
        """Memories not accessed recently get decayed"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create memory from 7 days ago
        created = (datetime.now() - timedelta(days=7)).isoformat()
        memory = client.create(
            content="Old memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8
        )

        # Manually set created date (hack for testing)
        memory = client.get(memory.id)
        client.update(memory.id, **{"created": created})

        # Apply decay
        decayed_count = apply_decay_to_all(runner.memory_dir)

        assert decayed_count >= 1

        # Check memory was decayed
        updated = client.get(memory.id)
        expected = 0.8 * (0.99 ** 7)  # ≈ 0.746
        assert updated.importance < 0.8
        assert abs(updated.importance - expected) < 0.01

    def test_no_decay_for_recent_memories(self, runner):
        """Memories accessed today don't decay"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)
        memory = client.create(
            content="Recent memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8
        )

        original_importance = memory.importance

        # Apply decay
        apply_decay_to_all(runner.memory_dir)

        # Check memory unchanged
        updated = client.get(memory.id)
        assert updated.importance == original_importance

    def test_decay_respects_floor(self, runner):
        """Decay never produces negative importance"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create very old, low-importance memory
        created = (datetime.now() - timedelta(days=365)).isoformat()
        memory = client.create(
            content="Very old memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.2
        )
        client.update(memory.id, **{"created": created})

        # Apply decay
        apply_decay_to_all(runner.memory_dir)

        # Check still >= 0
        updated = client.get(memory.id)
        assert updated.importance >= 0


class TestLowImportanceArchival:
    """Test archiving memories below importance threshold"""

    def test_archive_below_threshold(self, runner):
        """Memories <0.2 importance get archived"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create low-importance memory
        memory = client.create(
            content="Low value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.15
        )

        # Archive low importance
        archived_count = archive_low_importance(runner.memory_dir, threshold=0.2)

        assert archived_count >= 1

        # Check memory was archived (status changed or scope updated)
        updated = client.get(memory.id)
        assert updated.status == "archived" or "archived" in updated.tags

    def test_keep_above_threshold(self, runner):
        """Memories >=0.2 importance stay active"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create medium-importance memory
        memory = client.create(
            content="Medium value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5
        )

        # Archive low importance
        archived_count = archive_low_importance(runner.memory_dir, threshold=0.2)

        # Check memory still active
        updated = client.get(memory.id)
        assert updated.status == "active"

    def test_threshold_configurable(self, runner):
        """Archival threshold can be configured"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create memory at 0.3 importance
        memory = client.create(
            content="Borderline memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.3
        )

        # Archive with threshold 0.4 (should archive)
        archived_count = archive_low_importance(runner.memory_dir, threshold=0.4)
        assert archived_count >= 1

        updated = client.get(memory.id)
        assert updated.status == "archived"


class TestStatsCollection:
    """Test stats collection for dashboard"""

    def test_collect_basic_stats(self, runner):
        """Collect basic memory statistics"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create some test memories
        client.create(content="Memory 1", project_id="LFI", tags=["#learning"], importance=0.8)
        client.create(content="Memory 2", project_id="LFI", tags=["#learning"], importance=0.5)
        client.create(content="Memory 3", project_id="LFI", tags=["#important"], importance=0.9)

        stats = collect_stats(runner.memory_dir)

        assert stats["total_memories"] >= 3
        assert stats["high_importance_count"] >= 1  # 0.8+ memories
        assert stats["avg_importance"] > 0
        assert "project_breakdown" in stats

    def test_stats_include_project_breakdown(self, runner):
        """Stats include per-project breakdown"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create memories across projects
        client.create(content="LFI memory", project_id="LFI", tags=["#learning"])
        client.create(content="Cogent memory", project_id="Cogent", tags=["#learning"])

        stats = collect_stats(runner.memory_dir)

        breakdown = stats["project_breakdown"]
        assert "LFI" in breakdown
        assert "Cogent" in breakdown
        assert breakdown["LFI"] >= 1
        assert breakdown["Cogent"] >= 1

    def test_stats_include_tag_distribution(self, runner):
        """Stats include tag distribution"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)

        # Create memories with different tags
        client.create(content="Learning", project_id="LFI", tags=["#learning"])
        client.create(content="Important", project_id="LFI", tags=["#important"])

        stats = collect_stats(runner.memory_dir)

        assert "tag_distribution" in stats
        tag_dist = stats["tag_distribution"]
        assert "#learning" in tag_dist
        assert tag_dist["#learning"] >= 1


class TestHealthCheck:
    """Test system health checks"""

    def test_health_check_memory_ts_accessible(self, runner):
        """Health check verifies memory-ts directory is accessible"""
        health = health_check(runner.memory_dir)

        assert health["memory_ts_accessible"] is True
        assert "memory_dir" in health

    def test_health_check_counts_files(self, runner):
        """Health check counts memory files"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)
        client.create(content="Test", project_id="LFI", tags=["#test"])

        health = health_check(runner.memory_dir)

        assert health["memory_file_count"] >= 1

    def test_health_check_detects_corruption(self, runner):
        """Health check detects corrupted memory files"""
        # Create corrupted file (invalid YAML)
        corrupt_file = Path(runner.memory_dir) / "corrupt.md"
        corrupt_file.write_text("---\ninvalid yaml: [no closing bracket\n---\nContent")

        health = health_check(runner.memory_dir)

        assert "corrupted_files" in health
        assert health["corrupted_files"] >= 1


class TestMaintenanceRunner:
    """Test complete maintenance runner"""

    def test_runner_executes_all_tasks(self, runner):
        """Runner executes decay, archival, stats, health check"""
        from src.memory_ts_client import MemoryTSClient

        # Setup test data
        client = MemoryTSClient(memory_dir=runner.memory_dir)
        client.create(content="Test memory", project_id="LFI", tags=["#learning"], importance=0.8)

        # Run maintenance
        result = runner.run()

        assert result["decay_count"] >= 0
        assert result["archived_count"] >= 0
        assert result["stats"] is not None
        assert result["health"] is not None

    def test_runner_handles_empty_directory(self, runner):
        """Runner handles empty memory directory gracefully"""
        result = runner.run()

        assert result["decay_count"] == 0
        assert result["archived_count"] == 0
        assert result["stats"]["total_memories"] == 0

    def test_runner_creates_log_entry(self, runner):
        """Runner creates log entry with timestamp"""
        result = runner.run()

        assert "timestamp" in result
        assert "duration_ms" in result

    def test_runner_dry_run_mode(self, runner):
        """Runner supports dry-run mode (no changes)"""
        from src.memory_ts_client import MemoryTSClient

        client = MemoryTSClient(memory_dir=runner.memory_dir)
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#learning"],
            importance=0.15
        )

        # Dry run
        result = runner.run(dry_run=True)

        # Changes not applied
        updated = client.get(memory.id)
        assert updated.status == "active"  # Not archived


class TestMaintenanceFunction:
    """Test convenience function"""

    def test_run_daily_maintenance_convenience(self, temp_memory_dir):
        """Convenience function runs full maintenance"""
        result = run_daily_maintenance(memory_dir=temp_memory_dir)

        assert "decay_count" in result
        assert "archived_count" in result
        assert "stats" in result
        assert "health" in result
