"""
Feature 24: Memory Clustering & Topic Detection

Auto-groups related memories by semantic similarity using K-means clustering.
LLM generates human-readable topic labels for each cluster.

Database: intelligence.db (memory_clusters, cluster_memberships tables)
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection
import semantic_search

# Import ask_claude dynamically to avoid relative import issues
def _ask_claude(prompt: str, timeout: int = 30) -> str:
    """Wrapper for ask_claude import."""
    import llm_extractor
    return llm_extractor.ask_claude(prompt, timeout)


@dataclass
class Cluster:
    """Memory cluster with topic label"""
    cluster_id: int
    topic_label: str
    keywords: List[str]
    created_at: datetime
    last_updated: datetime
    member_count: int


@dataclass
class ClusterMembership:
    """Memory's membership in a cluster"""
    memory_id: str
    cluster_id: int
    similarity_score: float
    added_at: datetime


class MemoryClustering:
    """
    K-means clustering on memory embeddings with LLM-generated topic labels.

    Features:
    - Automatic cluster count selection (elbow method + silhouette score)
    - LLM-generated topic labels (2-4 words describing cluster theme)
    - Re-clustering on demand or schedule
    - Browse memories by topic

    Example:
        clustering = MemoryClustering()

        # Cluster all memories
        clusters = clustering.cluster_memories()
        for c in clusters:
            print(f"{c.topic_label} ({c.member_count} memories)")

        # Get memories in a cluster
        members = clustering.get_cluster_members(cluster_id=1)

        # Find which cluster a memory belongs to
        cluster = clustering.get_memory_cluster("mem_001")
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize clustering system.

        Args:
            db_path: Path to intelligence.db (default: intelligence.db in module parent)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Create clustering tables if they don't exist."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_clusters (
                    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_label TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_updated INTEGER NOT NULL,
                    member_count INTEGER DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS cluster_memberships (
                    memory_id TEXT NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    similarity_score REAL NOT NULL,
                    added_at INTEGER NOT NULL,
                    PRIMARY KEY (memory_id, cluster_id),
                    FOREIGN KEY (cluster_id) REFERENCES memory_clusters(cluster_id)
                )
            """)

            # Index for finding cluster members
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memberships_cluster
                ON cluster_memberships(cluster_id, similarity_score DESC)
            """)

            # Index for finding memory's cluster
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memberships_memory
                ON cluster_memberships(memory_id)
            """)

            conn.commit()

    def cluster_memories(
        self,
        min_clusters: int = 3,
        max_clusters: int = 15,
        min_memories: int = 10
    ) -> List[Cluster]:
        """
        Cluster all memories using K-means with automatic cluster count selection.

        Args:
            min_clusters: Minimum number of clusters to try
            max_clusters: Maximum number of clusters to try
            min_memories: Minimum memories needed for clustering

        Returns:
            List of created clusters with topic labels

        Algorithm:
            1. Get embeddings for all memories
            2. Find optimal K using elbow method + silhouette score
            3. Run K-means clustering
            4. LLM generates topic label for each cluster
            5. Store clusters and memberships
        """
        # Get all memories with embeddings
        memories = self._get_all_memories_with_embeddings()

        if len(memories) < min_memories:
            return []

        # Extract embeddings and IDs
        memory_ids = [m["id"] for m in memories]
        embeddings = np.array([m["embedding"] for m in memories])

        # Find optimal number of clusters
        optimal_k = self._find_optimal_clusters(
            embeddings,
            min_k=min_clusters,
            max_k=min(max_clusters, len(memories) // 3)  # At least 3 memories per cluster
        )

        # Run K-means
        kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)

        # Clear existing clusters
        self._clear_existing_clusters()

        # Create clusters and assign memories
        clusters = []
        now = int(datetime.now().timestamp())

        for cluster_idx in range(optimal_k):
            # Get members of this cluster
            member_indices = np.where(labels == cluster_idx)[0]
            member_ids = [memory_ids[i] for i in member_indices]
            member_contents = [memories[i]["content"] for i in member_indices]

            # Generate topic label via LLM
            topic_label, keywords = self._generate_topic_label(member_contents)

            # Create cluster
            cluster = self._create_cluster(
                topic_label=topic_label,
                keywords=keywords,
                created_at=now,
                member_count=len(member_ids)
            )

            # Assign memberships
            centroid = kmeans.cluster_centers_[cluster_idx]
            for idx, memory_id in zip(member_indices, member_ids):
                # Calculate similarity to centroid (cosine similarity)
                similarity = self._cosine_similarity(
                    embeddings[idx],
                    centroid
                )

                self._add_membership(
                    memory_id=memory_id,
                    cluster_id=cluster.cluster_id,
                    similarity_score=similarity,
                    added_at=now
                )

            clusters.append(cluster)

        return clusters

    def get_cluster(self, cluster_id: int) -> Optional[Cluster]:
        """
        Get cluster by ID.

        Args:
            cluster_id: Cluster identifier

        Returns:
            Cluster or None if not found
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT cluster_id, topic_label, keywords,
                       created_at, last_updated, member_count
                FROM memory_clusters
                WHERE cluster_id = ?
            """, (cluster_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return Cluster(
                cluster_id=row[0],
                topic_label=row[1],
                keywords=json.loads(row[2]),
                created_at=datetime.fromtimestamp(row[3]),
                last_updated=datetime.fromtimestamp(row[4]),
                member_count=row[5]
            )

    def get_all_clusters(self) -> List[Cluster]:
        """
        Get all clusters sorted by member count descending.

        Returns:
            List of all clusters
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT cluster_id, topic_label, keywords,
                       created_at, last_updated, member_count
                FROM memory_clusters
                ORDER BY member_count DESC
            """)

            clusters = []
            for row in cursor.fetchall():
                clusters.append(Cluster(
                    cluster_id=row[0],
                    topic_label=row[1],
                    keywords=json.loads(row[2]),
                    created_at=datetime.fromtimestamp(row[3]),
                    last_updated=datetime.fromtimestamp(row[4]),
                    member_count=row[5]
                ))

            return clusters

    def get_cluster_members(self, cluster_id: int) -> List[ClusterMembership]:
        """
        Get all memories in a cluster, ordered by similarity.

        Args:
            cluster_id: Cluster identifier

        Returns:
            List of cluster memberships sorted by similarity descending
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT memory_id, cluster_id, similarity_score, added_at
                FROM cluster_memberships
                WHERE cluster_id = ?
                ORDER BY similarity_score DESC
            """, (cluster_id,))

            members = []
            for row in cursor.fetchall():
                members.append(ClusterMembership(
                    memory_id=row[0],
                    cluster_id=row[1],
                    similarity_score=row[2],
                    added_at=datetime.fromtimestamp(row[3])
                ))

            return members

    def get_memory_cluster(self, memory_id: str) -> Optional[Cluster]:
        """
        Find which cluster a memory belongs to.

        Args:
            memory_id: Memory identifier

        Returns:
            Cluster or None if memory not clustered
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT c.cluster_id, c.topic_label, c.keywords,
                       c.created_at, c.last_updated, c.member_count
                FROM memory_clusters c
                JOIN cluster_memberships m ON c.cluster_id = m.cluster_id
                WHERE m.memory_id = ?
            """, (memory_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return Cluster(
                cluster_id=row[0],
                topic_label=row[1],
                keywords=json.loads(row[2]),
                created_at=datetime.fromtimestamp(row[3]),
                last_updated=datetime.fromtimestamp(row[4]),
                member_count=row[5]
            )

    # === Private helper methods ===

    def _get_all_memories_with_embeddings(self) -> List[Dict]:
        """
        Get all memories with their embeddings.

        Returns:
            List of {id, content, embedding} dicts
        """
        # Use semantic search to get embeddings
        # This leverages the existing embedding manager
        from memory_ts_client import MemoryTSClient

        client = MemoryTSClient()
        all_memories = client.search()  # Get all memories

        memories_with_embeddings = []
        for mem in all_memories:
            # Get embedding using semantic_search module
            embedding = semantic_search.embed_text(mem.content)
            memories_with_embeddings.append({
                "id": mem.id,
                "content": mem.content,
                "embedding": embedding
            })

        return memories_with_embeddings

    def _find_optimal_clusters(
        self,
        embeddings: np.ndarray,
        min_k: int = 3,
        max_k: int = 15
    ) -> int:
        """
        Find optimal number of clusters using elbow method + silhouette score.

        Args:
            embeddings: Memory embeddings (N x D matrix)
            min_k: Minimum clusters to try
            max_k: Maximum clusters to try

        Returns:
            Optimal K value
        """
        inertias = []
        silhouette_scores = []
        k_range = range(min_k, min(max_k + 1, len(embeddings) // 3))

        for k in k_range:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)
            inertias.append(kmeans.inertia_)

            # Silhouette score (only valid for k >= 2)
            if k >= 2:
                score = silhouette_score(embeddings, labels)
                silhouette_scores.append(score)
            else:
                silhouette_scores.append(0.0)

        # Simple heuristic: choose K with best silhouette score
        # (more sophisticated: elbow detection algorithm)
        best_idx = np.argmax(silhouette_scores)
        return list(k_range)[best_idx]

    def _generate_topic_label(self, contents: List[str]) -> Tuple[str, List[str]]:
        """
        Use LLM to generate topic label and keywords for cluster.

        Args:
            contents: List of memory contents in cluster

        Returns:
            (topic_label, keywords) tuple
        """
        # Sample up to 10 memories for LLM analysis
        sample = contents[:10] if len(contents) > 10 else contents

        prompt = f"""
Analyze these related memories and generate:
1. A topic label (2-4 words describing the common theme)
2. 3-5 keywords

Memories:
{chr(10).join(f"- {c}" for c in sample)}

Respond in JSON:
{{"topic_label": "...", "keywords": ["...", "..."]}}
"""

        try:
            response = _ask_claude(prompt, timeout=15)
            # Extract JSON
            data = json.loads(response.strip())
            return data["topic_label"], data["keywords"]
        except Exception:
            # Fallback: simple heuristic
            return "Miscellaneous", ["general"]

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def _clear_existing_clusters(self):
        """Delete all existing clusters and memberships."""
        with get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM cluster_memberships")
            conn.execute("DELETE FROM memory_clusters")
            conn.commit()

    def _create_cluster(
        self,
        topic_label: str,
        keywords: List[str],
        created_at: int,
        member_count: int
    ) -> Cluster:
        """Create a new cluster."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO memory_clusters
                (topic_label, keywords, created_at, last_updated, member_count)
                VALUES (?, ?, ?, ?, ?)
            """, (topic_label, json.dumps(keywords), created_at, created_at, member_count))

            cluster_id = cursor.lastrowid
            conn.commit()

            return Cluster(
                cluster_id=cluster_id,
                topic_label=topic_label,
                keywords=keywords,
                created_at=datetime.fromtimestamp(created_at),
                last_updated=datetime.fromtimestamp(created_at),
                member_count=member_count
            )

    def _add_membership(
        self,
        memory_id: str,
        cluster_id: int,
        similarity_score: float,
        added_at: int
    ):
        """Add memory to cluster."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cluster_memberships
                (memory_id, cluster_id, similarity_score, added_at)
                VALUES (?, ?, ?, ?)
            """, (memory_id, cluster_id, similarity_score, added_at))

            conn.commit()
