"""
Tests for memory decay archival feature

Tests the integration between:
- MemoryTSClient.archive() — moves files to archived/ subdirectory
- MemoryTSClient.list() — with include_archived parameter
- MemoryTSClient.get() — checks both active and archived locations
- MaintenanceRunner — archives low-importance and predicted-stale memories
- Archive manifest creation
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from memory_system.memory_ts_client import (
    MemoryTSClient,
    Memory,
    MemoryNotFoundError,
)
from memory_system.daily_memory_maintenance import (
    MaintenanceRunner,
    archive_low_importance,
)


@pytest.fixture
def temp_memory_dir():
    """Create temporary directory for test memories"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_memory_dir):
    """Create client pointing to temp directory"""
    return MemoryTSClient(memory_dir=temp_memory_dir)


class TestArchivalByImportance:
    """Test archival based on importance threshold"""

    def test_low_importance_gets_archived(self, client, temp_memory_dir):
        """Memory with importance=0.1 gets archived"""
        memory = client.create(
            content="Low value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        archived_count = archive_low_importance(temp_memory_dir, threshold=0.2)

        assert archived_count == 1

        # Original file should be gone
        original_path = Path(temp_memory_dir) / f"{memory.id}.md"
        assert not original_path.exists()

        # Should be in archived/
        archived_path = Path(temp_memory_dir) / "archived" / f"{memory.id}.md"
        assert archived_path.exists()

    def test_above_threshold_not_archived(self, client, temp_memory_dir):
        """Memory with importance=0.3 does NOT get archived (above threshold)"""
        memory = client.create(
            content="Medium value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.3
        )

        archived_count = archive_low_importance(temp_memory_dir, threshold=0.2)

        assert archived_count == 0

        # File should still be in main directory
        original_path = Path(temp_memory_dir) / f"{memory.id}.md"
        assert original_path.exists()

        # archived/ should not exist
        archived_dir = Path(temp_memory_dir) / "archived"
        assert not archived_dir.exists()


class TestArchivedMemoryAccess:
    """Test accessing archived memories"""

    def test_archived_excluded_from_list_default(self, client, temp_memory_dir):
        """Archived memory excluded from list() default"""
        mem1 = client.create(
            content="Active memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8
        )
        mem2 = client.create(
            content="Low memory to archive",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        # Archive the low-importance one
        client.archive(mem2.id, reason="low_importance")

        # Default list should only return active
        active_list = client.list()
        active_ids = [m.id for m in active_list]
        assert mem1.id in active_ids
        assert mem2.id not in active_ids

    def test_archived_included_with_flag(self, client, temp_memory_dir):
        """Archived memory included in list(include_archived=True)"""
        mem1 = client.create(
            content="Active memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.8
        )
        mem2 = client.create(
            content="Memory to archive",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        client.archive(mem2.id, reason="low_importance")

        # Include archived
        all_memories = client.list(include_archived=True)
        all_ids = [m.id for m in all_memories]
        assert mem1.id in all_ids
        assert mem2.id in all_ids

    def test_get_archived_memory(self, client):
        """get(archived_id) still works after archival"""
        memory = client.create(
            content="Memory that will be archived",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )
        memory_id = memory.id

        client.archive(memory_id, reason="low_importance")

        # get() should still find it
        retrieved = client.get(memory_id)
        assert retrieved.id == memory_id
        assert retrieved.status == "archived"
        assert "Memory that will be archived" in retrieved.content


class TestArchiveManifest:
    """Test archive manifest creation"""

    def test_manifest_created(self, client, temp_memory_dir):
        """Manifest file created after archival"""
        client.create(
            content="Low value",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        archive_low_importance(temp_memory_dir, threshold=0.2)

        # Check manifest exists
        today = datetime.now().strftime("%Y-%m-%d")
        manifest_path = Path(temp_memory_dir) / "archived" / f"{today}-archive.md"
        assert manifest_path.exists()

    def test_manifest_contains_correct_content(self, client, temp_memory_dir):
        """Manifest contains correct content (IDs, reasons)"""
        mem = client.create(
            content="Low value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.15
        )

        archive_low_importance(temp_memory_dir, threshold=0.2)

        today = datetime.now().strftime("%Y-%m-%d")
        manifest_path = Path(temp_memory_dir) / "archived" / f"{today}-archive.md"
        manifest_content = manifest_path.read_text()

        assert mem.id in manifest_content
        assert "low_importance" in manifest_content
        assert "0.15" in manifest_content
        assert "archived_at:" in manifest_content


class TestDecayPredictorIntegration:
    """Test integration with DecayPredictor for stale memory archival"""

    def test_predicted_stale_gets_archived(self, client, temp_memory_dir):
        """Memory past predicted stale date gets archived"""
        # Create a memory with normal importance (above threshold)
        memory = client.create(
            content="Stale predicted memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5
        )

        # Mock DecayPredictor
        mock_predictor = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.memory_id = memory.id
        mock_predictor.get_memories_becoming_stale.return_value = [mock_prediction]

        archived_count = archive_low_importance(
            temp_memory_dir,
            threshold=0.2,
            decay_predictor=mock_predictor
        )

        assert archived_count == 1
        mock_predictor.get_memories_becoming_stale.assert_called_once_with(days_ahead=0)

        # Memory should be archived
        archived_path = Path(temp_memory_dir) / "archived" / f"{memory.id}.md"
        assert archived_path.exists()

    def test_dedup_low_importance_and_stale(self, client, temp_memory_dir):
        """Memory that is both low importance AND predicted stale is only archived once"""
        memory = client.create(
            content="Low and stale",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        mock_predictor = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.memory_id = memory.id
        mock_predictor.get_memories_becoming_stale.return_value = [mock_prediction]

        archived_count = archive_low_importance(
            temp_memory_dir,
            threshold=0.2,
            decay_predictor=mock_predictor
        )

        # Should only archive once, not twice
        assert archived_count == 1


class TestArchiveIdempotency:
    """Test edge cases and idempotency"""

    def test_archive_already_archived_is_idempotent(self, client):
        """Calling archive() on already-archived memory doesn't error"""
        memory = client.create(
            content="Will be archived twice",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        # Archive first time
        result1 = client.archive(memory.id, reason="low_importance")
        assert result1 is True

        # Archive second time — should return False, no error
        result2 = client.archive(memory.id, reason="low_importance")
        assert result2 is False

    def test_no_archival_no_dir_created(self, client, temp_memory_dir):
        """No memories below threshold = no archived/ dir created"""
        client.create(
            content="High value memory",
            project_id="LFI",
            tags=["#learning"],
            importance=0.9
        )

        archived_count = archive_low_importance(temp_memory_dir, threshold=0.2)

        assert archived_count == 0
        archived_dir = Path(temp_memory_dir) / "archived"
        assert not archived_dir.exists()

    def test_archived_memory_has_correct_status(self, client):
        """Archived memory file has status=archived and #archived tag"""
        memory = client.create(
            content="To be archived",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        client.archive(memory.id, reason="low_importance")

        retrieved = client.get(memory.id)
        assert retrieved.status == "archived"
        assert "#archived" in retrieved.tags

    def test_manifest_reason_for_predicted_stale(self, client, temp_memory_dir):
        """Manifest shows predicted_stale reason for decay-predicted archival"""
        memory = client.create(
            content="Stale content",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5
        )

        mock_predictor = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.memory_id = memory.id
        mock_predictor.get_memories_becoming_stale.return_value = [mock_prediction]

        archive_low_importance(
            temp_memory_dir,
            threshold=0.2,
            decay_predictor=mock_predictor
        )

        today = datetime.now().strftime("%Y-%m-%d")
        manifest_path = Path(temp_memory_dir) / "archived" / f"{today}-archive.md"
        manifest_content = manifest_path.read_text()

        assert "predicted_stale" in manifest_content
        assert memory.id in manifest_content


class TestMaintenanceRunnerArchival:
    """Test MaintenanceRunner integration with archival"""

    def test_runner_returns_archived_count(self, temp_memory_dir):
        """Runner returns updated archived_count field"""
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        client.create(
            content="Low importance for runner",
            project_id="LFI",
            tags=["#learning"],
            importance=0.1
        )

        runner = MaintenanceRunner(memory_dir=temp_memory_dir)
        result = runner.run()

        assert result["archived_count"] >= 1

    def test_runner_with_decay_predictor(self, temp_memory_dir):
        """Runner passes decay_predictor through to archive function"""
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        memory = client.create(
            content="Predicted stale via runner",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5
        )

        mock_predictor = MagicMock()
        mock_prediction = MagicMock()
        mock_prediction.memory_id = memory.id
        mock_predictor.get_memories_becoming_stale.return_value = [mock_prediction]

        runner = MaintenanceRunner(
            memory_dir=temp_memory_dir,
            decay_predictor=mock_predictor
        )
        result = runner.run()

        assert result["archived_count"] >= 1
        mock_predictor.get_memories_becoming_stale.assert_called()
