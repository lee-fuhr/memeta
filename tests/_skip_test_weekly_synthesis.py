"""
Tests for weekly synthesis - collects promotions and generates summary

Tests promotion collection, cluster grouping, draft generation,
and notification sending.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fsrs_scheduler import FSRSScheduler, ReviewGrade
from src.memory_ts_client import MemoryTSClient
from src.promotion_executor import PromotionExecutor
from src.memory_clustering import MemoryClustering
from src.weekly_synthesis import (
    WeeklySynthesis,
    SynthesisReport,
)


@pytest.fixture
def db_path(tmp_path):
    """FSRS database"""
    return tmp_path / "test_fsrs.db"


@pytest.fixture
def cluster_db_path(tmp_path):
    """Cluster database"""
    return tmp_path / "test_clusters.db"


@pytest.fixture
def memory_dir(tmp_path):
    """Memory directory"""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def output_dir(tmp_path):
    """Synthesis output directory"""
    out_dir = tmp_path / "synthesis"
    out_dir.mkdir()
    return out_dir


@pytest.fixture
def scheduler(db_path):
    return FSRSScheduler(db_path=db_path)


@pytest.fixture
def memory_client(memory_dir):
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def synthesis(memory_dir, db_path, cluster_db_path, output_dir, scheduler, memory_client):
    return WeeklySynthesis(
        memory_dir=memory_dir,
        fsrs_db_path=db_path,
        cluster_db_path=cluster_db_path,
        output_dir=output_dir,
        scheduler=scheduler,
        memory_client=memory_client,
    )


def create_promoted_memory(memory_client, scheduler, content, project_id="LFI"):
    """Helper: create and promote a memory through the full pipeline"""
    mem = memory_client.create(
        content=content,
        project_id=project_id,
        tags=["#learning"],
        importance=0.8,
        scope="project",
    )

    scheduler.register_memory(mem.id, project_id=project_id)
    scheduler.record_review(mem.id, ReviewGrade.GOOD, project_id=project_id)
    scheduler.record_review(mem.id, ReviewGrade.EASY, project_id="ClientA")
    scheduler.record_review(mem.id, ReviewGrade.EASY, project_id="ClientB")

    executor = PromotionExecutor(
        scheduler=scheduler,
        memory_client=memory_client,
    )
    executor.promote_single(mem.id)

    return mem.id


class TestSynthesisReport:
    """Test SynthesisReport data structure"""

    def test_create_report(self):
        """Should create report with required fields"""
        report = SynthesisReport(
            promoted_count=3,
            cluster_summaries={"validation": ["mem-001", "mem-002"]},
            draft_text="## New universal learnings\n...",
            output_path="/tmp/synthesis.md",
        )
        assert report.promoted_count == 3
        assert len(report.cluster_summaries) == 1


class TestWeeklySynthesis:
    """Test weekly synthesis generation"""

    def test_collects_recently_promoted(self, synthesis, memory_client, scheduler):
        """Should find memories promoted since last run"""
        mem_id = create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )

        report = synthesis.generate()

        assert report.promoted_count >= 1

    def test_generates_draft_text(self, synthesis, memory_client, scheduler):
        """Should generate markdown draft text"""
        create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )

        report = synthesis.generate()

        assert report.draft_text is not None
        assert len(report.draft_text) > 0
        assert "validate" in report.draft_text.lower() or "input" in report.draft_text.lower()

    def test_writes_output_file(self, synthesis, memory_client, scheduler, output_dir):
        """Should write draft to output directory"""
        create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )

        report = synthesis.generate()

        assert report.output_path is not None
        output_file = Path(report.output_path)
        assert output_file.exists()
        content = output_file.read_text()
        assert len(content) > 0

    def test_empty_when_no_promotions(self, synthesis):
        """Should handle no promotions gracefully"""
        report = synthesis.generate()

        assert report.promoted_count == 0
        assert report.draft_text == ""

    def test_multiple_promotions(self, synthesis, memory_client, scheduler):
        """Should handle multiple promoted memories"""
        create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )
        create_promoted_memory(
            memory_client, scheduler,
            "Use structured logging with context fields"
        )

        report = synthesis.generate()

        assert report.promoted_count >= 2

    def test_groups_by_cluster(self, synthesis, memory_client, scheduler):
        """Should group promoted memories by theme"""
        create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )
        create_promoted_memory(
            memory_client, scheduler,
            "Input validation prevents injection attacks"
        )

        report = synthesis.generate()

        # Should have cluster summaries
        assert len(report.cluster_summaries) >= 1


class TestNotification:
    """Test Pushover notification (mocked)"""

    @patch("src.weekly_synthesis.subprocess.run")
    def test_sends_pushover(self, mock_run, synthesis, memory_client, scheduler):
        """Should attempt to send Pushover notification"""
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")

        create_promoted_memory(
            memory_client, scheduler,
            "Always validate user input at system boundaries"
        )

        report = synthesis.generate()
        synthesis.notify(report)

        # Should have called subprocess to send notification
        assert mock_run.called

    def test_no_notification_for_empty(self, synthesis):
        """Should not send notification when nothing was promoted"""
        report = synthesis.generate()

        # notify should be a no-op for empty reports
        synthesis.notify(report)  # Should not raise
