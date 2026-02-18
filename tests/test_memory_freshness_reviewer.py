"""
Tests for memory freshness reviewer — scan, review, notification.
"""

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.memory_freshness_reviewer import (
    StaleMemory,
    ReviewResult,
    scan_stale_memories,
    refresh_memory,
    archive_memory,
    generate_review_summary,
    _days_since,
)
from memory_system.memory_ts_client import Memory, MemoryTSClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path):
    """Create a temp memory directory with test memories."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


def _write_memory_file(mem_dir: Path, memory_id: str, importance: float,
                        days_old: int, content: str = "test content",
                        domain: str = "testing", status: str = "active"):
    """Helper to write a memory .md file with given age."""
    now = datetime.now(tz=timezone.utc)
    created = now - timedelta(days=days_old)
    created_ms = int(created.timestamp() * 1000)

    tags_str = '["testing"]'
    fm = f"""---
id: {memory_id}
created: {created_ms}
updated: {created_ms}
reasoning: test
importance_weight: {importance}
confidence_score: 0.9
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: {domain}
status: {status}
scope: project
project_id: LFI
session_id: test-session
semantic_tags: {tags_str}
schema_version: 2
---
{content}"""
    (mem_dir / f"{memory_id}.md").write_text(fm)


# ---------------------------------------------------------------------------
# _days_since
# ---------------------------------------------------------------------------

class TestDaysSince:
    def test_epoch_millis(self):
        now = datetime.now(tz=timezone.utc)
        ts_ms = str(int((now - timedelta(days=10)).timestamp() * 1000))
        assert _days_since(ts_ms, now) == 10

    def test_epoch_seconds(self):
        now = datetime.now(tz=timezone.utc)
        ts = str(int((now - timedelta(days=5)).timestamp()))
        assert _days_since(ts, now) == 5

    def test_iso_format(self):
        now = datetime.now(tz=timezone.utc)
        past = (now - timedelta(days=30)).isoformat()
        assert _days_since(past, now) == 30

    def test_empty_returns_none(self):
        assert _days_since("", datetime.now(tz=timezone.utc)) is None

    def test_garbage_returns_none(self):
        assert _days_since("not-a-date", datetime.now(tz=timezone.utc)) is None


# ---------------------------------------------------------------------------
# scan_stale_memories
# ---------------------------------------------------------------------------

class TestScanStaleMemories:
    def test_finds_stale_low_importance(self, memory_dir):
        _write_memory_file(memory_dir, "old-low", 0.2, days_old=100)
        _write_memory_file(memory_dir, "fresh-low", 0.2, days_old=10)
        _write_memory_file(memory_dir, "old-high", 0.9, days_old=100)

        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        ids = [s.memory.id for s in result]
        assert "old-low" in ids
        assert "fresh-low" not in ids
        assert "old-high" not in ids  # importance too high

    def test_include_all_importance(self, memory_dir):
        _write_memory_file(memory_dir, "old-high", 0.9, days_old=100)
        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90, include_all_importance=True)
        assert len(result) == 1
        assert result[0].memory.id == "old-high"

    def test_skips_archived(self, memory_dir):
        _write_memory_file(memory_dir, "archived-old", 0.2, days_old=100, status="archived")
        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        assert len(result) == 0

    def test_sorted_by_staleness_score(self, memory_dir):
        _write_memory_file(memory_dir, "very-stale", 0.1, days_old=200)
        _write_memory_file(memory_dir, "mildly-stale", 0.25, days_old=95)

        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        assert len(result) == 2
        assert result[0].memory.id == "very-stale"  # higher staleness score

    def test_empty_dir(self, memory_dir):
        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        assert result == []

    def test_days_since_update_computed(self, memory_dir):
        _write_memory_file(memory_dir, "old", 0.2, days_old=120)
        result = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        assert len(result) == 1
        assert result[0].days_since_update >= 119  # Allow for test timing


# ---------------------------------------------------------------------------
# refresh_memory / archive_memory
# ---------------------------------------------------------------------------

class TestRefreshAndArchive:
    def test_refresh_updates_timestamp(self, memory_dir):
        _write_memory_file(memory_dir, "to-refresh", 0.2, days_old=100)
        result = refresh_memory("to-refresh", memory_dir=memory_dir)
        assert result.status == "active"

    def test_archive_sets_status(self, memory_dir):
        _write_memory_file(memory_dir, "to-archive", 0.2, days_old=100)
        result = archive_memory("to-archive", memory_dir=memory_dir)
        assert result.status == "archived"
        assert "#archived" in result.tags


# ---------------------------------------------------------------------------
# generate_review_summary
# ---------------------------------------------------------------------------

class TestGenerateReviewSummary:
    def test_empty_stale_list(self):
        summary = generate_review_summary([])
        assert "fresh" in summary.lower()

    def test_includes_count(self, memory_dir):
        _write_memory_file(memory_dir, "s1", 0.2, days_old=100)
        _write_memory_file(memory_dir, "s2", 0.1, days_old=150)
        stale = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        summary = generate_review_summary(stale)
        assert "2 memories" in summary

    def test_includes_dashboard_link(self, memory_dir):
        _write_memory_file(memory_dir, "s1", 0.2, days_old=100)
        stale = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        summary = generate_review_summary(stale)
        assert "localhost:7860" in summary

    def test_truncates_long_list(self, memory_dir):
        for i in range(10):
            _write_memory_file(memory_dir, f"s{i}", 0.1, days_old=100 + i)
        stale = scan_stale_memories(memory_dir=memory_dir, stale_days=90)
        summary = generate_review_summary(stale, max_items=3)
        assert "more" in summary


# ---------------------------------------------------------------------------
# StaleMemory
# ---------------------------------------------------------------------------

class TestStaleMemory:
    def test_summary_format(self):
        m = Memory(
            id="test", content="This is test content for summary",
            importance=0.3, tags=["test"], project_id="LFI",
            knowledge_domain="testing",
        )
        sm = StaleMemory(memory=m, days_since_update=95, staleness_score=2.2)
        assert "95d" in sm.summary
        assert "testing" in sm.summary
