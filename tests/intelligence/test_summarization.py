"""
Tests for Feature 26: Memory Summarization

Test coverage:
- Initialization and schema validation
- Cluster summarization (basic, not found, empty, LLM fallback)
- Project summarization (basic, insufficient memories, date filtering)
- Period summarization (basic, no memories, date range handling)
- Summary retrieval and filtering
- Summary regeneration
- Statistics
"""

import pytest
import sqlite3
import json
from pathlib import Path
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from memory_system.intelligence.summarization import (
    MemorySummarizer,
    Summary
)
from memory_system.intelligence_db import IntelligenceDB


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    # Initialize intelligence.db schema
    intel_db = IntelligenceDB(db_path)
    intel_db.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def mock_memory_client():
    """Create mock MemoryTSClient"""
    client = Mock()

    # Mock memory objects
    class MockMemory:
        def __init__(self, id, content, created_at=None, project_id=None):
            self.id = id
            self.content = content
            self.created_at = created_at or datetime.now()
            self.project_id = project_id

    # Default get behavior
    client.get = Mock(side_effect=lambda id: MockMemory(id, f"Memory content for {id}"))

    # Default search behavior
    client.search = Mock(return_value=[])

    return client


@pytest.fixture
def summarizer(temp_db, mock_memory_client):
    """Create summarizer with temp database and mock client"""
    return MemorySummarizer(db_path=temp_db, memory_client=mock_memory_client)


# === Initialization Tests ===

def test_summarizer_initialization(summarizer):
    """Test summarizer initializes database correctly"""
    # Check that summary table exists
    cursor = summarizer.intel_db.conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='memory_summaries'
    """)
    assert cursor.fetchone() is not None


def test_summarizer_with_custom_db(mock_memory_client):
    """Test summarizer works with custom database path"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        intel_db = IntelligenceDB(db_path)
        intel_db.close()

        summarizer = MemorySummarizer(db_path=db_path, memory_client=mock_memory_client)
        assert summarizer.intel_db.db_path == Path(db_path)
    finally:
        Path(db_path).unlink(missing_ok=True)


# === Cluster Summary Tests ===

def test_summarize_cluster_basic(summarizer, mock_memory_client):
    """Test basic cluster summarization"""
    # Create a cluster in database
    cluster_id = "cluster-1"
    cursor = summarizer.intel_db.conn.cursor()
    cursor.execute("""
        INSERT INTO memory_clusters
        (id, name, description, memory_ids, cohesion_score, member_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cluster_id,
        "Test Cluster",
        "Test description",
        json.dumps(["mem1", "mem2", "mem3"]),
        0.85,
        3,
        int(datetime.now().timestamp()),
        int(datetime.now().timestamp())
    ))
    summarizer.intel_db.conn.commit()

    # Mock LLM response
    with patch('memory_system.intelligence.summarization._ask_claude', return_value="This cluster is about testing. It contains three related memories about unit tests and code quality. The key pattern is focus on test coverage."):
        summary = summarizer.summarize_cluster(cluster_id)

    assert summary is not None
    assert summary.summary_type == "cluster"
    assert summary.target_id == cluster_id
    assert summary.memory_count == 3
    assert "testing" in summary.summary.lower()
    assert len(summary.summary) > 50  # Should be substantive


def test_summarize_cluster_not_found(summarizer):
    """Test cluster summarization with invalid cluster_id"""
    summary = summarizer.summarize_cluster("nonexistent-cluster")
    assert summary is None


def test_summarize_cluster_empty(summarizer):
    """Test summarization of empty cluster"""
    # Create empty cluster
    cluster_id = "empty-cluster"
    cursor = summarizer.intel_db.conn.cursor()
    cursor.execute("""
        INSERT INTO memory_clusters
        (id, name, description, memory_ids, cohesion_score, member_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cluster_id,
        "Empty Cluster",
        None,
        json.dumps([]),
        0.0,
        0,
        int(datetime.now().timestamp()),
        int(datetime.now().timestamp())
    ))
    summarizer.intel_db.conn.commit()

    summary = summarizer.summarize_cluster(cluster_id)

    assert summary is not None
    assert summary.memory_count == 0
    assert "no memories" in summary.summary.lower()


def test_summarize_cluster_llm_fallback(summarizer, mock_memory_client):
    """Test fallback when LLM times out"""
    # Create cluster
    cluster_id = "cluster-timeout"
    cursor = summarizer.intel_db.conn.cursor()
    cursor.execute("""
        INSERT INTO memory_clusters
        (id, name, description, memory_ids, cohesion_score, member_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cluster_id,
        "Timeout Cluster",
        None,
        json.dumps(["mem1", "mem2"]),
        0.75,
        2,
        int(datetime.now().timestamp()),
        int(datetime.now().timestamp())
    ))
    summarizer.intel_db.conn.commit()

    # Mock LLM timeout
    with patch('memory_system.intelligence.summarization._ask_claude', side_effect=Exception("Timeout")):
        summary = summarizer.summarize_cluster(cluster_id)

    assert summary is not None
    assert "unavailable" in summary.summary.lower() or "timeout" in summary.summary.lower()


# === Project Summary Tests ===

def test_summarize_project_basic(summarizer, mock_memory_client):
    """Test basic project summarization"""
    # Mock memories for project
    now = datetime.now()
    memories = [
        Mock(id=f"mem{i}", content=f"Project work {i}", created_at=now - timedelta(days=i), project_id="proj1")
        for i in range(10)
    ]
    mock_memory_client.search.return_value = memories

    # Mock LLM response
    with patch('memory_system.intelligence.summarization._ask_claude', return_value="Project made progress on features A, B, and C. Key decisions included architecture changes. No major blockers. Learned importance of test coverage."):
        summary = summarizer.summarize_project("proj1", days=30)

    assert summary is not None
    assert summary.summary_type == "project"
    assert summary.target_id == "proj1"
    assert summary.memory_count == 10
    assert summary.period_start is not None
    assert summary.period_end is not None
    assert "progress" in summary.summary.lower() or "project" in summary.summary.lower()


def test_summarize_project_insufficient_memories(summarizer, mock_memory_client):
    """Test project summarization with too few memories"""
    # Mock only 2 memories (below min_memories=5)
    now = datetime.now()
    memories = [
        Mock(id="mem1", content="Work 1", created_at=now, project_id="proj1"),
        Mock(id="mem2", content="Work 2", created_at=now, project_id="proj1")
    ]
    mock_memory_client.search.return_value = memories

    summary = summarizer.summarize_project("proj1", days=30, min_memories=5)
    assert summary is None


def test_summarize_project_date_filtering(summarizer, mock_memory_client):
    """Test project summarization filters by date correctly"""
    now = datetime.now()

    # Create memories: some in range, some out of range
    in_range = [
        Mock(id=f"in{i}", content=f"Recent {i}", created_at=now - timedelta(days=i), project_id="proj1")
        for i in range(10)
    ]
    out_of_range = [
        Mock(id=f"out{i}", content=f"Old {i}", created_at=now - timedelta(days=100+i), project_id="proj1")
        for i in range(5)
    ]

    mock_memory_client.search.return_value = in_range + out_of_range

    with patch('memory_system.intelligence.summarization._ask_claude', return_value="Summary of recent work."):
        summary = summarizer.summarize_project("proj1", days=30)

    # Should only count memories within 30 days
    assert summary is not None
    assert summary.memory_count == 10  # Only recent ones


# === Period Summary Tests ===

def test_summarize_period_basic(summarizer, mock_memory_client):
    """Test basic period summarization"""
    start = datetime(2025, 1, 1)
    end = datetime(2025, 1, 31)

    # Mock memories in period
    memories = [
        Mock(id=f"mem{i}", content=f"January work {i}", created_at=datetime(2025, 1, i+1))
        for i in range(10)
    ]
    mock_memory_client.search.return_value = memories

    with patch('memory_system.intelligence.summarization._ask_claude', return_value="**Testing theme**: Focused on test coverage improvements.\n**Development theme**: Implemented new features A and B.\n**Documentation theme**: Updated README and added examples."):
        summary = summarizer.summarize_period(start, end)

    assert summary is not None
    assert summary.summary_type == "period"
    assert summary.period_start == start
    assert summary.period_end == end
    assert summary.memory_count == 10
    assert len(summary.summary) > 50


def test_summarize_period_no_memories(summarizer, mock_memory_client):
    """Test period summarization with no memories"""
    start = datetime(2025, 1, 1)
    end = datetime(2025, 1, 31)

    mock_memory_client.search.return_value = []

    summary = summarizer.summarize_period(start, end)
    assert summary is None


def test_summarize_period_date_swap(summarizer, mock_memory_client):
    """Test period summarization swaps start/end if reversed"""
    end = datetime(2025, 1, 1)
    start = datetime(2025, 1, 31)  # Intentionally reversed

    memories = [
        Mock(id="mem1", content="Work", created_at=datetime(2025, 1, 15))
    ]
    mock_memory_client.search.return_value = memories

    with patch('memory_system.intelligence.summarization._ask_claude', return_value="Summary of period."):
        summary = summarizer.summarize_period(start, end)

    # Should have swapped dates
    assert summary is not None
    assert summary.period_start < summary.period_end


# === Summary Operations Tests ===

def test_get_summaries_filtered(summarizer):
    """Test filtering summaries by type, target, and date"""
    # Create multiple summaries
    now = datetime.now()

    summaries = [
        summarizer._create_summary("cluster", "Summary 1", 10, target_id="cluster-1"),
        summarizer._create_summary("project", "Summary 2", 20, target_id="proj-1", period_start=now-timedelta(days=30), period_end=now),
        summarizer._create_summary("period", "Summary 3", 15, period_start=now-timedelta(days=7), period_end=now),
    ]

    # Filter by type
    cluster_summaries = summarizer.get_summaries(summary_type="cluster")
    assert len(cluster_summaries) == 1
    assert cluster_summaries[0].summary_type == "cluster"

    # Filter by target
    proj_summaries = summarizer.get_summaries(target_id="proj-1")
    assert len(proj_summaries) == 1
    assert proj_summaries[0].target_id == "proj-1"

    # Filter by date
    recent_summaries = summarizer.get_summaries(after=now - timedelta(hours=1))
    assert len(recent_summaries) == 3  # All created just now


def test_regenerate_summary(summarizer, mock_memory_client):
    """Test regenerating an existing summary"""
    # Create a cluster and summary
    cluster_id = "cluster-regen"
    cursor = summarizer.intel_db.conn.cursor()
    cursor.execute("""
        INSERT INTO memory_clusters
        (id, name, description, memory_ids, cohesion_score, member_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cluster_id,
        "Regen Cluster",
        None,
        json.dumps(["mem1", "mem2"]),
        0.8,
        2,
        int(datetime.now().timestamp()),
        int(datetime.now().timestamp())
    ))
    summarizer.intel_db.conn.commit()

    # Create initial summary
    with patch('memory_system.intelligence.summarization._ask_claude', return_value="Original summary."):
        original = summarizer.summarize_cluster(cluster_id)

    original_id = original.id

    # Regenerate
    with patch('memory_system.intelligence.summarization._ask_claude', return_value="Regenerated summary."):
        regenerated = summarizer.regenerate_summary(original_id)

    assert regenerated is not None
    assert regenerated.id != original_id  # New ID
    assert regenerated.target_id == cluster_id  # Same cluster
    assert regenerated.summary != original.summary  # Different content

    # Original should be deleted
    assert summarizer.get_summary(original_id) is None


def test_get_summary_statistics(summarizer):
    """Test summary statistics calculation"""
    # Create summaries of different types
    summarizer._create_summary("cluster", "Summary 1", 10, target_id="cluster-1")
    summarizer._create_summary("cluster", "Summary 2", 15, target_id="cluster-1")
    summarizer._create_summary("project", "Summary 3", 20, target_id="proj-1")
    summarizer._create_summary("period", "Summary 4", 12)

    stats = summarizer.get_summary_statistics()

    assert stats["total_summaries"] == 4
    assert stats["by_type"]["cluster"] == 2
    assert stats["by_type"]["project"] == 1
    assert stats["by_type"]["period"] == 1
    assert stats["average_memory_count"] == 14.2  # (10+15+20+12)/4
    assert stats["most_summarized_target"]["id"] == "cluster-1"
    assert stats["most_summarized_target"]["count"] == 2


# === Edge Case Tests ===

def test_delete_summary(summarizer):
    """Test deleting a summary"""
    summary = summarizer._create_summary("cluster", "Test summary", 5, target_id="cluster-1")
    summary_id = summary.id

    # Verify exists
    assert summarizer.get_summary(summary_id) is not None

    # Delete
    result = summarizer.delete_summary(summary_id)
    assert result is True

    # Verify deleted
    assert summarizer.get_summary(summary_id) is None


def test_delete_summary_nonexistent(summarizer):
    """Test deleting nonexistent summary returns False"""
    result = summarizer.delete_summary("nonexistent-id")
    assert result is False
