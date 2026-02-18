"""
Tests for Feature 28: Memory Search Optimization

Test coverage:
- Initialization and schema creation
- Caching (miss, hit, expiry, invalidation)
- Ranking (basic, recency, importance)
- Selection recording
- Analytics (basic, top queries)
- Cache statistics
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
from datetime import datetime, timedelta
from dataclasses import dataclass
import sys

from memory_system.intelligence.search_optimizer import SearchOptimizer


@dataclass
class MockMemory:
    """Mock Memory object for testing"""
    id: str
    content: str
    created: str
    importance: float = 0.5
    semantic_score: float = 0.5
    keyword_score: float = 0.0


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    yield db_path

    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def optimizer(temp_db):
    """Create optimizer with temp database"""
    return SearchOptimizer(db_path=temp_db)


# === Initialization Tests ===

def test_optimizer_initialization(optimizer):
    """Test optimizer initializes database correctly"""
    with sqlite3.connect(optimizer.db_path) as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'search_cache' in table_names
        assert 'search_analytics' in table_names


# === Caching Tests ===

def test_cache_miss_first_search(optimizer):
    """Test first search is cache miss"""
    call_count = [0]

    def mock_search(query):
        call_count[0] += 1
        return [MockMemory("mem1", "test", datetime.now().isoformat())]

    results = optimizer.search_with_cache("test query", mock_search)

    assert len(results) == 1
    assert call_count[0] == 1  # Search function called


def test_cache_hit_second_search(optimizer, monkeypatch):
    """Test cache hit - search_fn should NOT be called on cache hit"""
    call_count = [0]
    stored_memories = []

    def mock_search(query):
        call_count[0] += 1
        mems = [
            MockMemory("mem1", "test", datetime.now().isoformat()),
            MockMemory("mem2", "test", datetime.now().isoformat()),
            MockMemory("mem3", "test", datetime.now().isoformat())
        ]
        stored_memories.clear()
        stored_memories.extend(mems)
        return mems

    # Mock the MemoryTSClient to return our stored memories
    class MockClient:
        def get(self, memory_id):
            for m in stored_memories:
                if m.id == memory_id:
                    return m
            raise FileNotFoundError(f"Memory {memory_id} not found")

    # Patch the import (save original to restore after test)
    import sys
    _orig_module = sys.modules.get('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'] = type(sys)('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'].MemoryTSClient = MockClient

    # First search - cache miss
    results1 = optimizer.search_with_cache("test query", mock_search)
    assert len(results1) == 3
    assert call_count[0] == 1  # Search function called

    # Check cache was created
    with sqlite3.connect(optimizer.db_path) as conn:
        row = conn.execute("SELECT hits FROM search_cache").fetchone()
        assert row[0] == 1  # First hit

    # Second search - cache hit (search_fn should NOT be called)
    results2 = optimizer.search_with_cache("test query", mock_search)

    # CRITICAL: search_fn should NOT be called on cache hit
    assert call_count[0] == 1  # Still 1 - search function NOT called again
    assert len(results2) == 3  # Should get 3 results from cache

    # Verify cache hit count increased
    with sqlite3.connect(optimizer.db_path) as conn:
        row = conn.execute("SELECT hits FROM search_cache").fetchone()
        assert row[0] == 2  # Second hit

    # Restore original module to prevent test pollution
    if _orig_module is not None:
        sys.modules['memory_system.memory_ts_client'] = _orig_module


def test_cache_respects_project_id(optimizer):
    """Test cache keys include project_id"""
    call_count = [0]

    def mock_search(query):
        call_count[0] += 1
        return [
            MockMemory("mem1", "test", datetime.now().isoformat()),
            MockMemory("mem2", "test", datetime.now().isoformat()),
            MockMemory("mem3", "test", datetime.now().isoformat())
        ]

    # Search with project_id=A
    optimizer.search_with_cache("test", mock_search, project_id="project_a")
    assert call_count[0] == 1

    # Same query, different project - should NOT use cache
    optimizer.search_with_cache("test", mock_search, project_id="project_b")
    assert call_count[0] == 2  # Search function called again


def test_cache_not_used_when_disabled(optimizer):
    """Test use_cache=False bypasses cache"""
    call_count = [0]

    def mock_search(query):
        call_count[0] += 1
        return [MockMemory("mem1", "test", datetime.now().isoformat())]

    # First search
    optimizer.search_with_cache("test", mock_search)
    assert call_count[0] == 1

    # Second search with cache disabled
    optimizer.search_with_cache("test", mock_search, use_cache=False)
    assert call_count[0] == 2  # Search function called again


def test_cache_only_stores_3_to_100_results(optimizer):
    """Test cache bounds (3-100 results)"""
    def mock_search_small(query):
        return [MockMemory("m1", "test", datetime.now().isoformat())]

    def mock_search_good(query):
        return [MockMemory(f"m{i}", "test", datetime.now().isoformat()) for i in range(10)]

    # Too few results - not cached
    optimizer.search_with_cache("small", mock_search_small)

    with sqlite3.connect(optimizer.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM search_cache WHERE query LIKE '%small%'").fetchone()[0]
        assert count == 0

    # Good range - cached
    optimizer.search_with_cache("good", mock_search_good)

    with sqlite3.connect(optimizer.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM search_cache WHERE query LIKE '%good%'").fetchone()[0]
        assert count == 1


def test_cache_expiry(optimizer):
    """Test cache TTL expiration"""
    def mock_search(query):
        return [MockMemory(f"m{i}", "test", datetime.now().isoformat()) for i in range(5)]

    # First search - cached
    optimizer.search_with_cache("test", mock_search)

    # Manually expire the cache entry
    with sqlite3.connect(optimizer.db_path) as conn:
        past = int((datetime.now() - timedelta(days=2)).timestamp())
        conn.execute("UPDATE search_cache SET expires_at = ?", (past,))
        conn.commit()

    # Should not use expired cache
    call_count = [0]

    def counting_search(query):
        call_count[0] += 1
        return mock_search(query)

    optimizer.search_with_cache("test", counting_search)
    assert call_count[0] == 1  # Search function called (cache expired)


def test_cache_invalidation(optimizer):
    """Test cache invalidation with correct composite key"""
    def mock_search(query):
        return [MockMemory(f"m{i}", "test", datetime.now().isoformat()) for i in range(5)]

    # Cache a query
    optimizer.search_with_cache("test", mock_search)

    # Verify cached
    with sqlite3.connect(optimizer.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        assert count == 1

    # Invalidate using correct format (query + project_id)
    optimizer.invalidate_cache("test", project_id=None)  # project_id=None → "global"

    # Verify removed
    with sqlite3.connect(optimizer.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        assert count == 0


def test_cache_efficiency(optimizer):
    """Test cache prevents redundant search_fn calls"""
    call_count = [0]
    stored_memories = []

    def mock_search(query):
        call_count[0] += 1
        mems = [MockMemory(f"m{i}", "test", datetime.now().isoformat()) for i in range(5)]
        stored_memories.clear()
        stored_memories.extend(mems)
        return mems

    # Mock the MemoryTSClient to return our stored memories
    class MockClient:
        def get(self, memory_id):
            for m in stored_memories:
                if m.id == memory_id:
                    return m
            raise FileNotFoundError(f"Memory {memory_id} not found")

    # Patch the import (save original to restore after test)
    import sys
    _orig_module = sys.modules.get('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'] = type(sys)('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'].MemoryTSClient = MockClient

    # First search - cache miss
    optimizer.search_with_cache("test", mock_search)
    assert call_count[0] == 1

    # Next 10 searches - all cache hits (should NOT call search_fn)
    for _ in range(10):
        optimizer.search_with_cache("test", mock_search)

    # Verify search_fn only called once (cache working)
    assert call_count[0] == 1

    # Verify cache hit count
    with sqlite3.connect(optimizer.db_path) as conn:
        row = conn.execute("SELECT hits FROM search_cache").fetchone()
        assert row[0] == 11  # 1 initial + 10 cache hits

    # Restore original module to prevent test pollution
    if _orig_module is not None:
        sys.modules['memory_system.memory_ts_client'] = _orig_module


# === Ranking Tests ===

def test_rank_results_basic(optimizer):
    """Test basic ranking"""
    memories = [
        MockMemory("m1", "old", (datetime.now() - timedelta(days=365)).isoformat(), importance=0.3),
        MockMemory("m2", "new", datetime.now().isoformat(), importance=0.9),
    ]

    ranked = optimizer.rank_results(memories)

    # New + important should rank higher
    assert ranked[0].id == "m2"
    assert ranked[1].id == "m1"


def test_rank_results_recency(optimizer):
    """Test recency component"""
    old_date = (datetime.now() - timedelta(days=365)).isoformat()
    new_date = datetime.now().isoformat()

    memories = [
        MockMemory("old", "content", old_date, importance=0.5, semantic_score=0.5),
        MockMemory("new", "content", new_date, importance=0.5, semantic_score=0.5),
    ]

    ranked = optimizer.rank_results(memories)

    # Newer should rank higher (all else equal)
    assert ranked[0].id == "new"


def test_rank_results_no_negative_recency(optimizer):
    """Test recency score clamped at 0 for old memories"""
    very_old_date = (datetime.now() - timedelta(days=730)).isoformat()  # 2 years

    memory = MockMemory("m1", "content", very_old_date)

    # Should not crash or produce negative scores
    ranked = optimizer.rank_results([memory])
    assert len(ranked) == 1


# === Selection Recording Tests ===

def test_record_selection(optimizer):
    """Test recording user selection"""
    optimizer.record_selection("test query", "mem1", position=3, result_count=10)

    with sqlite3.connect(optimizer.db_path) as conn:
        row = conn.execute(
            "SELECT query, selected_memory_id, position FROM search_analytics"
        ).fetchone()

        assert row[0] == "test query"
        assert row[1] == "mem1"
        assert row[2] == 3


# === Analytics Tests ===

def test_get_search_analytics(optimizer):
    """Test search analytics"""
    # Record some searches
    optimizer.record_selection("query1", "mem1", 1, 5)
    optimizer.record_selection("query2", "mem2", 2, 8)
    optimizer.record_selection("query1", "mem3", 3, 5)

    analytics = optimizer.get_search_analytics(days=7)

    assert analytics['total_searches'] == 3
    assert "query1" in analytics['top_queries']


def test_get_cache_stats(optimizer):
    """Test cache statistics"""
    stored_memories = []

    def mock_search(query):
        mems = [MockMemory(f"m{i}-{query}", "test", datetime.now().isoformat()) for i in range(5)]
        stored_memories.clear()
        stored_memories.extend(mems)
        return mems

    # Mock the MemoryTSClient to return our stored memories
    class MockClient:
        def get(self, memory_id):
            for m in stored_memories:
                if m.id == memory_id:
                    return m
            raise FileNotFoundError(f"Memory {memory_id} not found")

    # Patch the import (save original to restore after test)
    import sys
    _orig_module = sys.modules.get('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'] = type(sys)('memory_system.memory_ts_client')
    sys.modules['memory_system.memory_ts_client'].MemoryTSClient = MockClient

    # Create some cache entries
    optimizer.search_with_cache("test1", mock_search)
    optimizer.search_with_cache("test2", mock_search)

    # Hit one multiple times
    optimizer.search_with_cache("test1", mock_search)
    optimizer.search_with_cache("test1", mock_search)

    stats = optimizer.get_cache_stats()

    assert stats['total_entries'] == 2
    assert stats['total_hits'] >= 2  # test1 hit at least twice

    # Restore original module to prevent test pollution
    if _orig_module is not None:
        sys.modules['memory_system.memory_ts_client'] = _orig_module
