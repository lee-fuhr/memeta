"""
Tests for Feature 25: Memory Relationships Graph
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from intelligence.relationships import MemoryRelationships, MemoryRelationship


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def relationships(temp_db):
    """Create relationships instance with temp database."""
    return MemoryRelationships(db_path=temp_db)


def test_init_creates_table(relationships, temp_db):
    """Test that initialization creates required table."""
    from db_pool import get_connection

    with get_connection(temp_db) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='memory_relationships'
        """)
        tables = {row[0] for row in cursor.fetchall()}

    assert "memory_relationships" in tables


def test_add_relationship(relationships):
    """Test adding a relationship."""
    rel = relationships.add_relationship(
        from_memory="mem_001",
        to_memory="mem_002",
        relationship_type="led_to",
        weight=0.9,
        auto_detected=False
    )

    assert rel.from_memory_id == "mem_001"
    assert rel.to_memory_id == "mem_002"
    assert rel.relationship_type == "led_to"
    assert abs(rel.weight - 0.9) < 0.001
    assert rel.auto_detected is False


def test_add_relationship_duplicate_updates(relationships):
    """Test that adding duplicate relationship updates existing."""
    # Add first
    rel1 = relationships.add_relationship("mem_001", "mem_002", "led_to", 0.5)

    # Add again with different weight
    rel2 = relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)

    # Should update, not create new
    assert rel1.id == rel2.id
    assert abs(rel2.weight - 0.9) < 0.001


def test_get_relationship(relationships):
    """Test retrieving relationship by ID."""
    rel = relationships.add_relationship("mem_001", "mem_002", "supports", 0.8)

    retrieved = relationships.get_relationship(rel.id)

    assert retrieved is not None
    assert retrieved.id == rel.id
    assert retrieved.from_memory_id == "mem_001"
    assert retrieved.to_memory_id == "mem_002"
    assert retrieved.relationship_type == "supports"


def test_get_relationship_nonexistent(relationships):
    """Test retrieving nonexistent relationship returns None."""
    rel = relationships.get_relationship(999)
    assert rel is None


def test_get_relationships_outgoing(relationships):
    """Test getting outgoing relationships."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "references", 0.7)
    relationships.add_relationship("mem_004", "mem_001", "supports", 0.5)

    outgoing = relationships.get_relationships("mem_001", direction="outgoing")

    assert len(outgoing) == 2
    # Should be sorted by weight descending
    assert outgoing[0].to_memory_id == "mem_002"
    assert outgoing[1].to_memory_id == "mem_003"


def test_get_relationships_incoming(relationships):
    """Test getting incoming relationships."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_003", "mem_002", "supports", 0.8)
    relationships.add_relationship("mem_002", "mem_004", "references", 0.5)

    incoming = relationships.get_relationships("mem_002", direction="incoming")

    assert len(incoming) == 2
    assert incoming[0].from_memory_id == "mem_001"
    assert incoming[1].from_memory_id == "mem_003"


def test_get_relationships_both(relationships):
    """Test getting relationships in both directions."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_002", "mem_003", "references", 0.8)

    both = relationships.get_relationships("mem_002", direction="both")

    assert len(both) == 2


def test_get_relationships_by_type(relationships):
    """Test filtering relationships by type."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "contradicts", 0.8)
    relationships.add_relationship("mem_001", "mem_004", "led_to", 0.7)

    led_to_only = relationships.get_relationships(
        "mem_001",
        relationship_type="led_to",
        direction="outgoing"
    )

    assert len(led_to_only) == 2
    assert all(r.relationship_type == "led_to" for r in led_to_only)


def test_get_predecessors(relationships):
    """Test getting causal predecessors."""
    relationships.add_relationship("mem_001", "mem_003", "led_to", 0.9)
    relationships.add_relationship("mem_002", "mem_003", "led_to", 0.8)

    predecessors = relationships.get_predecessors("mem_003")

    assert len(predecessors) == 2
    assert "mem_001" in predecessors
    assert "mem_002" in predecessors


def test_get_successors(relationships):
    """Test getting causal successors."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "led_to", 0.8)

    successors = relationships.get_successors("mem_001")

    assert len(successors) == 2
    assert "mem_002" in successors
    assert "mem_003" in successors


def test_get_contradictions(relationships):
    """Test finding contradictions (bidirectional)."""
    relationships.add_relationship("mem_001", "mem_002", "contradicts", 0.9)
    relationships.add_relationship("mem_003", "mem_001", "contradicts", 0.8)

    contradictions = relationships.get_contradictions("mem_001")

    assert len(contradictions) == 2
    assert "mem_002" in contradictions
    assert "mem_003" in contradictions


def test_get_references(relationships):
    """Test getting referenced memories."""
    relationships.add_relationship("mem_001", "mem_002", "references", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "references", 0.8)

    references = relationships.get_references("mem_001")

    assert len(references) == 2
    assert "mem_002" in references
    assert "mem_003" in references


def test_get_cited_by(relationships):
    """Test getting memories that cite this one."""
    relationships.add_relationship("mem_001", "mem_003", "references", 0.9)
    relationships.add_relationship("mem_002", "mem_003", "references", 0.8)

    citations = relationships.get_cited_by("mem_003")

    assert len(citations) == 2
    assert "mem_001" in citations
    assert "mem_002" in citations


def test_remove_relationship(relationships):
    """Test removing a relationship."""
    rel = relationships.add_relationship("mem_001", "mem_002", "supports", 0.8)

    removed = relationships.remove_relationship(rel.id)
    assert removed is True

    # Verify it's gone
    retrieved = relationships.get_relationship(rel.id)
    assert retrieved is None


def test_remove_relationship_nonexistent(relationships):
    """Test removing nonexistent relationship returns False."""
    removed = relationships.remove_relationship(999)
    assert removed is False


def test_get_memory_graph_depth_1(relationships):
    """Test getting graph with max depth 1 (direct connections only)."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_002", "mem_003", "led_to", 0.8)
    relationships.add_relationship("mem_001", "mem_004", "references", 0.7)

    graph = relationships.get_memory_graph("mem_001", max_depth=1)

    # Should include mem_001, mem_002, mem_004 (not mem_003 - 2 hops away)
    assert "mem_001" in graph["nodes"]
    assert "mem_002" in graph["nodes"]
    assert "mem_004" in graph["nodes"]
    assert "mem_003" not in graph["nodes"]

    assert len(graph["edges"]) == 2


def test_get_memory_graph_depth_2(relationships):
    """Test getting graph with max depth 2."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_002", "mem_003", "led_to", 0.8)
    relationships.add_relationship("mem_003", "mem_004", "led_to", 0.7)

    graph = relationships.get_memory_graph("mem_001", max_depth=2)

    # Should include up to 2 hops
    assert "mem_001" in graph["nodes"]
    assert "mem_002" in graph["nodes"]
    assert "mem_003" in graph["nodes"]
    assert "mem_004" not in graph["nodes"]  # 3 hops away

    assert len(graph["edges"]) == 2


def test_get_memory_graph_filtered_types(relationships):
    """Test graph with relationship type filtering."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "contradicts", 0.8)
    relationships.add_relationship("mem_001", "mem_004", "led_to", 0.7)

    graph = relationships.get_memory_graph(
        "mem_001",
        max_depth=1,
        relationship_types=["led_to"]
    )

    # Should only include led_to relationships
    assert "mem_002" in graph["nodes"]
    assert "mem_004" in graph["nodes"]
    assert "mem_003" not in graph["nodes"]  # contradicts filtered out


def test_get_relationship_count(relationships):
    """Test counting relationships for a memory."""
    relationships.add_relationship("mem_001", "mem_002", "led_to", 0.9)
    relationships.add_relationship("mem_001", "mem_003", "references", 0.8)
    relationships.add_relationship("mem_004", "mem_001", "supports", 0.7)

    count = relationships.get_relationship_count("mem_001")

    assert count == 3  # 2 outgoing + 1 incoming


def test_get_relationship_count_zero(relationships):
    """Test count for memory with no relationships."""
    count = relationships.get_relationship_count("nonexistent")
    assert count == 0
