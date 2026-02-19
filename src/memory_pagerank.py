"""
Memory PageRank — iterative PageRank on the memory relationship graph.

Runs the classic PageRank algorithm (Brin & Page, 1998) over the memory
relationship graph. A memory's structural importance is determined by
the importance of memories that link to it, not just its standalone
importance score.

A quiet memory like "always check DNS before debugging" that gets
`supports` links from 8 debugging memories would bubble up in rank.

PageRank scores are stored in memory_pagerank table and used as a
secondary ranking factor in search. Hub memories (high in-degree +
high PageRank) are surfaced in briefings as "most connected insights."

Algorithm:
    1. Initialize all nodes with score 1/N
    2. For each iteration:
       new_rank[node] = (1-d)/N + d * sum(rank[src]/out_degree[src]
                                          for src in incoming[node])
       Dangling nodes (out_degree=0) distribute their rank equally
       to all nodes via teleportation.
    3. Stop when max delta < tolerance or max_iterations reached.

Usage:
    from memory_system.memory_pagerank import MemoryPageRank

    pr = MemoryPageRank(db_path="intelligence.db")

    # From explicit edges
    scores = pr.compute_pagerank([("mem_A", "mem_B"), ("mem_C", "mem_B")])

    # From database
    scores = pr.compute_from_db()

    # Query results
    top = pr.get_top_memories(limit=10)
    hubs = pr.get_hub_memories(min_in_degree=3)
    stats = pr.get_stats()
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory_system.db_pool import get_connection

logger = logging.getLogger(__name__)


class MemoryPageRank:
    """
    Iterative PageRank computation over the memory relationship graph.

    Stores results in memory_pagerank table for downstream consumption
    by search ranking, briefings, and the dashboard.
    """

    def __init__(
        self,
        db_path: str = None,
        damping: float = 0.85,
        max_iterations: int = 20,
        tolerance: float = 1e-6,
    ):
        """
        Initialize PageRank engine.

        Args:
            db_path: Path to SQLite database. Defaults to intelligence.db
                     alongside the package root.
            damping: Damping factor (probability of following a link vs.
                     teleporting). 0.85 is the classic default.
            max_iterations: Maximum iterations before stopping.
            tolerance: Convergence threshold (max score delta between
                       iterations).
        """
        if db_path is None:
            db_path = str(Path(__file__).parent / "intelligence.db")

        self.db_path = str(db_path)
        self.damping = damping
        self.max_iterations = max_iterations
        self.tolerance = tolerance

        # Track last computation stats
        self._last_total_nodes = 0
        self._last_total_edges = 0
        self._last_iterations = 0
        self._last_scores: dict[str, float] = {}

        # Degree maps from last computation (for store_results)
        self._last_in_degree: dict[str, int] = {}
        self._last_out_degree: dict[str, int] = {}

        self._init_db()

    def _init_db(self):
        """Create memory_pagerank table if it doesn't exist."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_pagerank (
                    memory_id TEXT PRIMARY KEY,
                    pagerank_score REAL NOT NULL,
                    in_degree INTEGER NOT NULL,
                    out_degree INTEGER NOT NULL,
                    computed_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def compute_pagerank(self, edges: list[tuple[str, str]]) -> dict[str, float]:
        """
        Compute PageRank from a list of (source, target) edges.

        Handles dangling nodes (no outgoing edges) by redistributing
        their rank equally to all nodes (teleportation).

        Args:
            edges: List of (source_id, target_id) tuples representing
                   directed links in the graph.

        Returns:
            Dictionary mapping memory_id to PageRank score.
            Scores sum to 1.0 (normalized).
        """
        if not edges:
            self._last_total_nodes = 0
            self._last_total_edges = 0
            self._last_iterations = 0
            self._last_scores = {}
            self._last_in_degree = {}
            self._last_out_degree = {}
            return {}

        # Build adjacency structures
        # Deduplicate edges
        unique_edges = set(edges)

        nodes: set[str] = set()
        outgoing: dict[str, set[str]] = defaultdict(set)
        incoming: dict[str, set[str]] = defaultdict(set)

        for src, tgt in unique_edges:
            nodes.add(src)
            nodes.add(tgt)
            if src != tgt:  # Self-loops don't contribute to PageRank
                outgoing[src].add(tgt)
                incoming[tgt].add(src)

        node_list = sorted(nodes)
        n = len(node_list)

        if n == 0:
            self._last_total_nodes = 0
            self._last_total_edges = 0
            self._last_iterations = 0
            self._last_scores = {}
            self._last_in_degree = {}
            self._last_out_degree = {}
            return {}

        # Compute degree maps
        out_degree = {node: len(outgoing.get(node, set())) for node in node_list}
        in_degree = {node: len(incoming.get(node, set())) for node in node_list}

        # Initialize scores
        rank = {node: 1.0 / n for node in node_list}

        d = self.damping
        teleport = (1.0 - d) / n

        # Identify dangling nodes (no outgoing edges, excluding self-loops)
        dangling_nodes = [node for node in node_list if out_degree[node] == 0]

        iterations = 0

        for iteration in range(self.max_iterations):
            iterations = iteration + 1
            new_rank = {}

            # Dangling node contribution: sum of dangling ranks / N
            dangling_sum = sum(rank[node] for node in dangling_nodes)
            dangling_contrib = d * dangling_sum / n

            for node in node_list:
                # Link contribution from incoming nodes
                link_sum = 0.0
                for src in incoming.get(node, set()):
                    link_sum += rank[src] / out_degree[src]

                new_rank[node] = teleport + d * link_sum + dangling_contrib

            # Check convergence
            max_delta = max(abs(new_rank[node] - rank[node]) for node in node_list)
            rank = new_rank

            if max_delta < self.tolerance:
                break

        # Normalize to sum to exactly 1.0 (fix floating-point drift)
        total = sum(rank.values())
        if total > 0:
            rank = {node: score / total for node, score in rank.items()}

        # Store metadata
        self._last_total_nodes = n
        self._last_total_edges = len(unique_edges)
        self._last_iterations = iterations
        self._last_scores = dict(rank)
        self._last_in_degree = in_degree
        self._last_out_degree = out_degree

        return dict(rank)

    def compute_from_db(self) -> dict[str, float]:
        """
        Load edges from memory_relationships table and compute PageRank.

        Reads all relationships from the database, runs PageRank, stores
        results in memory_pagerank table, and returns scores.

        Returns:
            Dictionary mapping memory_id to PageRank score, or empty dict
            if no relationships found.
        """
        edges = []

        try:
            with get_connection(self.db_path) as conn:
                # Check if table exists
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_relationships'"
                )
                if cursor.fetchone() is None:
                    return {}

                rows = conn.execute(
                    "SELECT from_memory_id, to_memory_id FROM memory_relationships"
                ).fetchall()

                edges = [(row[0], row[1]) for row in rows]
        except (sqlite3.OperationalError, KeyError) as exc:
            logger.debug("PageRank computation from DB failed: %s", exc)
            return {}

        if not edges:
            return {}

        scores = self.compute_pagerank(edges)
        self.store_results(scores)
        return scores

    def store_results(self, scores: dict[str, float]) -> None:
        """
        Store PageRank scores to the memory_pagerank database table.

        Uses INSERT OR REPLACE to upsert. Includes degree information
        from the last computation (if available) or defaults to 0.

        Args:
            scores: Dictionary mapping memory_id to PageRank score.
        """
        if not scores:
            return

        now = datetime.now(timezone.utc).isoformat()

        with get_connection(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO memory_pagerank
                (memory_id, pagerank_score, in_degree, out_degree, computed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (mem_id, score, self._last_in_degree.get(mem_id, 0),
                     self._last_out_degree.get(mem_id, 0), now)
                    for mem_id, score in scores.items()
                ],
            )
            conn.commit()

    def get_top_memories(self, limit: int = 10) -> list[dict]:
        """
        Return top-N memories by PageRank score.

        Args:
            limit: Maximum number of results.

        Returns:
            List of dicts with keys: memory_id, pagerank_score,
            in_degree, out_degree, computed_at. Sorted by score descending.
        """
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT memory_id, pagerank_score, in_degree, out_degree, computed_at
                FROM memory_pagerank
                ORDER BY pagerank_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "memory_id": row[0],
                "pagerank_score": row[1],
                "in_degree": row[2],
                "out_degree": row[3],
                "computed_at": row[4],
            }
            for row in rows
        ]

    def get_score(self, memory_id: str) -> Optional[float]:
        """
        Get PageRank score for a specific memory.

        Args:
            memory_id: The memory identifier.

        Returns:
            PageRank score as float, or None if not found.
        """
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT pagerank_score FROM memory_pagerank WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()

        return row[0] if row else None

    def get_hub_memories(self, min_in_degree: int = 3) -> list[dict]:
        """
        Find hub memories with high in-degree AND high PageRank.

        Hub memories are structurally important: many other memories
        reference them, and those referring memories are themselves
        important.

        Args:
            min_in_degree: Minimum incoming edges to qualify as a hub.

        Returns:
            List of dicts sorted by pagerank_score descending, filtered
            to only include memories with in_degree >= min_in_degree.
        """
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT memory_id, pagerank_score, in_degree, out_degree, computed_at
                FROM memory_pagerank
                WHERE in_degree >= ?
                ORDER BY pagerank_score DESC
                """,
                (min_in_degree,),
            ).fetchall()

        return [
            {
                "memory_id": row[0],
                "pagerank_score": row[1],
                "in_degree": row[2],
                "out_degree": row[3],
                "computed_at": row[4],
            }
            for row in rows
        ]

    def get_stats(self) -> dict:
        """
        Return statistics about the last PageRank computation.

        Returns:
            Dict with keys: total_nodes, total_edges, mean_score,
            max_score, iterations_to_converge.
        """
        n = self._last_total_nodes
        scores = self._last_scores

        if n == 0 or not scores:
            return {
                "total_nodes": 0,
                "total_edges": 0,
                "mean_score": 0.0,
                "max_score": 0.0,
                "iterations_to_converge": 0,
            }

        values = list(scores.values())
        return {
            "total_nodes": n,
            "total_edges": self._last_total_edges,
            "mean_score": sum(values) / len(values),
            "max_score": max(values),
            "iterations_to_converge": self._last_iterations,
        }
