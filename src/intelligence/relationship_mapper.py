"""
Feature 24: Memory Relationship Mapping

Builds explicit relationship graph between memories.

Relationship types:
- causal: A led to decision B
- contradicts: A and B conflict
- supports: A reinforces B
- requires: A depends on B
- related: A and B are semantically similar

Use cases:
- Find all memories that led to a decision
- Detect contradicting memories
- Build causal chains (A→B→C)
- Visualize memory graphs
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


@dataclass
class MemoryRelationship:
    """A relationship between two memories"""
    id: str
    from_memory_id: str
    to_memory_id: str
    relationship_type: str  # causal, contradicts, supports, requires, related
    strength: float  # 0.0-1.0 confidence
    evidence: str  # Why they're related
    created_at: datetime


class RelationshipMapper:
    """
    Manages relationships between memories.

    Core operations:
    - link_memories(): Create explicit relationships
    - get_related_memories(): Find all memories related to one
    - find_causal_chain(): Trace A→B→C chains
    - detect_contradictions(): Find conflicting memories
    """

    def __init__(self, db_path: str = None):
        """Initialize mapper with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"

        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        """Create relationship tables"""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_relationships (
                    id TEXT PRIMARY KEY,
                    from_memory_id TEXT NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    evidence TEXT,
                    created_at INTEGER NOT NULL,
                    UNIQUE(from_memory_id, to_memory_id, relationship_type)
                )
            """)

            # Indices for fast lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rel_from
                ON memory_relationships(from_memory_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rel_to
                ON memory_relationships(to_memory_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rel_type
                ON memory_relationships(relationship_type)
            """)

            conn.commit()

    def link_memories(
        self,
        from_id: str,
        to_id: str,
        relationship_type: str,
        evidence: str,
        strength: float = 0.5
    ) -> str:
        """
        Create relationship between two memories.

        Args:
            from_id: Source memory ID
            to_id: Target memory ID
            relationship_type: causal, contradicts, supports, requires, related
            evidence: Why they're related
            strength: Confidence 0.0-1.0

        Returns:
            Relationship ID

        Raises:
            ValueError: If relationship_type invalid or strength out of range
        """
        # Validate
        valid_types = {'causal', 'contradicts', 'supports', 'requires', 'related'}
        if relationship_type not in valid_types:
            raise ValueError(f"Invalid relationship_type: {relationship_type}. Must be one of {valid_types}")

        if not 0.0 <= strength <= 1.0:
            raise ValueError(f"Strength must be 0.0-1.0, got {strength}")

        # Generate ID
        import hashlib
        id_source = f"{from_id}{to_id}{relationship_type}"
        rel_id = hashlib.md5(id_source.encode()).hexdigest()[:16]

        # Insert (or ignore if duplicate)
        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO memory_relationships
                (id, from_memory_id, to_memory_id, relationship_type, strength, evidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                rel_id,
                from_id,
                to_id,
                relationship_type,
                strength,
                evidence,
                int(datetime.now().timestamp())
            ))

            conn.commit()

        return rel_id

    def get_related_memories(
        self,
        memory_id: str,
        relationship_type: Optional[str] = None,
        direction: str = "both"
    ) -> List[Tuple[str, MemoryRelationship]]:
        """
        Find all memories related to this one.

        Args:
            memory_id: Memory to find relations for
            relationship_type: Filter by type (optional)
            direction: "from" (outgoing), "to" (incoming), "both"

        Returns:
            List of (related_memory_id, relationship) tuples
        """
        # Build query
        conditions = []
        params = []

        if direction in ["from", "both"]:
            conditions.append("from_memory_id = ?")
            params.append(memory_id)

        if direction in ["to", "both"]:
            if conditions:
                conditions.append("OR to_memory_id = ?")
            else:
                conditions.append("to_memory_id = ?")
            params.append(memory_id)

        where_clause = " OR ".join(conditions)

        if relationship_type:
            where_clause += " AND relationship_type = ?"
            params.append(relationship_type)

        # Query
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(f"""
                SELECT id, from_memory_id, to_memory_id, relationship_type,
                       strength, evidence, created_at
                FROM memory_relationships
                WHERE {where_clause}
                ORDER BY strength DESC, created_at DESC
            """, params)

            results = []
            for row in cursor.fetchall():
                rel = MemoryRelationship(
                    id=row[0],
                    from_memory_id=row[1],
                    to_memory_id=row[2],
                    relationship_type=row[3],
                    strength=row[4],
                    evidence=row[5],
                    created_at=datetime.fromtimestamp(row[6])
                )

                # Determine related memory ID
                related_id = row[2] if row[1] == memory_id else row[1]

                results.append((related_id, rel))

            return results

    def find_causal_chain(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 5
    ) -> Optional[List[str]]:
        """
        Find causal chain from start to end memory.

        Uses breadth-first search to find shortest path.

        Args:
            start_id: Starting memory
            end_id: Target memory
            max_depth: Maximum chain length

        Returns:
            List of memory IDs forming chain, or None if no path
        """
        # BFS to find shortest path
        from collections import deque

        queue = deque([(start_id, [start_id])])
        visited = {start_id}

        while queue:
            current_id, path = queue.popleft()

            # Max depth check
            if len(path) > max_depth:
                continue

            # Found target?
            if current_id == end_id:
                return path

            # Explore causal relationships
            related = self.get_related_memories(
                current_id,
                relationship_type="causal",
                direction="from"
            )

            for related_id, _ in related:
                if related_id not in visited:
                    visited.add(related_id)
                    queue.append((related_id, path + [related_id]))

        # No path found
        return None

    def detect_contradictions(self, memory_id: str) -> List[Tuple[str, MemoryRelationship]]:
        """
        Find memories that contradict this one.

        Args:
            memory_id: Memory to check

        Returns:
            List of (contradicting_memory_id, relationship) tuples
        """
        return self.get_related_memories(
            memory_id,
            relationship_type="contradicts",
            direction="both"
        )

    def get_relationship_stats(self) -> dict:
        """Get relationship graph statistics"""
        with get_connection(self.db_path) as conn:
            # Total relationships
            total = conn.execute(
                "SELECT COUNT(*) FROM memory_relationships"
            ).fetchone()[0]

            # By type
            by_type = {}
            cursor = conn.execute("""
                SELECT relationship_type, COUNT(*)
                FROM memory_relationships
                GROUP BY relationship_type
            """)
            for row in cursor.fetchall():
                by_type[row[0]] = row[1]

            # Average strength
            avg_strength = conn.execute(
                "SELECT AVG(strength) FROM memory_relationships"
            ).fetchone()[0] or 0.0

            return {
                'total_relationships': total,
                'by_type': by_type,
                'average_strength': avg_strength
            }
