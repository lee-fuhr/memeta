"""
Tests for temporal_knowledge_graph.py

Spec 16: Temporal knowledge graph — time-aware edges between memories.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest

from memory_system.temporal_knowledge_graph import TemporalKnowledgeGraph


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_temporal.db")


@pytest.fixture
def tkg(tmp_db):
    """Create a TemporalKnowledgeGraph instance with temp DB."""
    return TemporalKnowledgeGraph(db_path=tmp_db)


# --- Schema and init ---

class TestInit:
    def test_creates_temporal_edges_table(self, tmp_db):
        """Table is created on init."""
        tkg = TemporalKnowledgeGraph(db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='temporal_edges'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_creates_indexes(self, tmp_db):
        """Indexes are created for source_id, target_id, relationship_type, validity range."""
        tkg = TemporalKnowledgeGraph(db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
        index_names = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert any("source" in name for name in index_names)
        assert any("target" in name for name in index_names)
        assert any("type" in name or "rel" in name for name in index_names)
        assert any("valid" in name for name in index_names)

    def test_idempotent_init(self, tmp_db):
        """Calling init twice does not error."""
        tkg1 = TemporalKnowledgeGraph(db_path=tmp_db)
        tkg2 = TemporalKnowledgeGraph(db_path=tmp_db)
        stats = tkg2.get_stats()
        assert stats["total_edges"] == 0


# --- add_edge ---

class TestAddEdge:
    def test_add_edge_returns_dict_with_edge_id(self, tkg):
        """add_edge returns dict containing edge_id."""
        result = tkg.add_edge(
            source_id="mem_001",
            target_id="mem_002",
            relationship_type="causal",
            valid_from="2026-01-01",
        )
        assert "edge_id" in result
        assert isinstance(result["edge_id"], int)

    def test_add_edge_with_all_params(self, tkg):
        """add_edge stores all parameters correctly."""
        result = tkg.add_edge(
            source_id="mem_001",
            target_id="mem_002",
            relationship_type="supports",
            valid_from="2026-01-01",
            valid_to="2026-06-01",
            confidence=0.85,
        )
        assert result["edge_id"] is not None

        # Verify stored correctly
        edges = tkg.get_relationship_evolution("mem_001")
        assert len(edges) == 1
        edge = edges[0]
        assert edge["source_id"] == "mem_001"
        assert edge["target_id"] == "mem_002"
        assert edge["relationship_type"] == "supports"
        assert edge["valid_from"] == "2026-01-01"
        assert edge["valid_to"] == "2026-06-01"
        assert edge["confidence"] == 0.85

    def test_add_edge_open_ended(self, tkg):
        """add_edge with no valid_to creates open-ended edge."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        edges = tkg.get_relationship_evolution("mem_001")
        assert len(edges) == 1
        assert edges[0]["valid_to"] is None

    def test_add_edge_default_confidence(self, tkg):
        """add_edge defaults confidence to 1.0."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        edges = tkg.get_relationship_evolution("mem_001")
        assert edges[0]["confidence"] == 1.0

    def test_add_multiple_edges(self, tkg):
        """Multiple edges can be added between different memories."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.add_edge("mem_002", "mem_003", "supports", "2026-02-01")
        tkg.add_edge("mem_001", "mem_003", "related", "2026-03-01")

        stats = tkg.get_stats()
        assert stats["total_edges"] == 3


# --- get_edges_at ---

class TestGetEdgesAt:
    def test_get_edges_at_open_ended(self, tkg):
        """Open-ended edge is valid at any future timestamp."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        edges = tkg.get_edges_at("mem_001", "2026-06-15")
        assert len(edges) == 1
        assert edges[0]["target_id"] == "mem_002"

    def test_get_edges_at_within_range(self, tkg):
        """Edge valid within its valid_from to valid_to range."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-06-30")
        edges = tkg.get_edges_at("mem_001", "2026-03-15")
        assert len(edges) == 1

    def test_get_edges_at_before_valid_from(self, tkg):
        """Edge not returned if timestamp is before valid_from."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-06-01")
        edges = tkg.get_edges_at("mem_001", "2026-01-01")
        assert len(edges) == 0

    def test_get_edges_at_after_valid_to(self, tkg):
        """Edge not returned if timestamp is after valid_to."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-06-30")
        edges = tkg.get_edges_at("mem_001", "2026-12-01")
        assert len(edges) == 0

    def test_get_edges_at_boundary_valid_from(self, tkg):
        """Edge is valid at exactly valid_from."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-06-30")
        edges = tkg.get_edges_at("mem_001", "2026-01-01")
        assert len(edges) == 1

    def test_get_edges_at_boundary_valid_to(self, tkg):
        """Edge is valid at exactly valid_to."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-06-30")
        edges = tkg.get_edges_at("mem_001", "2026-06-30")
        assert len(edges) == 1

    def test_get_edges_at_returns_both_directions(self, tkg):
        """Returns edges where memory_id is source OR target."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.add_edge("mem_003", "mem_001", "supports", "2026-01-01")

        edges = tkg.get_edges_at("mem_001", "2026-06-15")
        assert len(edges) == 2

    def test_get_edges_at_empty_db(self, tkg):
        """Returns empty list for memory with no edges."""
        edges = tkg.get_edges_at("nonexistent", "2026-01-01")
        assert edges == []

    def test_get_edges_at_filters_expired(self, tkg):
        """Only active edges at the given timestamp are returned."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-03-31")
        tkg.add_edge("mem_001", "mem_003", "supports", "2026-04-01", "2026-12-31")

        # In March, only the first edge is active
        edges_march = tkg.get_edges_at("mem_001", "2026-03-15")
        assert len(edges_march) == 1
        assert edges_march[0]["target_id"] == "mem_002"

        # In June, only the second edge is active
        edges_june = tkg.get_edges_at("mem_001", "2026-06-15")
        assert len(edges_june) == 1
        assert edges_june[0]["target_id"] == "mem_003"


# --- get_relationship_evolution ---

class TestGetRelationshipEvolution:
    def test_returns_all_edges_sorted(self, tkg):
        """Returns all edges for a memory sorted by valid_from."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-03-01")
        tkg.add_edge("mem_001", "mem_003", "supports", "2026-01-01")
        tkg.add_edge("mem_001", "mem_004", "related", "2026-02-01")

        edges = tkg.get_relationship_evolution("mem_001")
        assert len(edges) == 3
        assert edges[0]["valid_from"] == "2026-01-01"
        assert edges[1]["valid_from"] == "2026-02-01"
        assert edges[2]["valid_from"] == "2026-03-01"

    def test_includes_incoming_edges(self, tkg):
        """Evolution includes edges where memory is target."""
        tkg.add_edge("mem_002", "mem_001", "causal", "2026-01-01")
        tkg.add_edge("mem_001", "mem_003", "supports", "2026-02-01")

        edges = tkg.get_relationship_evolution("mem_001")
        assert len(edges) == 2

    def test_empty_for_unknown_memory(self, tkg):
        """Returns empty list for memory with no edges."""
        edges = tkg.get_relationship_evolution("nonexistent")
        assert edges == []


# --- get_edges_between ---

class TestGetEdgesBetween:
    def test_edges_in_range(self, tkg):
        """Returns edges with valid_from within the date range."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-15")
        tkg.add_edge("mem_003", "mem_004", "supports", "2026-02-15")
        tkg.add_edge("mem_005", "mem_006", "related", "2026-03-15")

        edges = tkg.get_edges_between("2026-02-01", "2026-02-28")
        assert len(edges) == 1
        assert edges[0]["source_id"] == "mem_003"

    def test_edges_between_inclusive(self, tkg):
        """Boundary dates are inclusive."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-02-01")
        tkg.add_edge("mem_003", "mem_004", "supports", "2026-02-28")

        edges = tkg.get_edges_between("2026-02-01", "2026-02-28")
        assert len(edges) == 2

    def test_edges_between_empty_range(self, tkg):
        """Returns empty list when no edges exist in range."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-15")
        edges = tkg.get_edges_between("2026-06-01", "2026-06-30")
        assert edges == []


# --- expire_edge ---

class TestExpireEdge:
    def test_expire_open_ended_edge(self, tkg):
        """Sets valid_to on a previously open-ended edge."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")

        result = tkg.expire_edge("mem_001", "mem_002", "causal", "2026-06-30")
        assert result is True

        edges = tkg.get_relationship_evolution("mem_001")
        assert edges[0]["valid_to"] == "2026-06-30"

    def test_expire_nonexistent_edge(self, tkg):
        """Returns False when no matching open-ended edge exists."""
        result = tkg.expire_edge("mem_001", "mem_002", "causal", "2026-06-30")
        assert result is False

    def test_expire_only_affects_open_ended(self, tkg):
        """Only expires edges that currently have valid_to IS NULL."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01", "2026-03-31")

        result = tkg.expire_edge("mem_001", "mem_002", "causal", "2026-06-30")
        assert result is False

        # Original valid_to unchanged
        edges = tkg.get_relationship_evolution("mem_001")
        assert edges[0]["valid_to"] == "2026-03-31"

    def test_expired_edge_no_longer_active(self, tkg):
        """After expiring, edge doesn't show in get_edges_at for future dates."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.expire_edge("mem_001", "mem_002", "causal", "2026-06-30")

        # Should still be active in June
        edges_june = tkg.get_edges_at("mem_001", "2026-06-15")
        assert len(edges_june) == 1

        # Should NOT be active in July
        edges_july = tkg.get_edges_at("mem_001", "2026-07-15")
        assert len(edges_july) == 0


# --- get_stats ---

class TestGetStats:
    def test_stats_empty_db(self, tkg):
        """Stats on empty DB return zeroes."""
        stats = tkg.get_stats()
        assert stats["total_edges"] == 0
        assert stats["active_edges"] == 0
        assert stats["expired_edges"] == 0
        assert stats["by_type"] == {}

    def test_stats_counts(self, tkg):
        """Stats correctly count total, active, expired edges."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.add_edge("mem_001", "mem_003", "supports", "2026-01-01", "2026-06-30")
        tkg.add_edge("mem_002", "mem_003", "related", "2026-02-01")

        stats = tkg.get_stats()
        assert stats["total_edges"] == 3
        assert stats["active_edges"] == 2  # two open-ended
        assert stats["expired_edges"] == 1  # one with valid_to set

    def test_stats_by_type(self, tkg):
        """Stats break down edge counts by relationship_type."""
        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.add_edge("mem_001", "mem_003", "causal", "2026-02-01")
        tkg.add_edge("mem_002", "mem_003", "supports", "2026-03-01")

        stats = tkg.get_stats()
        assert stats["by_type"]["causal"] == 2
        assert stats["by_type"]["supports"] == 1
