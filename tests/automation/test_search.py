"""
Tests for Feature 30: Memory-Aware Search
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from automation.search import MemoryAwareSearch, SearchQuery, SearchResult
from memory_ts_client import MemoryTSClient, Memory


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def search(temp_db):
    """Create search instance."""
    return MemoryAwareSearch(db_path=temp_db)


@pytest.fixture
def mock_memories():
    """Create mock memories for testing."""
    now = datetime.now()

    return [
        Memory(
            id="mem_001",
            content="Client feedback about the new design",
            importance=0.8,
            tags=["client", "design"],
            project_id="ProjectA",
            created=now - timedelta(days=2)
        ),
        Memory(
            id="mem_002",
            content="API integration deadline is next Friday",
            importance=0.9,
            tags=["deadline", "urgent"],
            project_id="ProjectB",
            created=now - timedelta(days=5)
        ),
        Memory(
            id="mem_003",
            content="Minor fix for button styling",
            importance=0.3,
            tags=["fix", "ui"],
            project_id="ProjectA",
            created=now - timedelta(days=1)
        ),
        Memory(
            id="mem_004",
            content="Important meeting notes from January",
            importance=0.7,
            tags=["meeting", "notes"],
            project_id="ProjectC",
            created=datetime(2026, 1, 15)
        )
    ]


def test_init_creates_tables(search, temp_db):
    """Test initialization creates search history table."""
    from db_pool import get_connection

    with get_connection(temp_db) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='search_history'
        """)
        tables = {row[0] for row in cursor.fetchall()}

    assert "search_history" in tables


def test_simple_search(search, monkeypatch, mock_memories):
    """Test simple content search."""
    # Mock client.search to return our test memories
    def mock_search(*args, **kwargs):
        return [mock_memories[0]]

    monkeypatch.setattr(search.client, "search", mock_search)

    results = search.search("design", limit=10)

    assert len(results) == 1
    assert results[0].memory.content == "Client feedback about the new design"
    assert results[0].match_reason == "Content match"


def test_parse_natural_query_last_week(search):
    """Test parsing 'last week' from natural query."""
    query = "Find memories about design from last week"

    parsed = search.parse_natural_query(query)

    assert parsed.text_query is not None
    assert parsed.date_start is not None
    assert (datetime.now() - parsed.date_start).days <= 7


def test_parse_natural_query_last_month(search):
    """Test parsing 'last month' from natural query."""
    query = "What did I learn about APIs last month?"

    parsed = search.parse_natural_query(query)

    assert parsed.date_start is not None
    assert (datetime.now() - parsed.date_start).days <= 30


def test_parse_natural_query_important(search):
    """Test parsing importance indicator."""
    query = "Show me important memories about clients"

    parsed = search.parse_natural_query(query)

    assert parsed.min_importance == 0.7


def test_parse_natural_query_month_name(search):
    """Test parsing month names."""
    query = "Memories from January"

    parsed = search.parse_natural_query(query)

    assert parsed.date_start is not None
    assert parsed.date_start.month == 1
    assert parsed.date_end is not None


def test_parse_natural_query_project(search):
    """Test extracting project ID."""
    query = "Find memories in ProjectA"

    parsed = search.parse_natural_query(query)

    assert parsed.project_id == "ProjectA"


def test_parse_natural_query_tags(search):
    """Test extracting tags with # prefix."""
    query = "Show me #urgent and #deadline memories"

    parsed = search.parse_natural_query(query)

    assert parsed.tags is not None
    assert "urgent" in parsed.tags
    assert "deadline" in parsed.tags


def test_parse_natural_query_recency_order(search):
    """Test detecting recency ordering."""
    query = "Show me recent memories about design"

    parsed = search.parse_natural_query(query)

    assert parsed.order_by == "recency"


def test_parse_natural_query_today(search):
    """Test parsing 'today' temporal reference."""
    query = "What happened today?"

    parsed = search.parse_natural_query(query)

    assert parsed.date_start is not None
    now = datetime.now()
    assert parsed.date_start.date() == now.date()


def test_parse_natural_query_yesterday(search):
    """Test parsing 'yesterday' temporal reference."""
    query = "Show me memories from yesterday"

    parsed = search.parse_natural_query(query)

    assert parsed.date_start is not None
    assert parsed.date_end is not None


def test_get_search_history(search):
    """Test retrieving search history."""
    import time
    # Perform some searches to populate history
    search._log_search("test query 1", {"min_importance": 0.7}, 5)
    time.sleep(1.01)  # Ensure different second timestamps
    search._log_search("test query 2", {}, 10)

    history = search.get_search_history(limit=10)

    assert len(history) == 2
    # Check that both queries are in history
    query_texts = {h['query_text'] for h in history}
    assert "test query 1" in query_texts
    assert "test query 2" in query_texts
    # Most recent should be first (query 2)
    assert history[0]['query_text'] == "test query 2"
    assert history[0]['results_count'] == 10


def test_search_history_limit(search):
    """Test search history respects limit."""
    # Create more than limit
    for i in range(15):
        search._log_search(f"query {i}", {}, i)

    history = search.get_search_history(limit=5)

    assert len(history) == 5


def test_calculate_relevance_importance(search, mock_memories):
    """Test relevance calculation by importance."""
    mem = mock_memories[0]
    score = search._calculate_relevance(mem, None, "importance")

    assert score == mem.importance


def test_calculate_relevance_recency(search, mock_memories):
    """Test relevance calculation by recency."""
    mem = mock_memories[0]
    score = search._calculate_relevance(mem, None, "recency")

    assert score > 0
    assert score == mem.created.timestamp()


def test_calculate_relevance_combined(search, mock_memories):
    """Test combined relevance calculation."""
    mem = mock_memories[0]
    score = search._calculate_relevance(mem, "query", "relevance")

    # Should be weighted combination
    assert 0 < score <= 1
