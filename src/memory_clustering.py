"""
Memory clustering - groups related memories by keyword themes

Uses keyword extraction and co-occurrence to cluster memories
into coherent themes. No ML required - simple keyword overlap.

Algorithm:
1. Extract keywords from each memory
2. Calculate pairwise keyword similarity
3. Greedy clustering: assign each memory to most similar existing cluster
4. Name clusters by most frequent keywords
5. Persist to SQLite
"""

import re
import sqlite3
import json
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .memory_ts_client import MemoryTSClient


# Common English stopwords to filter out
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "at", "by", "for", "from", "in", "into", "of", "on", "to", "with",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "as", "until", "while",
    "about", "above", "after", "again", "against", "before", "below",
    "between", "during", "over", "through", "under",
    "that", "this", "these", "those", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "they", "them", "their", "what", "which", "who",
    "when", "where", "why", "how",
    "if", "then", "else", "also", "always", "never", "often",
    "up", "down", "out",
}

DEFAULT_SIMILARITY_THRESHOLD = 0.4


def extract_keywords(text: str) -> Set[str]:
    """
    Extract meaningful keywords from text, filtering stopwords.

    Args:
        text: Raw text string

    Returns:
        Set of lowercase keywords
    """
    text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in text_clean.split() if w]
    # Filter stopwords and very short words
    keywords = {w for w in words if w not in STOPWORDS and len(w) > 2}
    return keywords


def keyword_similarity(keywords_a: Set[str], keywords_b: Set[str]) -> float:
    """
    Calculate Jaccard similarity between two keyword sets.

    Args:
        keywords_a: First keyword set
        keywords_b: Second keyword set

    Returns:
        Similarity score 0.0-1.0
    """
    if not keywords_a or not keywords_b:
        return 0.0

    intersection = len(keywords_a & keywords_b)
    union = len(keywords_a | keywords_b)

    return intersection / union if union > 0 else 0.0


@dataclass
class MemoryCluster:
    """A cluster of related memories"""
    cluster_id: str
    name: str
    keywords: List[str]
    memory_ids: List[str]
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())


class MemoryClustering:
    """
    Groups related memories into clusters by keyword similarity.

    Uses greedy clustering with configurable similarity threshold.
    Persists clusters to SQLite for dashboard and synthesis use.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """
        Initialize clustering engine.

        Args:
            memory_dir: Path to memory-ts memories directory
            db_path: Path to SQLite database for cluster persistence
            similarity_threshold: Minimum keyword overlap to join cluster (0.0-1.0)
        """
        self.memory_client = MemoryTSClient(memory_dir=memory_dir)
        self.similarity_threshold = similarity_threshold

        if db_path is None:
            db_path = Path(__file__).parent.parent / "clusters.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Create cluster tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_clusters (
                cluster_id TEXT PRIMARY KEY,
                name TEXT,
                keywords TEXT,
                memory_ids TEXT,
                created TEXT,
                updated TEXT
            )
        """)
        conn.commit()
        conn.close()

    def build_clusters(self) -> List[MemoryCluster]:
        """
        Build clusters from all memories in memory-ts.

        Rebuilds from scratch each time (clusters are cheap to compute).

        Returns:
            List of MemoryCluster objects
        """
        memories = self.memory_client.search()
        if not memories:
            return []

        # Extract keywords for each memory
        memory_keywords: Dict[str, Set[str]] = {}
        for mem in memories:
            kw = extract_keywords(mem.content)
            if kw:
                memory_keywords[mem.id] = kw

        if not memory_keywords:
            return []

        # Greedy clustering
        clusters: List[Dict] = []
        assigned: Set[str] = set()

        memory_ids = list(memory_keywords.keys())

        for mem_id in memory_ids:
            if mem_id in assigned:
                continue

            # Find or create best cluster
            best_cluster_idx = -1
            best_score = 0.0

            for idx, cluster in enumerate(clusters):
                score = keyword_similarity(
                    memory_keywords[mem_id],
                    cluster["keywords"],
                )
                if score >= self.similarity_threshold and score > best_score:
                    best_score = score
                    best_cluster_idx = idx

            if best_cluster_idx >= 0:
                # Add to existing cluster
                clusters[best_cluster_idx]["memory_ids"].append(mem_id)
                clusters[best_cluster_idx]["keywords"] |= memory_keywords[mem_id]
            else:
                # Create new cluster
                clusters.append({
                    "memory_ids": [mem_id],
                    "keywords": set(memory_keywords[mem_id]),
                })

            assigned.add(mem_id)

        # Build MemoryCluster objects with names
        result = []
        for cluster_data in clusters:
            # Name from top 3 most common keywords across cluster members
            keyword_counts = Counter()
            for mid in cluster_data["memory_ids"]:
                keyword_counts.update(memory_keywords.get(mid, set()))

            top_keywords = [kw for kw, _ in keyword_counts.most_common(5)]
            name = " ".join(top_keywords[:3])

            cluster_id = hashlib.md5(
                json.dumps(sorted(cluster_data["memory_ids"])).encode()
            ).hexdigest()[:12]

            result.append(MemoryCluster(
                cluster_id=cluster_id,
                name=name,
                keywords=top_keywords,
                memory_ids=cluster_data["memory_ids"],
            ))

        # Persist to database
        self._save_clusters(result)

        return result

    def _save_clusters(self, clusters: List[MemoryCluster]):
        """Save clusters to SQLite, replacing existing"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM memory_clusters")

        for cluster in clusters:
            conn.execute(
                """INSERT INTO memory_clusters
                (cluster_id, name, keywords, memory_ids, created, updated)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    cluster.cluster_id,
                    cluster.name,
                    json.dumps(cluster.keywords),
                    json.dumps(cluster.memory_ids),
                    cluster.created,
                    cluster.updated,
                )
            )

        conn.commit()
        conn.close()

    def get_clusters(self) -> List[MemoryCluster]:
        """Load all clusters from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT cluster_id, name, keywords, memory_ids, created, updated "
            "FROM memory_clusters"
        )

        clusters = []
        for row in cursor.fetchall():
            clusters.append(MemoryCluster(
                cluster_id=row[0],
                name=row[1],
                keywords=json.loads(row[2]),
                memory_ids=json.loads(row[3]),
                created=row[4],
                updated=row[5],
            ))

        conn.close()
        return clusters

    def get_cluster(self, cluster_id: str) -> Optional[MemoryCluster]:
        """Load a specific cluster by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT cluster_id, name, keywords, memory_ids, created, updated "
            "FROM memory_clusters WHERE cluster_id = ?",
            (cluster_id,)
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return MemoryCluster(
            cluster_id=row[0],
            name=row[1],
            keywords=json.loads(row[2]),
            memory_ids=json.loads(row[3]),
            created=row[4],
            updated=row[5],
        )
