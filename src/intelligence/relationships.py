"""
Feature 25: Memory Relationships Graph

Tracks explicit relationships between memories: "led_to", "contradicts", "references", "supports".

Enables:
- Graph queries: "What led to this insight?"
- Contradiction detection: "Does this conflict with anything?"
- Citation tracking: "What references this memory?"
- Support network: "What evidence backs this up?"

Database: intelligence.db (memory_relationships table)
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Literal
from dataclasses import dataclass

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


# Relationship types
RelationshipType = Literal["led_to", "contradicts", "references", "supports", "related_to"]


@dataclass
class MemoryRelationship:
    """Relationship between two memories"""
    id: int
    from_memory_id: str
    to_memory_id: str
    relationship_type: RelationshipType
    weight: float
    created_at: datetime
    auto_detected: bool


class MemoryRelationships:
    """
    Graph of relationships between memories.

    Relationship types:
    - **led_to**: Memory A led to insight B (causal chain)
    - **contradicts**: Memory A conflicts with B (needs resolution)
    - **references**: Memory A mentions/cites B (attribution)
    - **supports**: Memory A provides evidence for B (reinforcement)
    - **related_to**: Generic association (weak connection)

    Weight: 0.0-1.0 (strength of relationship)
    Auto-detected: True if system found it, False if user added it

    Example:
        relationships = MemoryRelationships()

        # Add relationship
        rel = relationships.add_relationship(
            from_memory="mem_001",
            to_memory="mem_002",
            relationship_type="led_to",
            weight=0.9,
            auto_detected=False
        )

        # Find what led to this insight
        predecessors = relationships.get_predecessors("mem_002", "led_to")

        # Find contradictions
        conflicts = relationships.get_relationships("mem_001", "contradicts")

        # Get relationship graph for memory
        graph = relationships.get_memory_graph("mem_001", max_depth=2)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize relationships system.

        Args:
            db_path: Path to intelligence.db (default: intelligence.db in module parent)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Create relationships table if it doesn't exist."""
        with get_connection(self.db_path) as conn:
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

            # Index for finding outgoing relationships
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_from
                ON memory_relationships(from_memory_id, relationship_type)
            """)

            # Index for finding incoming relationships
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_to
                ON memory_relationships(to_memory_id, relationship_type)
            """)

            # Index for finding by type
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_type
                ON memory_relationships(relationship_type, weight DESC)
            """)

            conn.commit()

    def add_relationship(
        self,
        from_memory: str,
        to_memory: str,
        relationship_type: RelationshipType,
        weight: float = 1.0,
        auto_detected: bool = False
    ) -> MemoryRelationship:
        """
        Add or update relationship between memories.

        Args:
            from_memory: Source memory ID
            to_memory: Target memory ID
            relationship_type: Type of relationship
            weight: Strength of relationship (0.0-1.0)
            auto_detected: True if automatically detected by system

        Returns:
            Created/updated relationship
        """
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO memory_relationships
                (from_memory_id, to_memory_id, relationship_type, weight, created_at, auto_detected)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(from_memory_id, to_memory_id, relationship_type)
                DO UPDATE SET weight = excluded.weight, auto_detected = excluded.auto_detected
                RETURNING id
            """, (from_memory, to_memory, relationship_type, weight, now, auto_detected))

            rel_id = cursor.fetchone()[0]
            conn.commit()

            return self.get_relationship(rel_id)

    def get_relationship(self, relationship_id: int) -> Optional[MemoryRelationship]:
        """
        Get relationship by ID.

        Args:
            relationship_id: Relationship identifier

        Returns:
            Relationship or None if not found
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, from_memory_id, to_memory_id, relationship_type,
                       weight, created_at, auto_detected
                FROM memory_relationships
                WHERE id = ?
            """, (relationship_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return MemoryRelationship(
                id=row[0],
                from_memory_id=row[1],
                to_memory_id=row[2],
                relationship_type=row[3],
                weight=row[4],
                created_at=datetime.fromtimestamp(row[5]),
                auto_detected=bool(row[6])
            )

    def get_relationships(
        self,
        memory_id: str,
        relationship_type: Optional[RelationshipType] = None,
        direction: Literal["outgoing", "incoming", "both"] = "outgoing"
    ) -> List[MemoryRelationship]:
        """
        Get all relationships for a memory.

        Args:
            memory_id: Memory identifier
            relationship_type: Filter by type (None = all types)
            direction: "outgoing" (from this memory), "incoming" (to this memory), or "both"

        Returns:
            List of relationships ordered by weight descending
        """
        with get_connection(self.db_path) as conn:
            if direction == "outgoing":
                query = """
                    SELECT id, from_memory_id, to_memory_id, relationship_type,
                           weight, created_at, auto_detected
                    FROM memory_relationships
                    WHERE from_memory_id = ?
                """
                params = [memory_id]
            elif direction == "incoming":
                query = """
                    SELECT id, from_memory_id, to_memory_id, relationship_type,
                           weight, created_at, auto_detected
                    FROM memory_relationships
                    WHERE to_memory_id = ?
                """
                params = [memory_id]
            else:  # both
                query = """
                    SELECT id, from_memory_id, to_memory_id, relationship_type,
                           weight, created_at, auto_detected
                    FROM memory_relationships
                    WHERE from_memory_id = ? OR to_memory_id = ?
                """
                params = [memory_id, memory_id]

            if relationship_type:
                query += " AND relationship_type = ?"
                params.append(relationship_type)

            query += " ORDER BY weight DESC"

            cursor = conn.execute(query, params)

            relationships = []
            for row in cursor.fetchall():
                relationships.append(MemoryRelationship(
                    id=row[0],
                    from_memory_id=row[1],
                    to_memory_id=row[2],
                    relationship_type=row[3],
                    weight=row[4],
                    created_at=datetime.fromtimestamp(row[5]),
                    auto_detected=bool(row[6])
                ))

            return relationships

    def get_predecessors(
        self,
        memory_id: str,
        relationship_type: RelationshipType = "led_to"
    ) -> List[str]:
        """
        Get memories that led to this one (causal chain backwards).

        Args:
            memory_id: Memory identifier
            relationship_type: Type of relationship (default: "led_to")

        Returns:
            List of memory IDs that came before this one
        """
        relationships = self.get_relationships(
            memory_id,
            relationship_type=relationship_type,
            direction="incoming"
        )

        return [rel.from_memory_id for rel in relationships]

    def get_successors(
        self,
        memory_id: str,
        relationship_type: RelationshipType = "led_to"
    ) -> List[str]:
        """
        Get memories that came after this one (causal chain forwards).

        Args:
            memory_id: Memory identifier
            relationship_type: Type of relationship (default: "led_to")

        Returns:
            List of memory IDs that came after this one
        """
        relationships = self.get_relationships(
            memory_id,
            relationship_type=relationship_type,
            direction="outgoing"
        )

        return [rel.to_memory_id for rel in relationships]

    def get_contradictions(self, memory_id: str) -> List[str]:
        """
        Find all memories that contradict this one.

        Args:
            memory_id: Memory identifier

        Returns:
            List of memory IDs that contradict this memory
        """
        # Check both directions - A contradicts B means B contradicts A
        outgoing = self.get_relationships(memory_id, "contradicts", "outgoing")
        incoming = self.get_relationships(memory_id, "contradicts", "incoming")

        contradictions = set()
        for rel in outgoing:
            contradictions.add(rel.to_memory_id)
        for rel in incoming:
            contradictions.add(rel.from_memory_id)

        return list(contradictions)

    def get_references(self, memory_id: str) -> List[str]:
        """
        Get all memories referenced by this one.

        Args:
            memory_id: Memory identifier

        Returns:
            List of memory IDs referenced by this memory
        """
        relationships = self.get_relationships(memory_id, "references", "outgoing")
        return [rel.to_memory_id for rel in relationships]

    def get_cited_by(self, memory_id: str) -> List[str]:
        """
        Get all memories that reference this one.

        Args:
            memory_id: Memory identifier

        Returns:
            List of memory IDs that cite this memory
        """
        relationships = self.get_relationships(memory_id, "references", "incoming")
        return [rel.from_memory_id for rel in relationships]

    def remove_relationship(self, relationship_id: int) -> bool:
        """
        Remove a relationship.

        Args:
            relationship_id: Relationship to remove

        Returns:
            True if removed, False if not found
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM memory_relationships
                WHERE id = ?
            """, (relationship_id,))

            conn.commit()
            return cursor.rowcount > 0

    def get_memory_graph(
        self,
        memory_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[RelationshipType]] = None
    ) -> dict:
        """
        Get subgraph centered on a memory (breadth-first traversal).

        Args:
            memory_id: Center node
            max_depth: Maximum hops from center (1 = direct connections only)
            relationship_types: Filter by types (None = all types)

        Returns:
            {
                "nodes": [memory_ids],
                "edges": [(from, to, type, weight)]
            }
        """
        nodes = {memory_id}
        edges_set = set()  # Use set to dedupe edges
        queue = [(memory_id, 0)]
        visited = set()

        while queue:
            current_id, depth = queue.pop(0)

            if current_id in visited or depth >= max_depth:
                continue

            visited.add(current_id)

            # Get all relationships for this node
            relationships = self.get_relationships(current_id, direction="both")

            for rel in relationships:
                # Filter by type if specified
                if relationship_types and rel.relationship_type not in relationship_types:
                    continue

                # Add edge (use tuple for deduping)
                edge = (
                    rel.from_memory_id,
                    rel.to_memory_id,
                    rel.relationship_type,
                    rel.weight
                )
                edges_set.add(edge)

                # Add neighbor to graph
                if rel.from_memory_id == current_id:
                    neighbor = rel.to_memory_id
                else:
                    neighbor = rel.from_memory_id

                nodes.add(neighbor)

                # Queue neighbor for exploration
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))

        return {
            "nodes": list(nodes),
            "edges": list(edges_set)
        }

    def get_relationship_count(self, memory_id: str) -> int:
        """
        Count total relationships for a memory.

        Args:
            memory_id: Memory identifier

        Returns:
            Total number of relationships (incoming + outgoing)
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*)
                FROM memory_relationships
                WHERE from_memory_id = ? OR to_memory_id = ?
            """, (memory_id, memory_id))

            return cursor.fetchone()[0]
