"""
Spec 16: Temporal knowledge graph

Time-aware relationship edges between memories. Each edge has a validity
window (valid_from, valid_to) so the graph can be queried at any point
in time to see which relationships were active.

Relationship types are free-form strings (causal, supports, contradicts,
related, requires, etc.) — no enum constraint, to stay flexible.

Database: uses its own `temporal_edges` table via db_pool.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from memory_system.db_pool import get_connection


class TemporalKnowledgeGraph:
    """
    Time-aware knowledge graph for memory relationships.

    Every edge has a validity window [valid_from, valid_to].
    Open-ended edges have valid_to = NULL (still active).

    Example:
        tkg = TemporalKnowledgeGraph(db_path="temporal.db")

        tkg.add_edge("mem_001", "mem_002", "causal", "2026-01-01")
        tkg.add_edge("mem_001", "mem_003", "supports", "2026-02-01", "2026-06-30")

        # What was connected to mem_001 on March 15?
        edges = tkg.get_edges_at("mem_001", "2026-03-15")

        # Full history
        evolution = tkg.get_relationship_evolution("mem_001")

        # Close an open edge
        tkg.expire_edge("mem_001", "mem_002", "causal", "2026-12-31")
    """

    def __init__(self, db_path: str = None):
        """
        Initialize temporal knowledge graph.

        Args:
            db_path: Path to SQLite database. Defaults to intelligence.db
                     alongside the package root.
        """
        if db_path is None:
            db_path = str(Path(__file__).parent.parent / "intelligence.db")

        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        """Create temporal_edges table and indexes."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS temporal_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
            """)

            # Index for querying by source
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_source_id
                ON temporal_edges(source_id)
            """)

            # Index for querying by target
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_target_id
                ON temporal_edges(target_id)
            """)

            # Index for filtering by relationship type
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_rel_type
                ON temporal_edges(relationship_type)
            """)

            # Index for temporal range queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_temporal_valid_range
                ON temporal_edges(valid_from, valid_to)
            """)

            conn.commit()

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        valid_from: str,
        valid_to: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Dict:
        """
        Add a temporal edge between two memories.

        Args:
            source_id: Source memory ID.
            target_id: Target memory ID.
            relationship_type: Type of relationship (free-form string).
            valid_from: Start of validity window (ISO date string, e.g. "2026-01-01").
            valid_to: End of validity window. None = open-ended (still active).
            confidence: Confidence score 0.0-1.0. Default 1.0.

        Returns:
            Dict with edge_id key.
        """
        created_at = datetime.now().isoformat()

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO temporal_edges
                (source_id, target_id, relationship_type, valid_from, valid_to, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, target_id, relationship_type, valid_from, valid_to, confidence, created_at),
            )
            conn.commit()
            edge_id = cursor.lastrowid

        return {"edge_id": edge_id}

    def get_edges_at(self, memory_id: str, timestamp: str) -> List[Dict]:
        """
        Get all edges involving memory_id that are valid at timestamp.

        An edge is valid at timestamp when:
            valid_from <= timestamp AND (valid_to IS NULL OR valid_to >= timestamp)

        Searches both directions (memory_id as source OR target).

        Args:
            memory_id: Memory identifier.
            timestamp: ISO date string to check validity against.

        Returns:
            List of edge dicts.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, source_id, target_id, relationship_type,
                       valid_from, valid_to, confidence, created_at
                FROM temporal_edges
                WHERE (source_id = ? OR target_id = ?)
                  AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to >= ?)
                ORDER BY valid_from
                """,
                (memory_id, memory_id, timestamp, timestamp),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_relationship_evolution(self, memory_id: str) -> List[Dict]:
        """
        Get all edges for a memory, sorted chronologically by valid_from.

        Includes both directions (source and target).

        Args:
            memory_id: Memory identifier.

        Returns:
            List of edge dicts sorted by valid_from ascending.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, source_id, target_id, relationship_type,
                       valid_from, valid_to, confidence, created_at
                FROM temporal_edges
                WHERE source_id = ? OR target_id = ?
                ORDER BY valid_from ASC
                """,
                (memory_id, memory_id),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_edges_between(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Get edges created (valid_from) within a date range.

        Both boundaries are inclusive.

        Args:
            start_date: Start of range (ISO date string).
            end_date: End of range (ISO date string).

        Returns:
            List of edge dicts with valid_from in [start_date, end_date].
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, source_id, target_id, relationship_type,
                       valid_from, valid_to, confidence, created_at
                FROM temporal_edges
                WHERE valid_from >= ? AND valid_from <= ?
                ORDER BY valid_from ASC
                """,
                (start_date, end_date),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def expire_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        valid_to: str,
    ) -> bool:
        """
        Set valid_to on an open-ended edge, closing it.

        Only affects edges where valid_to IS NULL (open-ended).
        If no matching open-ended edge exists, returns False.

        Args:
            source_id: Source memory ID.
            target_id: Target memory ID.
            relationship_type: Relationship type to match.
            valid_to: Date to close the edge at.

        Returns:
            True if an edge was expired, False if no matching open-ended edge found.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE temporal_edges
                SET valid_to = ?
                WHERE source_id = ?
                  AND target_id = ?
                  AND relationship_type = ?
                  AND valid_to IS NULL
                """,
                (valid_to, source_id, target_id, relationship_type),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_stats(self) -> Dict:
        """
        Get graph statistics.

        Returns:
            Dict with total_edges, active_edges (valid_to IS NULL),
            expired_edges (valid_to IS NOT NULL), and by_type counts.
        """
        with get_connection(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM temporal_edges"
            ).fetchone()[0]

            active = conn.execute(
                "SELECT COUNT(*) FROM temporal_edges WHERE valid_to IS NULL"
            ).fetchone()[0]

            expired = conn.execute(
                "SELECT COUNT(*) FROM temporal_edges WHERE valid_to IS NOT NULL"
            ).fetchone()[0]

            by_type = {}
            cursor = conn.execute(
                """
                SELECT relationship_type, COUNT(*)
                FROM temporal_edges
                GROUP BY relationship_type
                """
            )
            for row in cursor.fetchall():
                by_type[row[0]] = row[1]

        return {
            "total_edges": total,
            "active_edges": active,
            "expired_edges": expired,
            "by_type": by_type,
        }

    @staticmethod
    def _row_to_dict(row) -> Dict:
        """Convert a raw SQLite row tuple to an edge dict."""
        return {
            "id": row[0],
            "source_id": row[1],
            "target_id": row[2],
            "relationship_type": row[3],
            "valid_from": row[4],
            "valid_to": row[5],
            "confidence": row[6],
            "created_at": row[7],
        }
