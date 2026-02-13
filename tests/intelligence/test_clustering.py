"""
Tests for Feature 24: Memory Clustering & Topic Detection
"""

import pytest
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from intelligence.clustering import MemoryClustering, Cluster, ClusterMembership
from memory_ts_client import MemoryTSClient


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def clustering(temp_db):
    """Create clustering instance with temp database."""
    return MemoryClustering(db_path=temp_db)


@pytest.fixture
def sample_memories():
    """Sample memories for testing (diverse topics)."""
    return [
        "Always run tests before claiming completion",
        "Verify tests pass before marking task done",
        "Test-driven development prevents bugs",
        "User wants dark mode toggle in settings",
        "Add theme switcher to navigation bar",
        "Support light and dark color schemes",
        "Database connection pooling prevents SQLITE_BUSY",
        "Use connection pool to avoid lock contention",
        "SQLite WAL mode improves concurrency",
        "LLM retry logic with exponential backoff",
        "Implement retry strategy for API failures",
        "Handle API errors gracefully with retries"
    ]


def test_init_creates_tables(clustering, temp_db):
    """Test that initialization creates required tables."""
    from db_pool import get_connection

    with get_connection(temp_db) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('memory_clusters', 'cluster_memberships')
        """)
        tables = {row[0] for row in cursor.fetchall()}

    assert "memory_clusters" in tables
    assert "cluster_memberships" in tables


@pytest.mark.skip(reason="Requires sentence-transformers (heavy dependency)")
def test_cluster_empty_memories(clustering):
    """Test clustering with no memories returns empty list."""
    clusters = clustering.cluster_memories(min_memories=10)
    assert clusters == []


@pytest.mark.skip(reason="Requires sentence-transformers (heavy dependency)")
def test_cluster_insufficient_memories(clustering):
    """Test clustering with too few memories returns empty list."""
    # Would need to add memories first, but min_memories check happens before
    clusters = clustering.cluster_memories(min_memories=100)
    assert clusters == []


def test_find_optimal_clusters():
    """Test optimal cluster selection algorithm."""
    clustering = MemoryClustering()

    # Create synthetic data with clear clusters
    np.random.seed(42)

    # 3 clusters of 10 points each
    cluster1 = np.random.randn(10, 384) + np.array([5.0] * 384)
    cluster2 = np.random.randn(10, 384) + np.array([-5.0] * 384)
    cluster3 = np.random.randn(10, 384) + np.array([0.0] * 384)

    embeddings = np.vstack([cluster1, cluster2, cluster3])

    optimal_k = clustering._find_optimal_clusters(embeddings, min_k=2, max_k=5)

    # Should find 3 clusters (or close to it)
    assert 2 <= optimal_k <= 4


def test_cosine_similarity(clustering):
    """Test cosine similarity calculation."""
    vec1 = np.array([1.0, 0.0, 0.0])
    vec2 = np.array([1.0, 0.0, 0.0])
    vec3 = np.array([0.0, 1.0, 0.0])

    # Identical vectors
    sim1 = clustering._cosine_similarity(vec1, vec2)
    assert abs(sim1 - 1.0) < 0.001

    # Orthogonal vectors
    sim2 = clustering._cosine_similarity(vec1, vec3)
    assert abs(sim2 - 0.0) < 0.001

    # Zero vector
    zero = np.array([0.0, 0.0, 0.0])
    sim3 = clustering._cosine_similarity(vec1, zero)
    assert sim3 == 0.0


def test_create_cluster(clustering):
    """Test cluster creation."""
    now = int(datetime.now().timestamp())

    cluster = clustering._create_cluster(
        topic_label="Testing Best Practices",
        keywords=["testing", "verification", "quality"],
        created_at=now,
        member_count=5
    )

    assert cluster.cluster_id > 0
    assert cluster.topic_label == "Testing Best Practices"
    assert cluster.keywords == ["testing", "verification", "quality"]
    assert cluster.member_count == 5


def test_add_membership(clustering):
    """Test adding memory to cluster."""
    now = int(datetime.now().timestamp())

    # Create cluster first
    cluster = clustering._create_cluster(
        topic_label="Test Cluster",
        keywords=["test"],
        created_at=now,
        member_count=0
    )

    # Add membership
    clustering._add_membership(
        memory_id="mem_001",
        cluster_id=cluster.cluster_id,
        similarity_score=0.95,
        added_at=now
    )

    # Verify membership exists
    members = clustering.get_cluster_members(cluster.cluster_id)
    assert len(members) == 1
    assert members[0].memory_id == "mem_001"
    assert abs(members[0].similarity_score - 0.95) < 0.001


def test_get_cluster(clustering):
    """Test retrieving cluster by ID."""
    now = int(datetime.now().timestamp())

    cluster = clustering._create_cluster(
        topic_label="Database Performance",
        keywords=["database", "performance", "optimization"],
        created_at=now,
        member_count=3
    )

    retrieved = clustering.get_cluster(cluster.cluster_id)

    assert retrieved is not None
    assert retrieved.cluster_id == cluster.cluster_id
    assert retrieved.topic_label == "Database Performance"
    assert retrieved.keywords == ["database", "performance", "optimization"]
    assert retrieved.member_count == 3


def test_get_cluster_nonexistent(clustering):
    """Test retrieving nonexistent cluster returns None."""
    cluster = clustering.get_cluster(999)
    assert cluster is None


def test_get_all_clusters(clustering):
    """Test retrieving all clusters."""
    now = int(datetime.now().timestamp())

    # Create multiple clusters
    c1 = clustering._create_cluster("Cluster 1", ["k1"], now, 5)
    c2 = clustering._create_cluster("Cluster 2", ["k2"], now, 10)
    c3 = clustering._create_cluster("Cluster 3", ["k3"], now, 3)

    clusters = clustering.get_all_clusters()

    assert len(clusters) == 3
    # Should be sorted by member count descending
    assert clusters[0].member_count == 10
    assert clusters[1].member_count == 5
    assert clusters[2].member_count == 3


def test_get_all_clusters_empty(clustering):
    """Test retrieving clusters when none exist."""
    clusters = clustering.get_all_clusters()
    assert clusters == []


def test_get_cluster_members(clustering):
    """Test retrieving members of a cluster."""
    now = int(datetime.now().timestamp())

    cluster = clustering._create_cluster("Test", ["test"], now, 3)

    # Add multiple members
    clustering._add_membership("mem_001", cluster.cluster_id, 0.95, now)
    clustering._add_membership("mem_002", cluster.cluster_id, 0.85, now)
    clustering._add_membership("mem_003", cluster.cluster_id, 0.75, now)

    members = clustering.get_cluster_members(cluster.cluster_id)

    assert len(members) == 3
    # Should be sorted by similarity descending
    assert members[0].memory_id == "mem_001"
    assert members[1].memory_id == "mem_002"
    assert members[2].memory_id == "mem_003"


def test_get_cluster_members_empty(clustering):
    """Test retrieving members from empty cluster."""
    now = int(datetime.now().timestamp())
    cluster = clustering._create_cluster("Empty", ["empty"], now, 0)

    members = clustering.get_cluster_members(cluster.cluster_id)
    assert members == []


def test_get_memory_cluster(clustering):
    """Test finding which cluster a memory belongs to."""
    now = int(datetime.now().timestamp())

    c1 = clustering._create_cluster("Cluster 1", ["k1"], now, 1)
    c2 = clustering._create_cluster("Cluster 2", ["k2"], now, 1)

    clustering._add_membership("mem_001", c1.cluster_id, 0.9, now)
    clustering._add_membership("mem_002", c2.cluster_id, 0.8, now)

    cluster = clustering.get_memory_cluster("mem_001")

    assert cluster is not None
    assert cluster.cluster_id == c1.cluster_id
    assert cluster.topic_label == "Cluster 1"


def test_get_memory_cluster_nonexistent(clustering):
    """Test finding cluster for unclustered memory returns None."""
    cluster = clustering.get_memory_cluster("nonexistent")
    assert cluster is None


def test_clear_existing_clusters(clustering):
    """Test clearing all clusters and memberships."""
    now = int(datetime.now().timestamp())

    # Create clusters and memberships
    c1 = clustering._create_cluster("C1", ["k1"], now, 1)
    clustering._add_membership("mem_001", c1.cluster_id, 0.9, now)

    # Clear
    clustering._clear_existing_clusters()

    # Verify empty
    assert clustering.get_all_clusters() == []
    assert clustering.get_cluster_members(c1.cluster_id) == []


def test_generate_topic_label_fallback(clustering):
    """Test topic label generation fallback when LLM fails."""
    # Test with contents that might cause LLM issues
    contents = ["test"] * 5

    topic, keywords = clustering._generate_topic_label(contents)

    # Should get fallback values
    assert isinstance(topic, str)
    assert isinstance(keywords, list)
    assert len(topic) > 0
    assert len(keywords) > 0
