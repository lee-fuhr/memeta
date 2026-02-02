"""
Tests for memory clustering - groups related memories by keyword themes

Tests keyword extraction, similarity calculation, cluster formation,
cluster naming, and integration with memory-ts.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory_ts_client import MemoryTSClient
from src.memory_clustering import (
    MemoryClustering,
    MemoryCluster,
    extract_keywords,
    keyword_similarity,
)


@pytest.fixture
def memory_dir(tmp_path):
    """Create temporary memory directory"""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def memory_client(memory_dir):
    """Create memory-ts client"""
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def db_path(tmp_path):
    """Cluster database path"""
    return tmp_path / "clusters.db"


def seed_memories(memory_client):
    """Create a set of memories across several themes"""
    memories_data = [
        ("Always validate user input at system boundaries", "LFI", 0.8),
        ("Input validation prevents injection attacks", "ClientA", 0.7),
        ("Sanitize all external data before processing", "ClientB", 0.7),
        ("Use structured logging with context fields", "LFI", 0.6),
        ("Log context helps debugging in production", "ClientA", 0.6),
        ("CSS grid layouts work better than flexbox for page structure", "LFI", 0.5),
        ("Responsive grid layouts need mobile-first breakpoints", "ClientB", 0.5),
    ]
    ids = []
    for content, project, importance in memories_data:
        mem = memory_client.create(
            content=content,
            project_id=project,
            tags=["#learning"],
            importance=importance,
            scope="project",
        )
        ids.append(mem.id)
    return ids


class TestExtractKeywords:
    """Test keyword extraction from memory content"""

    def test_extracts_meaningful_words(self):
        """Should extract meaningful words, not stopwords"""
        keywords = extract_keywords("Always validate user input at system boundaries")
        assert "validate" in keywords
        assert "input" in keywords
        assert "boundaries" in keywords

    def test_filters_stopwords(self):
        """Should filter common stopwords"""
        keywords = extract_keywords("the quick brown fox jumped over the lazy dog")
        assert "the" not in keywords
        assert "over" not in keywords

    def test_lowercase(self):
        """Should return lowercase keywords"""
        keywords = extract_keywords("VALIDATE User INPUT")
        assert "validate" in keywords
        assert "user" in keywords

    def test_empty_string(self):
        """Should handle empty string"""
        keywords = extract_keywords("")
        assert keywords == set()

    def test_returns_set(self):
        """Should return a set (no duplicates)"""
        keywords = extract_keywords("test test test unique")
        assert isinstance(keywords, set)


class TestKeywordSimilarity:
    """Test keyword-based similarity between memories"""

    def test_identical_keywords(self):
        """Identical keyword sets should score 1.0"""
        score = keyword_similarity(
            {"validate", "input", "boundaries"},
            {"validate", "input", "boundaries"},
        )
        assert score == 1.0

    def test_no_overlap(self):
        """No shared keywords should score 0.0"""
        score = keyword_similarity(
            {"validate", "input", "boundaries"},
            {"grid", "layout", "responsive"},
        )
        assert score == 0.0

    def test_partial_overlap(self):
        """Partial overlap should score between 0 and 1"""
        score = keyword_similarity(
            {"validate", "input", "boundaries", "system"},
            {"validate", "input", "data", "processing"},
        )
        assert 0.0 < score < 1.0

    def test_empty_sets(self):
        """Empty sets should score 0.0"""
        assert keyword_similarity(set(), {"word"}) == 0.0
        assert keyword_similarity({"word"}, set()) == 0.0
        assert keyword_similarity(set(), set()) == 0.0


class TestMemoryCluster:
    """Test MemoryCluster data structure"""

    def test_create_cluster(self):
        """Should create cluster with required fields"""
        cluster = MemoryCluster(
            cluster_id="cluster-001",
            name="input validation",
            keywords=["validate", "input", "boundaries"],
            memory_ids=["mem-001", "mem-002"],
        )
        assert cluster.name == "input validation"
        assert len(cluster.memory_ids) == 2


class TestMemoryClustering:
    """Test clustering algorithm"""

    def test_clusters_similar_memories(self, memory_dir, memory_client, db_path):
        """Should group similar memories into clusters"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        # Should have at least 2 distinct clusters
        assert len(clusters) >= 2

    def test_cluster_has_name(self, memory_dir, memory_client, db_path):
        """Each cluster should have a descriptive name"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        for cluster in clusters:
            assert cluster.name is not None
            assert len(cluster.name) > 0

    def test_cluster_has_keywords(self, memory_dir, memory_client, db_path):
        """Each cluster should have keywords"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        for cluster in clusters:
            assert len(cluster.keywords) > 0

    def test_cluster_has_memory_ids(self, memory_dir, memory_client, db_path):
        """Each cluster should reference at least 1 memory"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        for cluster in clusters:
            assert len(cluster.memory_ids) >= 1

    def test_all_memories_assigned(self, memory_dir, memory_client, db_path):
        """Every memory should appear in at least one cluster"""
        ids = seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        all_clustered_ids = set()
        for cluster in clusters:
            all_clustered_ids.update(cluster.memory_ids)

        for mem_id in ids:
            assert mem_id in all_clustered_ids

    def test_custom_threshold(self, memory_dir, memory_client, db_path):
        """Should respect custom similarity threshold"""
        seed_memories(memory_client)

        # Very high threshold = more smaller clusters
        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
            similarity_threshold=0.8,
        )

        clusters_high = clustering.build_clusters()

        # Very low threshold = fewer bigger clusters
        clustering_low = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
            similarity_threshold=0.1,
        )

        clusters_low = clustering_low.build_clusters()

        # Lower threshold should produce fewer or equal clusters
        assert len(clusters_low) <= len(clusters_high)

    def test_empty_memory_dir(self, memory_dir, db_path):
        """Should handle empty memory directory"""
        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()
        assert clusters == []

    def test_single_memory(self, memory_dir, memory_client, db_path):
        """Should handle single memory (creates one cluster)"""
        memory_client.create(
            content="Only memory in the system",
            project_id="LFI",
            tags=["#learning"],
            importance=0.5,
            scope="project",
        )

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()
        assert len(clusters) == 1

    def test_persists_clusters(self, memory_dir, memory_client, db_path):
        """Should save clusters to database"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()

        # Load from DB
        loaded = clustering.get_clusters()
        assert len(loaded) == len(clusters)

    def test_get_cluster_by_id(self, memory_dir, memory_client, db_path):
        """Should retrieve specific cluster by ID"""
        seed_memories(memory_client)

        clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=db_path,
        )

        clusters = clustering.build_clusters()
        first_id = clusters[0].cluster_id

        loaded = clustering.get_cluster(first_id)
        assert loaded is not None
        assert loaded.cluster_id == first_id
