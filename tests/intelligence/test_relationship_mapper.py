"""
Tests for Feature 24: Memory Relationship Mapping

Test coverage:
- Initialization and schema creation
- Link creation (basic, duplicates, invalid types, invalid strength)
- Retrieval (directional queries, filtering)
- Causal chain finding (direct, multi-hop, not found, max depth)
- Contradiction detection
- Updates and deletions
- Statistics (global and per-memory)
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
from datetime import datetime
from memory_system.intelligence.relationship_mapper import (
    RelationshipMapper,
    MemoryRelationship
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def mapper(temp_db):
    """Create mapper with temp database"""
    return RelationshipMapper(db_path=temp_db)


# === Initialization Tests ===

def test_mapper_initialization(mapper):
    """Test mapper initializes database correctly"""
    # Check tables exist
    with sqlite3.connect(mapper.db_path) as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'memory_relationships' in table_names


def test_schema_constraints(mapper):
    """Test database constraints work"""
    # Create relationship
    rel_id = mapper.link_memories("mem1", "mem2", "causal", "test")

    # Try to create duplicate (same from, to, type)
    rel_id2 = mapper.link_memories("mem1", "mem2", "causal", "duplicate test")

    # Should be same ID (UNIQUE constraint prevents duplicate)
    assert rel_id == rel_id2


# === Link Creation Tests ===

def test_link_memories_basic(mapper):
    """Test creating simple relationship"""
    rel_id = mapper.link_memories(
        from_id="mem1",
        to_id="mem2",
        relationship_type="causal",
        evidence="Test evidence",
        strength=0.8
    )

    assert rel_id is not None
    assert len(rel_id) == 16  # MD5 hash truncated to 16 chars


def test_link_memories_duplicate(mapper):
    """Test UNIQUE constraint prevents duplicates"""
    # Create relationship
    rel_id1 = mapper.link_memories("mem1", "mem2", "causal", "first")

    # Try to create duplicate
    rel_id2 = mapper.link_memories("mem1", "mem2", "causal", "second")

    # Should return same ID (INSERT OR IGNORE)
    assert rel_id1 == rel_id2


def test_link_memories_invalid_type(mapper):
    """Test ValueError on invalid relationship_type"""
    with pytest.raises(ValueError, match="Invalid relationship_type"):
        mapper.link_memories("mem1", "mem2", "invalid_type", "test")


def test_link_memories_invalid_strength(mapper):
    """Test ValueError on strength out of range"""
    with pytest.raises(ValueError, match="Strength must be 0.0-1.0"):
        mapper.link_memories("mem1", "mem2", "causal", "test", strength=1.5)

    with pytest.raises(ValueError, match="Strength must be 0.0-1.0"):
        mapper.link_memories("mem1", "mem2", "causal", "test", strength=-0.1)


def test_link_bidirectional(mapper):
    """Test A→B and B→A can both exist"""
    rel_id1 = mapper.link_memories("mem1", "mem2", "supports", "A supports B")
    rel_id2 = mapper.link_memories("mem2", "mem1", "supports", "B supports A")

    # Different IDs (different directions)
    assert rel_id1 != rel_id2


# === Retrieval Tests ===

def test_get_related_from(mapper):
    """Test direction='from' only returns outgoing relationships"""
    # Create: mem1 → mem2, mem3 → mem1
    mapper.link_memories("mem1", "mem2", "causal", "test1")
    mapper.link_memories("mem3", "mem1", "causal", "test2")

    # Query outgoing from mem1
    related = mapper.get_related_memories("mem1", direction="from")

    # Should only find mem2 (outgoing)
    assert len(related) == 1
    assert related[0][0] == "mem2"


def test_get_related_to(mapper):
    """Test direction='to' only returns incoming relationships"""
    # Create: mem1 → mem2, mem3 → mem1
    mapper.link_memories("mem1", "mem2", "causal", "test1")
    mapper.link_memories("mem3", "mem1", "causal", "test2")

    # Query incoming to mem1
    related = mapper.get_related_memories("mem1", direction="to")

    # Should only find mem3 (incoming)
    assert len(related) == 1
    assert related[0][0] == "mem3"


def test_get_related_both(mapper):
    """Test direction='both' returns all relationships"""
    # Create: mem1 → mem2, mem3 → mem1
    mapper.link_memories("mem1", "mem2", "causal", "test1")
    mapper.link_memories("mem3", "mem1", "causal", "test2")

    # Query both directions
    related = mapper.get_related_memories("mem1", direction="both")

    # Should find both mem2 and mem3
    assert len(related) == 2
    related_ids = {r[0] for r in related}
    assert related_ids == {"mem2", "mem3"}


def test_get_related_filtered_by_type(mapper):
    """Test filtering by relationship_type"""
    # Create multiple types
    mapper.link_memories("mem1", "mem2", "causal", "test1")
    mapper.link_memories("mem1", "mem3", "contradicts", "test2")
    mapper.link_memories("mem1", "mem4", "supports", "test3")

    # Query only causal
    related = mapper.get_related_memories("mem1", relationship_type="causal")

    assert len(related) == 1
    assert related[0][0] == "mem2"


def test_get_related_empty(mapper):
    """Test querying memory with no relationships"""
    related = mapper.get_related_memories("nonexistent")
    assert len(related) == 0


# === Causal Chain Tests ===

def test_find_causal_chain_direct(mapper):
    """Test finding direct causal link A→B"""
    mapper.link_memories("memA", "memB", "causal", "A causes B")

    chain = mapper.find_causal_chain("memA", "memB")

    assert chain == ["memA", "memB"]


def test_find_causal_chain_multi_hop(mapper):
    """Test finding multi-hop chain A→B→C"""
    mapper.link_memories("memA", "memB", "causal", "A→B")
    mapper.link_memories("memB", "memC", "causal", "B→C")

    chain = mapper.find_causal_chain("memA", "memC")

    assert chain == ["memA", "memB", "memC"]


def test_find_causal_chain_not_found(mapper):
    """Test no path returns None"""
    mapper.link_memories("memA", "memB", "causal", "A→B")
    mapper.link_memories("memC", "memD", "causal", "C→D")

    # No path from A to D
    chain = mapper.find_causal_chain("memA", "memD")

    assert chain is None


def test_find_causal_chain_max_depth(mapper):
    """Test max_depth limit respected"""
    # Create chain: A→B→C→D→E (length 5)
    mapper.link_memories("memA", "memB", "causal", "A→B")
    mapper.link_memories("memB", "memC", "causal", "B→C")
    mapper.link_memories("memC", "memD", "causal", "C→D")
    mapper.link_memories("memD", "memE", "causal", "D→E")

    # Find with max_depth=3 (can't reach E from A)
    chain = mapper.find_causal_chain("memA", "memE", max_depth=3)

    assert chain is None


def test_find_causal_chain_circular(mapper):
    """Test circular references handled (no infinite loop)"""
    # Create cycle: A→B→C→A
    mapper.link_memories("memA", "memB", "causal", "A→B")
    mapper.link_memories("memB", "memC", "causal", "B→C")
    mapper.link_memories("memC", "memA", "causal", "C→A")

    # Should find shortest path (or return None if target unreachable)
    chain = mapper.find_causal_chain("memA", "memC")

    # Should find path (BFS handles visited set)
    assert chain is not None
    assert chain == ["memA", "memB", "memC"]


# === Contradiction Tests ===

def test_detect_contradictions(mapper):
    """Test finding contradicting memories"""
    mapper.link_memories("mem1", "mem2", "contradicts", "They conflict")

    # Check from mem1
    contradictions = mapper.detect_contradictions("mem1")
    assert len(contradictions) == 1
    assert contradictions[0][0] == "mem2"

    # Check from mem2 (bidirectional)
    contradictions = mapper.detect_contradictions("mem2")
    assert len(contradictions) == 1
    assert contradictions[0][0] == "mem1"


def test_detect_contradictions_multiple(mapper):
    """Test detecting multiple contradictions"""
    mapper.link_memories("mem1", "mem2", "contradicts", "conflict1")
    mapper.link_memories("mem1", "mem3", "contradicts", "conflict2")
    mapper.link_memories("mem4", "mem1", "contradicts", "conflict3")

    contradictions = mapper.detect_contradictions("mem1")

    # Should find all 3
    assert len(contradictions) == 3
    related_ids = {c[0] for c in contradictions}
    assert related_ids == {"mem2", "mem3", "mem4"}


# === Update & Delete Tests ===

def test_update_strength(mapper):
    """Test updating relationship strength"""
    rel_id = mapper.link_memories("mem1", "mem2", "causal", "test", strength=0.5)

    # Update strength
    mapper.update_strength(rel_id, 0.9)

    # Verify updated
    related = mapper.get_related_memories("mem1")
    assert related[0][1].strength == 0.9


def test_update_strength_invalid(mapper):
    """Test ValueError on invalid strength update"""
    rel_id = mapper.link_memories("mem1", "mem2", "causal", "test")

    with pytest.raises(ValueError, match="Strength must be 0.0-1.0"):
        mapper.update_strength(rel_id, 1.5)


def test_update_strength_not_found(mapper):
    """Test ValueError on non-existent relationship"""
    with pytest.raises(ValueError, match="not found"):
        mapper.update_strength("nonexistent", 0.8)


def test_remove_relationship(mapper):
    """Test removing relationship"""
    rel_id = mapper.link_memories("mem1", "mem2", "causal", "test")

    # Remove
    removed = mapper.remove_relationship(rel_id)
    assert removed is True

    # Verify gone
    related = mapper.get_related_memories("mem1")
    assert len(related) == 0


def test_remove_relationship_not_found(mapper):
    """Test removing non-existent relationship returns False"""
    removed = mapper.remove_relationship("nonexistent")
    assert removed is False


# === Statistics Tests ===

def test_get_relationship_stats(mapper):
    """Test global statistics"""
    # Create some relationships
    mapper.link_memories("mem1", "mem2", "causal", "test1", strength=0.8)
    mapper.link_memories("mem2", "mem3", "causal", "test2", strength=0.6)
    mapper.link_memories("mem3", "mem4", "contradicts", "test3", strength=0.9)

    stats = mapper.get_relationship_stats()

    assert stats['total_relationships'] == 3
    assert stats['by_type']['causal'] == 2
    assert stats['by_type']['contradicts'] == 1
    assert 0.7 < stats['average_strength'] < 0.8  # (0.8 + 0.6 + 0.9) / 3 ≈ 0.77


def test_get_relationship_stats_empty(mapper):
    """Test statistics with no relationships"""
    stats = mapper.get_relationship_stats()

    assert stats['total_relationships'] == 0
    assert stats['by_type'] == {}
    assert stats['average_strength'] == 0.0


def test_get_memory_graph_stats(mapper):
    """Test per-memory statistics"""
    # Create: mem1 → mem2, mem3 → mem2, mem2 → mem4
    # mem2 has 1 outgoing, 2 incoming
    mapper.link_memories("mem1", "mem2", "causal", "test1")
    mapper.link_memories("mem3", "mem2", "supports", "test2")
    mapper.link_memories("mem2", "mem4", "related", "test3")

    stats = mapper.get_memory_graph_stats("mem2")

    assert stats['outgoing_count'] == 1
    assert stats['incoming_count'] == 2
    assert stats['total_connections'] == 3
    assert stats['contradiction_count'] == 0
    assert 0 < stats['centrality_score'] <= 1.0


def test_get_memory_graph_stats_contradictions(mapper):
    """Test contradiction count in graph stats"""
    mapper.link_memories("mem1", "mem2", "contradicts", "conflict1")
    mapper.link_memories("mem3", "mem1", "contradicts", "conflict2")

    stats = mapper.get_memory_graph_stats("mem1")

    assert stats['contradiction_count'] == 2
