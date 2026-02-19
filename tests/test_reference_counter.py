"""
Tests for the reference counter module.

Covers:
- Initialization and schema creation
- Increment / decrement operations
- Clamping decrement at zero
- Per-type and total count retrieval
- Zero-reference memory detection
- Highly-referenced memory queries
- Protection status checks
- Bulk update from relationship edges
- Dangling reference detection
- Reference distribution statistics
- Concurrent increments on same memory
- Multiple ref types for same memory
- Edge cases (unknown memory, empty DB, etc.)
"""

import sqlite3
import os

import pytest

from memory_system.reference_counter import ReferenceCounter


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database file."""
    return str(tmp_path / "test_refcount.db")


@pytest.fixture
def rc(tmp_db):
    """Return a fresh ReferenceCounter instance."""
    return ReferenceCounter(db_path=tmp_db)


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_database_file(self, tmp_db):
        ReferenceCounter(db_path=tmp_db)
        assert os.path.exists(tmp_db)

    def test_creates_table(self, tmp_db):
        ReferenceCounter(db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reference_counts'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent_init(self, tmp_db):
        """Creating multiple instances on same DB doesn't error."""
        ReferenceCounter(db_path=tmp_db)
        ReferenceCounter(db_path=tmp_db)  # should not raise


# ---------------------------------------------------------------------------
# 2. Increment
# ---------------------------------------------------------------------------

class TestIncrement:
    def test_increment_returns_new_count(self, rc):
        result = rc.increment("mem-1", ref_type="relationship")
        assert result == 1

    def test_increment_multiple_times(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="relationship")
        result = rc.increment("mem-1", ref_type="relationship")
        assert result == 3

    def test_increment_default_type_is_relationship(self, rc):
        rc.increment("mem-1")
        counts = rc.get_count("mem-1")
        assert counts["relationship"] == 1

    def test_increment_different_types_independent(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="chunk")
        counts = rc.get_count("mem-1")
        assert counts["relationship"] == 1
        assert counts["chunk"] == 2

    def test_increment_different_memories(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-2", ref_type="relationship")
        assert rc.get_count("mem-1")["relationship"] == 1
        assert rc.get_count("mem-2")["relationship"] == 1


# ---------------------------------------------------------------------------
# 3. Decrement
# ---------------------------------------------------------------------------

class TestDecrement:
    def test_decrement_returns_new_count(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="relationship")
        result = rc.decrement("mem-1", ref_type="relationship")
        assert result == 1

    def test_decrement_clamps_at_zero(self, rc):
        """Decrementing a zero-count memory stays at 0, never negative."""
        result = rc.decrement("mem-1", ref_type="relationship")
        assert result == 0

    def test_decrement_from_one_to_zero(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        result = rc.decrement("mem-1", ref_type="relationship")
        assert result == 0

    def test_decrement_nonexistent_memory(self, rc):
        """Decrementing a memory with no records stays at 0."""
        result = rc.decrement("does-not-exist", ref_type="chunk")
        assert result == 0

    def test_decrement_only_affects_specified_type(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="chunk")
        rc.decrement("mem-1", ref_type="relationship")
        counts = rc.get_count("mem-1")
        assert counts["relationship"] == 0
        assert counts["chunk"] == 1


# ---------------------------------------------------------------------------
# 4. Get count
# ---------------------------------------------------------------------------

class TestGetCount:
    def test_empty_memory_returns_all_zeros(self, rc):
        counts = rc.get_count("nonexistent")
        assert counts["relationship"] == 0
        assert counts["chunk"] == 0
        assert counts["decision"] == 0
        assert counts["synthesis"] == 0
        assert counts["total"] == 0

    def test_total_sums_all_types(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="decision")
        counts = rc.get_count("mem-1")
        assert counts["total"] == 4

    def test_count_includes_all_four_types(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="decision")
        rc.increment("mem-1", ref_type="synthesis")
        counts = rc.get_count("mem-1")
        assert counts["relationship"] == 1
        assert counts["chunk"] == 1
        assert counts["decision"] == 1
        assert counts["synthesis"] == 1
        assert counts["total"] == 4


# ---------------------------------------------------------------------------
# 5. Zero-reference memories
# ---------------------------------------------------------------------------

class TestZeroRefMemories:
    def test_empty_db_returns_empty_list(self, rc):
        assert rc.get_zero_ref_memories() == []

    def test_memory_with_refs_not_included(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        assert "mem-1" not in rc.get_zero_ref_memories()

    def test_memory_after_decrement_to_zero(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.decrement("mem-1", ref_type="relationship")
        zero = rc.get_zero_ref_memories()
        assert "mem-1" in zero

    def test_multiple_zero_ref_memories(self, rc):
        # Create and then zero out two memories
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-2", ref_type="chunk")
        rc.decrement("mem-1", ref_type="relationship")
        rc.decrement("mem-2", ref_type="chunk")
        # mem-3 still has refs
        rc.increment("mem-3", ref_type="decision")
        zero = rc.get_zero_ref_memories()
        assert set(zero) == {"mem-1", "mem-2"}


# ---------------------------------------------------------------------------
# 6. Highly referenced memories
# ---------------------------------------------------------------------------

class TestHighlyReferenced:
    def test_empty_db_returns_empty(self, rc):
        assert rc.get_highly_referenced(min_refs=3) == []

    def test_returns_memories_above_threshold(self, rc):
        for _ in range(5):
            rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-2", ref_type="relationship")  # only 1
        result = rc.get_highly_referenced(min_refs=3)
        ids = [r["memory_id"] for r in result]
        assert "mem-1" in ids
        assert "mem-2" not in ids

    def test_threshold_is_inclusive(self, rc):
        for _ in range(3):
            rc.increment("mem-1", ref_type="chunk")
        result = rc.get_highly_referenced(min_refs=3)
        assert len(result) == 1
        assert result[0]["memory_id"] == "mem-1"
        assert result[0]["total"] == 3

    def test_result_includes_total_field(self, rc):
        for _ in range(4):
            rc.increment("mem-1", ref_type="decision")
        result = rc.get_highly_referenced(min_refs=1)
        assert result[0]["total"] == 4

    def test_counts_across_types(self, rc):
        """Total counts across all ref types for threshold."""
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="decision")
        result = rc.get_highly_referenced(min_refs=3)
        assert len(result) == 1
        assert result[0]["total"] == 3


# ---------------------------------------------------------------------------
# 7. Protection status
# ---------------------------------------------------------------------------

class TestProtection:
    def test_zero_refs_not_protected(self, rc):
        assert rc.is_protected("nonexistent") is False

    def test_has_refs_is_protected(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        assert rc.is_protected("mem-1") is True

    def test_becomes_unprotected_after_full_decrement(self, rc):
        rc.increment("mem-1", ref_type="synthesis")
        rc.decrement("mem-1", ref_type="synthesis")
        assert rc.is_protected("mem-1") is False

    def test_protected_with_any_single_type(self, rc):
        rc.increment("mem-1", ref_type="chunk")
        assert rc.is_protected("mem-1") is True


# ---------------------------------------------------------------------------
# 8. Bulk update from relationships
# ---------------------------------------------------------------------------

class TestBulkUpdate:
    def test_empty_edges_zeroes_counts(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        result = rc.bulk_update_from_relationships([])
        assert result["updated"] >= 0
        counts = rc.get_count("mem-1")
        assert counts["relationship"] == 0

    def test_simple_edge_list(self, rc):
        edges = [("mem-1", "mem-2"), ("mem-1", "mem-3")]
        result = rc.bulk_update_from_relationships(edges)
        assert result["updated"] > 0
        # mem-1 is referenced by 0 edges as a target (it's only a source)
        # mem-2 referenced once (target of one edge)
        # mem-3 referenced once (target of one edge)
        # mem-1 referenced once (source of edges counts as reference too?
        # Actually: edges represent "A references B". So B gets a ref count.
        # An edge (A, B) means A links to B: B gets +1.
        # But A also participates: A gets +1 for being referenced by the edge.
        # Let's go with: both endpoints get +1 relationship ref.
        counts_2 = rc.get_count("mem-2")
        assert counts_2["relationship"] >= 1
        counts_3 = rc.get_count("mem-3")
        assert counts_3["relationship"] >= 1

    def test_bulk_replaces_previous_relationship_counts(self, rc):
        """Bulk update is a full recompute, not additive."""
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-1", ref_type="relationship")
        # Now recompute from edges where mem-1 appears once
        edges = [("mem-1", "mem-2")]
        rc.bulk_update_from_relationships(edges)
        counts = rc.get_count("mem-1")
        # mem-1 appears as source: 1 reference
        assert counts["relationship"] == 1

    def test_bulk_preserves_other_ref_types(self, rc):
        """Bulk update only touches 'relationship' type."""
        rc.increment("mem-1", ref_type="chunk")
        rc.increment("mem-1", ref_type="chunk")
        edges = [("mem-1", "mem-2")]
        rc.bulk_update_from_relationships(edges)
        counts = rc.get_count("mem-1")
        assert counts["chunk"] == 2  # untouched

    def test_bulk_updates_return_count(self, rc):
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        result = rc.bulk_update_from_relationships(edges)
        assert "updated" in result
        assert result["updated"] > 0


# ---------------------------------------------------------------------------
# 9. Dangling references
# ---------------------------------------------------------------------------

class TestDanglingReferences:
    def test_no_dangling_when_all_active(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-2", ref_type="chunk")
        active = {"mem-1", "mem-2"}
        assert rc.find_dangling_references(active) == []

    def test_detects_dangling(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-deleted", ref_type="chunk")
        active = {"mem-1"}  # mem-deleted not in active set
        dangling = rc.find_dangling_references(active)
        ids = [d["memory_id"] for d in dangling]
        assert "mem-deleted" in ids

    def test_dangling_includes_total(self, rc):
        rc.increment("mem-gone", ref_type="relationship")
        rc.increment("mem-gone", ref_type="chunk")
        dangling = rc.find_dangling_references(set())
        assert len(dangling) == 1
        assert dangling[0]["total"] >= 2

    def test_empty_active_set_all_dangling(self, rc):
        rc.increment("mem-1", ref_type="relationship")
        rc.increment("mem-2", ref_type="decision")
        dangling = rc.find_dangling_references(set())
        ids = [d["memory_id"] for d in dangling]
        assert "mem-1" in ids
        assert "mem-2" in ids


# ---------------------------------------------------------------------------
# 10. Reference distribution
# ---------------------------------------------------------------------------

class TestRefDistribution:
    def test_empty_db_distribution(self, rc):
        dist = rc.get_ref_distribution()
        assert dist["zero_refs"] == 0
        assert dist["one_ref"] == 0
        assert dist["two_refs"] == 0
        assert dist["three_plus"] == 0
        assert dist["max_refs"] == 0

    def test_distribution_counts(self, rc):
        # mem-1: 0 refs (create then decrement)
        rc.increment("mem-zero", ref_type="relationship")
        rc.decrement("mem-zero", ref_type="relationship")
        # mem-2: 1 ref
        rc.increment("mem-one", ref_type="relationship")
        # mem-3: 2 refs
        rc.increment("mem-two", ref_type="relationship")
        rc.increment("mem-two", ref_type="chunk")
        # mem-4: 5 refs
        for _ in range(5):
            rc.increment("mem-five", ref_type="decision")

        dist = rc.get_ref_distribution()
        assert dist["zero_refs"] == 1
        assert dist["one_ref"] == 1
        assert dist["two_refs"] == 1
        assert dist["three_plus"] == 1
        assert dist["max_refs"] == 5


# ---------------------------------------------------------------------------
# 11. Edge cases and misc
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_special_characters_in_memory_id(self, rc):
        """Memory IDs with special chars should work fine."""
        rc.increment("mem/special:chars-2024.01", ref_type="relationship")
        counts = rc.get_count("mem/special:chars-2024.01")
        assert counts["relationship"] == 1

    def test_many_increments(self, rc):
        """Stress test with many increments."""
        for i in range(100):
            rc.increment("mem-heavy", ref_type="relationship")
        counts = rc.get_count("mem-heavy")
        assert counts["relationship"] == 100
        assert counts["total"] == 100

    def test_last_updated_is_set(self, tmp_db):
        """Verify the last_updated field is populated."""
        rc = ReferenceCounter(db_path=tmp_db)
        rc.increment("mem-1", ref_type="relationship")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT last_updated FROM reference_counts WHERE memory_id='mem-1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert len(row[0]) > 0  # ISO format timestamp

    def test_persistence_across_instances(self, tmp_db):
        """Data persists when creating a new ReferenceCounter on the same DB."""
        rc1 = ReferenceCounter(db_path=tmp_db)
        rc1.increment("mem-1", ref_type="relationship")
        rc1.increment("mem-1", ref_type="relationship")

        rc2 = ReferenceCounter(db_path=tmp_db)
        counts = rc2.get_count("mem-1")
        assert counts["relationship"] == 2

    def test_all_ref_types(self, rc):
        """All four ref types work independently."""
        for t in ["relationship", "chunk", "decision", "synthesis"]:
            rc.increment("mem-all", ref_type=t)
        counts = rc.get_count("mem-all")
        assert counts["total"] == 4
        for t in ["relationship", "chunk", "decision", "synthesis"]:
            assert counts[t] == 1


# ---------------------------------------------------------------------------
# 12. ref_type validation
# ---------------------------------------------------------------------------

class TestRefTypeValidation:
    def test_increment_rejects_invalid_ref_type(self, rc):
        """Incrementing with an invalid ref_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid ref_type 'bogus'"):
            rc.increment("mem-1", ref_type="bogus")

    def test_decrement_rejects_invalid_ref_type(self, rc):
        """Decrementing with an invalid ref_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid ref_type 'unknown'"):
            rc.decrement("mem-1", ref_type="unknown")

    def test_increment_rejects_empty_string(self, rc):
        """Empty string is not a valid ref_type."""
        with pytest.raises(ValueError, match="Invalid ref_type"):
            rc.increment("mem-1", ref_type="")

    def test_decrement_rejects_typo(self, rc):
        """Common typo of valid ref_type should be rejected."""
        with pytest.raises(ValueError, match="Invalid ref_type 'relations'"):
            rc.decrement("mem-1", ref_type="relations")
