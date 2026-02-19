"""
Schema assimilation/accommodation classifier.

Based on Bartlett's schema theory (1932) and Piaget's assimilation/accommodation.
When a new memory arrives, classifies how it relates to existing knowledge:

- **Assimilation** (fits existing cluster): cosine distance to centroid < 0.3
- **Extension** (borderline, stretches the schema): distance 0.3–0.6
- **Accommodation** (changes understanding): distance > 0.6

Accommodation events trigger alerts indicating a shift in understanding.

Usage:
    from memory_system.schema_classifier import SchemaClassifier, SchemaEvent

    sc = SchemaClassifier(db_path="intelligence.db")

    # Classify a new memory against its cluster neighbors
    event = sc.classify(new_embedding, neighbor_embeddings, cluster_id="topic_5")

    # Query accommodation events (schema shifts)
    shifts = sc.get_accommodation_events(limit=10)

    # Check cluster stability
    stability = sc.get_cluster_stability("topic_5")
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SchemaEvent:
    """A classification event for a new memory against its schema."""
    memory_id: str
    event_type: str  # 'assimilation', 'extension', 'accommodation'
    cluster_id: Optional[str]
    distance_from_centroid: float
    timestamp: str


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class SchemaClassifier:
    """
    Classifies new memories as assimilation, extension, or accommodation
    based on cosine distance from the centroid of their nearest neighbors.
    """

    ASSIMILATION_THRESHOLD = 0.3
    EXTENSION_THRESHOLD = 0.6

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the schema_events table and indexes if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    cluster_id TEXT,
                    distance_from_centroid REAL NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schema_type ON schema_events(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schema_cluster ON schema_events(cluster_id)"
            )
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # Vector math
    # ------------------------------------------------------------------

    def compute_centroid(self, embeddings: list[list[float]]) -> list[float]:
        """Compute the centroid (mean) of a list of embeddings.

        Args:
            embeddings: List of embedding vectors (must be non-empty).

        Returns:
            The mean vector.

        Raises:
            ValueError: If embeddings list is empty.
        """
        if not embeddings:
            raise ValueError("Cannot compute centroid of empty embedding list.")
        arr = np.array(embeddings, dtype=np.float64)
        centroid = np.mean(arr, axis=0)
        return centroid.tolist()

    def cosine_distance(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine distance (1 - cosine_similarity) between two vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine distance in range [0, 2].

        Raises:
            ValueError: If either vector has zero magnitude.
        """
        a = np.array(vec_a, dtype=np.float64)
        b = np.array(vec_b, dtype=np.float64)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            raise ValueError("Cannot compute cosine distance with a zero vector.")
        similarity = np.dot(a, b) / (norm_a * norm_b)
        # Clamp to [-1, 1] to handle floating point edge cases
        similarity = float(np.clip(similarity, -1.0, 1.0))
        return 1.0 - similarity

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(
        self,
        new_embedding: list[float],
        neighbor_embeddings: list[list[float]],
        cluster_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        persist: bool = True,
    ) -> SchemaEvent:
        """Classify a new memory against its nearest neighbors.

        Computes cosine distance from the new embedding to the centroid
        of the neighbor embeddings, then classifies:
        - distance < 0.3 → assimilation
        - 0.3 <= distance <= 0.6 → extension
        - distance > 0.6 → accommodation

        Args:
            new_embedding: The embedding of the new memory.
            neighbor_embeddings: Embeddings of the cluster's existing memories.
            cluster_id: Optional cluster identifier.
            memory_id: Optional memory identifier (auto-generated if not provided).
            persist: If True (default), record the event to the database.
                Set to False for classify-only mode with no side effects.

        Returns:
            A SchemaEvent describing the classification.

        Raises:
            ValueError: If neighbor_embeddings is empty.
        """
        if not neighbor_embeddings:
            raise ValueError("Cannot classify against empty neighbor list.")

        centroid = self.compute_centroid(neighbor_embeddings)
        distance = self.cosine_distance(new_embedding, centroid)

        if distance < self.ASSIMILATION_THRESHOLD:
            event_type = "assimilation"
        elif distance <= self.EXTENSION_THRESHOLD:
            event_type = "extension"
        else:
            event_type = "accommodation"

        if memory_id is None:
            memory_id = f"mem_{uuid.uuid4().hex[:12]}"

        event = SchemaEvent(
            memory_id=memory_id,
            event_type=event_type,
            cluster_id=cluster_id,
            distance_from_centroid=round(distance, 6),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if persist:
            self.record_event(event)
        return event

    # ------------------------------------------------------------------
    # Event storage
    # ------------------------------------------------------------------

    def record_event(self, event: SchemaEvent) -> None:
        """Store a schema event in the database.

        Args:
            event: The SchemaEvent to persist.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO schema_events
                    (memory_id, event_type, cluster_id, distance_from_centroid, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.memory_id,
                    event.event_type,
                    event.cluster_id,
                    event.distance_from_centroid,
                    event.timestamp,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_accommodation_events(self, limit: int = 20) -> list[SchemaEvent]:
        """Return recent accommodation events (schema changes).

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of SchemaEvent objects, most recent first.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT memory_id, event_type, cluster_id, distance_from_centroid, timestamp
                FROM schema_events
                WHERE event_type = 'accommodation'
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                SchemaEvent(
                    memory_id=row[0],
                    event_type=row[1],
                    cluster_id=row[2],
                    distance_from_centroid=row[3],
                    timestamp=row[4],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_event_distribution(self) -> dict:
        """Return counts of each event type.

        Returns:
            Dict with keys: assimilation_count, extension_count, accommodation_count.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT event_type, COUNT(*) as cnt
                FROM schema_events
                GROUP BY event_type
                """
            )
            counts = {row[0]: row[1] for row in cursor.fetchall()}
            return {
                "assimilation_count": counts.get("assimilation", 0),
                "extension_count": counts.get("extension", 0),
                "accommodation_count": counts.get("accommodation", 0),
            }
        finally:
            conn.close()

    def get_cluster_stability(self, cluster_id: str) -> dict:
        """Return stability metrics for a cluster.

        A cluster with many accommodation events is unstable (understanding
        keeps shifting). A cluster with mostly assimilations is stable.

        Args:
            cluster_id: The cluster to analyze.

        Returns:
            Dict with keys:
            - accommodation_rate: float (0.0 = fully stable, 1.0 = fully unstable)
            - last_accommodation: str or None (ISO timestamp)
            - event_count: int (total events for this cluster)
        """
        conn = self._get_conn()
        try:
            # Total events for this cluster
            cursor = conn.execute(
                "SELECT COUNT(*) FROM schema_events WHERE cluster_id = ?",
                (cluster_id,),
            )
            event_count = cursor.fetchone()[0]

            if event_count == 0:
                return {
                    "accommodation_rate": 0.0,
                    "last_accommodation": None,
                    "event_count": 0,
                }

            # Accommodation count
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM schema_events
                WHERE cluster_id = ? AND event_type = 'accommodation'
                """,
                (cluster_id,),
            )
            accommodation_count = cursor.fetchone()[0]

            # Last accommodation timestamp
            cursor = conn.execute(
                """
                SELECT timestamp FROM schema_events
                WHERE cluster_id = ? AND event_type = 'accommodation'
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (cluster_id,),
            )
            row = cursor.fetchone()
            last_accommodation = row[0] if row else None

            return {
                "accommodation_rate": round(accommodation_count / event_count, 4),
                "last_accommodation": last_accommodation,
                "event_count": event_count,
            }
        finally:
            conn.close()
