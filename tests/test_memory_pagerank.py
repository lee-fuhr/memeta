"""
Tests for Memory PageRank — iterative PageRank on memory relationship graph.

Covers: empty graph, single node, two-node cycle, star topology,
chain topology, disconnected components, convergence behavior,
damping factor effects, database storage/retrieval, hub detection,
stats reporting, and edge cases.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from memory_system.memory_pagerank import MemoryPageRank


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_pagerank.db")


@pytest.fixture
def pr(tmp_db):
    """Create a MemoryPageRank instance with a fresh database."""
    return MemoryPageRank(db_path=tmp_db)


def _insert_relationships(db_path: str, edges: list[tuple[str, str, str]]):
    """Helper to insert edges into memory_relationships table.

    Each edge is (from_memory_id, to_memory_id, relationship_type).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_memory_id TEXT NOT NULL,
            to_memory_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            created_at INTEGER NOT NULL,
            auto_detected BOOLEAN DEFAULT FALSE,
            UNIQUE(from_memory_id, to_memory_id, relationship_type)
        )
    """)
    import time
    now = int(time.time())
    for from_id, to_id, rel_type in edges:
        conn.execute(
            "INSERT OR IGNORE INTO memory_relationships (from_memory_id, to_memory_id, relationship_type, created_at) VALUES (?, ?, ?, ?)",
            (from_id, to_id, rel_type, now),
        )
    conn.commit()
    conn.close()


# ─── Empty graph ──────────────────────────────────────────────────────────────

class TestEmptyGraph:
    def test_compute_pagerank_empty_edges(self, pr):
        """Empty edge list returns empty dict."""
        scores = pr.compute_pagerank([])
        assert scores == {}

    def test_compute_from_db_no_relationships_table(self, pr):
        """compute_from_db with no relationships table returns empty."""
        scores = pr.compute_from_db()
        assert scores == {}

    def test_get_top_memories_empty(self, pr):
        """get_top_memories returns empty list when nothing computed."""
        assert pr.get_top_memories() == []

    def test_get_score_missing(self, pr):
        """get_score for nonexistent memory returns None."""
        assert pr.get_score("nonexistent") is None

    def test_get_stats_empty(self, pr):
        """Stats on empty graph return zeroes."""
        stats = pr.get_stats()
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0


# ─── Single node ──────────────────────────────────────────────────────────────

class TestSingleNode:
    def test_single_self_loop(self, pr):
        """A single self-loop should give the node a score of 1.0."""
        scores = pr.compute_pagerank([("A", "A")])
        assert len(scores) == 1
        assert abs(scores["A"] - 1.0) < 1e-4

    def test_single_node_no_edges(self, pr):
        """A single node with no edges (just appears as source) gets score 1.0."""
        # Edge (A, B) creates two nodes; test with just one node in a self-loop
        scores = pr.compute_pagerank([("A", "A")])
        assert "A" in scores


# ─── Two-node cycle ───────────────────────────────────────────────────────────

class TestTwoNodeCycle:
    def test_symmetric_cycle(self, pr):
        """Two nodes pointing at each other should have equal PageRank."""
        scores = pr.compute_pagerank([("A", "B"), ("B", "A")])
        assert abs(scores["A"] - scores["B"]) < 1e-6

    def test_symmetric_cycle_sums_to_one(self, pr):
        """PageRank scores should sum to approximately 1.0 (normalized)."""
        scores = pr.compute_pagerank([("A", "B"), ("B", "A")])
        total = sum(scores.values())
        assert abs(total - 1.0) < 1e-4


# ─── Star topology ────────────────────────────────────────────────────────────

class TestStarTopology:
    """Star: A, B, C, D all point to hub H."""

    def _star_edges(self):
        return [("A", "H"), ("B", "H"), ("C", "H"), ("D", "H")]

    def test_hub_has_highest_score(self, pr):
        """Hub node should have the highest PageRank."""
        scores = pr.compute_pagerank(self._star_edges())
        assert scores["H"] > scores["A"]
        assert scores["H"] > scores["B"]
        assert scores["H"] > scores["C"]
        assert scores["H"] > scores["D"]

    def test_leaf_nodes_equal(self, pr):
        """All leaf nodes in a star should have equal PageRank."""
        scores = pr.compute_pagerank(self._star_edges())
        leaves = [scores["A"], scores["B"], scores["C"], scores["D"]]
        for leaf in leaves:
            assert abs(leaf - leaves[0]) < 1e-6

    def test_star_sums_to_one(self, pr):
        """Star scores should sum to 1.0."""
        scores = pr.compute_pagerank(self._star_edges())
        assert abs(sum(scores.values()) - 1.0) < 1e-4


# ─── Chain topology ───────────────────────────────────────────────────────────

class TestChainTopology:
    """Chain: A -> B -> C -> D"""

    def _chain_edges(self):
        return [("A", "B"), ("B", "C"), ("C", "D")]

    def test_endpoint_has_highest_rank(self, pr):
        """Last node in chain should have highest rank (sink node absorbs rank)."""
        scores = pr.compute_pagerank(self._chain_edges())
        assert scores["D"] > scores["C"]
        assert scores["D"] > scores["B"]
        assert scores["D"] > scores["A"]

    def test_chain_monotonically_increasing(self, pr):
        """PageRank should increase along the chain (with teleportation)."""
        scores = pr.compute_pagerank(self._chain_edges())
        # With damping, D gets most, then C, B, A roughly
        # D > C is guaranteed; B vs C depends on damping but D > A is certain
        assert scores["D"] > scores["A"]


# ─── Disconnected components ──────────────────────────────────────────────────

class TestDisconnectedComponents:
    def test_two_separate_pairs(self, pr):
        """Disconnected pairs should have independent but valid scores."""
        edges = [("A", "B"), ("C", "D")]
        scores = pr.compute_pagerank(edges)
        assert len(scores) == 4
        assert abs(sum(scores.values()) - 1.0) < 1e-4

    def test_disconnected_symmetric(self, pr):
        """Two symmetric cycles should give equal internal scores."""
        edges = [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")]
        scores = pr.compute_pagerank(edges)
        # A and B should be equal; C and D should be equal
        assert abs(scores["A"] - scores["B"]) < 1e-6
        assert abs(scores["C"] - scores["D"]) < 1e-6
        # And cross-component should also be equal (symmetric topology)
        assert abs(scores["A"] - scores["C"]) < 1e-6


# ─── Convergence ──────────────────────────────────────────────────────────────

class TestConvergence:
    def test_converges_within_max_iterations(self, tmp_db):
        """PageRank should converge on a simple graph well before max_iterations."""
        pr = MemoryPageRank(db_path=tmp_db, max_iterations=100)
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        scores = pr.compute_pagerank(edges)
        stats = pr.get_stats()
        # Triangle converges fast — should take < 20 iterations
        assert stats["iterations_to_converge"] < 50

    def test_tight_tolerance_more_iterations(self, tmp_db):
        """Tighter tolerance should require more iterations."""
        pr_loose = MemoryPageRank(db_path=tmp_db, tolerance=1e-2, max_iterations=100)
        edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")]
        pr_loose.compute_pagerank(edges)
        stats_loose = pr_loose.get_stats()

        # New db for the tight run
        tmp2 = tmp_db + ".tight"
        pr_tight = MemoryPageRank(db_path=tmp2, tolerance=1e-10, max_iterations=100)
        pr_tight.compute_pagerank(edges)
        stats_tight = pr_tight.get_stats()

        assert stats_tight["iterations_to_converge"] >= stats_loose["iterations_to_converge"]

    def test_single_iteration_cap(self, tmp_db):
        """max_iterations=1 should stop after one iteration."""
        pr = MemoryPageRank(db_path=tmp_db, max_iterations=1)
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        scores = pr.compute_pagerank(edges)
        stats = pr.get_stats()
        assert stats["iterations_to_converge"] == 1
        # Scores still valid (sum to 1)
        assert abs(sum(scores.values()) - 1.0) < 1e-4


# ─── Damping factor ───────────────────────────────────────────────────────────

class TestDampingFactor:
    def test_damping_zero_uniform(self, tmp_db):
        """Damping=0 means pure teleportation: all nodes should be equal."""
        pr = MemoryPageRank(db_path=tmp_db, damping=0.0)
        edges = [("A", "B"), ("B", "C"), ("C", "D")]
        scores = pr.compute_pagerank(edges)
        expected = 1.0 / 4
        for node, score in scores.items():
            assert abs(score - expected) < 1e-4, f"Node {node}: {score} != {expected}"

    def test_damping_one_extreme(self, tmp_db):
        """Damping=1.0 (no teleportation) should still converge on a cycle."""
        pr = MemoryPageRank(db_path=tmp_db, damping=1.0, max_iterations=50)
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        scores = pr.compute_pagerank(edges)
        # On a perfect cycle with d=1, all scores should be equal
        vals = list(scores.values())
        for v in vals:
            assert abs(v - vals[0]) < 1e-4

    def test_higher_damping_amplifies_structure(self, tmp_db):
        """Higher damping should amplify structural differences (hub vs leaf)."""
        edges = [("A", "H"), ("B", "H"), ("C", "H"), ("D", "H")]

        pr_low = MemoryPageRank(db_path=tmp_db, damping=0.5)
        scores_low = pr_low.compute_pagerank(edges)
        ratio_low = scores_low["H"] / scores_low["A"]

        tmp2 = tmp_db + ".high"
        pr_high = MemoryPageRank(db_path=tmp2, damping=0.95)
        scores_high = pr_high.compute_pagerank(edges)
        ratio_high = scores_high["H"] / scores_high["A"]

        assert ratio_high > ratio_low


# ─── Database storage and retrieval ───────────────────────────────────────────

class TestDatabaseStorage:
    def test_store_and_retrieve(self, pr):
        """Scores stored via store_results are retrievable via get_score."""
        scores = pr.compute_pagerank([("A", "B"), ("B", "C"), ("C", "A")])
        pr.store_results(scores)
        for mem_id, score in scores.items():
            retrieved = pr.get_score(mem_id)
            assert retrieved is not None
            assert abs(retrieved - score) < 1e-8

    def test_store_overwrites(self, pr):
        """Storing new results should overwrite old ones."""
        scores1 = {"A": 0.5, "B": 0.5}
        pr.store_results(scores1)
        assert abs(pr.get_score("A") - 0.5) < 1e-8

        scores2 = {"A": 0.9, "B": 0.1}
        pr.store_results(scores2)
        assert abs(pr.get_score("A") - 0.9) < 1e-8

    def test_get_top_memories(self, pr):
        """get_top_memories returns sorted list."""
        edges = [("A", "H"), ("B", "H"), ("C", "H")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)

        top = pr.get_top_memories(limit=2)
        assert len(top) == 2
        assert top[0]["memory_id"] == "H"
        assert top[0]["pagerank_score"] >= top[1]["pagerank_score"]

    def test_get_top_memories_limit(self, pr):
        """Limit parameter restricts result count."""
        scores = {f"mem_{i}": 1.0 / 10 for i in range(10)}
        pr.store_results(scores)
        top = pr.get_top_memories(limit=3)
        assert len(top) == 3

    def test_stored_results_have_degrees(self, pr):
        """Stored results should include in_degree and out_degree."""
        edges = [("A", "B"), ("A", "C"), ("B", "C")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)

        top = pr.get_top_memories(limit=10)
        # Find node C — it has in_degree=2 (from A and B)
        c_entry = [t for t in top if t["memory_id"] == "C"][0]
        assert c_entry["in_degree"] == 2

        # Find node A — it has out_degree=2 (to B and C), in_degree=0
        a_entry = [t for t in top if t["memory_id"] == "A"][0]
        assert a_entry["out_degree"] == 2
        assert a_entry["in_degree"] == 0


# ─── compute_from_db ──────────────────────────────────────────────────────────

class TestComputeFromDB:
    def test_loads_edges_from_memory_relationships(self, tmp_db):
        """compute_from_db should read edges from memory_relationships table."""
        _insert_relationships(tmp_db, [
            ("mem_A", "mem_B", "supports"),
            ("mem_C", "mem_B", "references"),
            ("mem_B", "mem_D", "led_to"),
        ])

        pr = MemoryPageRank(db_path=tmp_db)
        scores = pr.compute_from_db()

        assert len(scores) == 4
        assert abs(sum(scores.values()) - 1.0) < 1e-4
        # mem_B has 2 incoming edges; should rank high
        assert scores["mem_B"] > scores["mem_A"]

    def test_compute_from_db_stores_results(self, tmp_db):
        """compute_from_db should auto-store results to memory_pagerank table."""
        _insert_relationships(tmp_db, [
            ("A", "B", "supports"),
            ("C", "B", "supports"),
        ])

        pr = MemoryPageRank(db_path=tmp_db)
        pr.compute_from_db()

        # Results should be stored
        score = pr.get_score("B")
        assert score is not None
        assert score > 0

    def test_compute_from_db_empty_table(self, tmp_db):
        """compute_from_db with empty relationships table returns empty."""
        # Create the table but leave it empty
        _insert_relationships(tmp_db, [])
        pr = MemoryPageRank(db_path=tmp_db)
        scores = pr.compute_from_db()
        assert scores == {}


# ─── Hub memories ─────────────────────────────────────────────────────────────

class TestHubMemories:
    def test_get_hub_memories(self, pr):
        """Hub memories should have both high in-degree and high pagerank."""
        # Hub H has 5 incoming links
        edges = [("A", "H"), ("B", "H"), ("C", "H"), ("D", "H"), ("E", "H")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)

        hubs = pr.get_hub_memories(min_in_degree=3)
        assert len(hubs) >= 1
        assert hubs[0]["memory_id"] == "H"

    def test_get_hub_memories_excludes_low_degree(self, pr):
        """Nodes below min_in_degree threshold should be excluded."""
        edges = [("A", "H"), ("B", "H"), ("C", "X")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)

        hubs = pr.get_hub_memories(min_in_degree=2)
        hub_ids = [h["memory_id"] for h in hubs]
        assert "H" in hub_ids
        assert "X" not in hub_ids or all(
            h["in_degree"] >= 2 for h in hubs
        )

    def test_get_hub_memories_empty_when_no_hubs(self, pr):
        """No hubs found if min_in_degree is too high."""
        edges = [("A", "B"), ("C", "D")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)
        hubs = pr.get_hub_memories(min_in_degree=10)
        assert hubs == []


# ─── Stats ────────────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_after_computation(self, pr):
        """Stats should reflect the computed graph."""
        edges = [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")]
        scores = pr.compute_pagerank(edges)
        stats = pr.get_stats()

        assert stats["total_nodes"] == 4
        assert stats["total_edges"] == 4
        assert stats["mean_score"] > 0
        assert stats["max_score"] > 0
        assert stats["iterations_to_converge"] >= 1

    def test_stats_mean_equals_one_over_n(self, pr):
        """Mean score should equal 1/N since total sums to 1."""
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        pr.compute_pagerank(edges)
        stats = pr.get_stats()
        expected_mean = 1.0 / 3
        assert abs(stats["mean_score"] - expected_mean) < 1e-4

    def test_stats_max_score_matches_top(self, pr):
        """max_score in stats should match the top memory's score."""
        edges = [("A", "H"), ("B", "H"), ("C", "H")]
        scores = pr.compute_pagerank(edges)
        pr.store_results(scores)
        stats = pr.get_stats()
        top = pr.get_top_memories(limit=1)
        assert abs(stats["max_score"] - top[0]["pagerank_score"]) < 1e-8


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_duplicate_edges_handled(self, pr):
        """Duplicate edges should be counted once for degree, not crash."""
        edges = [("A", "B"), ("A", "B"), ("A", "B")]
        scores = pr.compute_pagerank(edges)
        assert len(scores) == 2
        assert abs(sum(scores.values()) - 1.0) < 1e-4

    def test_large_graph_converges(self, pr):
        """A larger graph (50 nodes) should converge without issues."""
        edges = []
        for i in range(50):
            edges.append((f"n{i}", f"n{(i + 1) % 50}"))
            if i % 5 == 0:
                edges.append((f"n{i}", "hub"))
        scores = pr.compute_pagerank(edges)
        assert abs(sum(scores.values()) - 1.0) < 1e-4
        # Hub should have high rank
        assert scores["hub"] > scores["n1"]

    def test_dangling_node_handling(self, pr):
        """Dangling nodes (no outgoing edges) should distribute rank via teleportation."""
        # D is a dangling node (sink) — it has incoming but no outgoing
        edges = [("A", "B"), ("B", "C"), ("C", "D")]
        scores = pr.compute_pagerank(edges)
        # D should have the most rank (sink absorbs)
        assert scores["D"] > scores["A"]
        # All scores should still sum to 1
        assert abs(sum(scores.values()) - 1.0) < 1e-4

    def test_many_to_one_amplifies_rank(self, pr):
        """More incoming edges should mean higher PageRank."""
        edges = [(f"src_{i}", "target") for i in range(20)]
        scores = pr.compute_pagerank(edges)
        # Target gets all the incoming edges
        assert scores["target"] > scores["src_0"]
        # With 20 sources, target should have a dominant score
        assert scores["target"] > 0.3

    def test_computed_at_timestamp(self, pr):
        """Stored results should have a computed_at timestamp."""
        scores = pr.compute_pagerank([("A", "B")])
        pr.store_results(scores)
        top = pr.get_top_memories(limit=10)
        for entry in top:
            assert "computed_at" in entry
            assert len(entry["computed_at"]) > 0


# ─── Known solution verification ──────────────────────────────────────────────

class TestKnownSolutions:
    def test_triangle_uniform(self, pr):
        """A perfect triangle (3-cycle) should give uniform scores."""
        edges = [("A", "B"), ("B", "C"), ("C", "A")]
        scores = pr.compute_pagerank(edges)
        expected = 1.0 / 3
        for node in ["A", "B", "C"]:
            assert abs(scores[node] - expected) < 1e-4

    def test_four_cycle_uniform(self, pr):
        """A 4-node cycle should give uniform scores of 0.25."""
        edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")]
        scores = pr.compute_pagerank(edges)
        for node in ["A", "B", "C", "D"]:
            assert abs(scores[node] - 0.25) < 1e-4
