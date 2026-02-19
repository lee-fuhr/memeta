"""
Tests for schema assimilation/accommodation classifier.

Covers:
- SchemaEvent dataclass creation
- SchemaClassifier initialization and DB table creation
- Centroid computation (single vector, multiple vectors)
- Cosine distance (identical, orthogonal, opposite vectors)
- Classification thresholds (assimilation, extension, accommodation)
- Classification at exact boundary values
- Event recording and retrieval
- Accommodation event filtering
- Event distribution counts
- Cluster stability metrics
- Edge cases (empty embeddings, zero vectors, single neighbor)
- High-dimensional vectors
- Multiple clusters tracked independently
"""

import math
import sqlite3
from datetime import datetime

import pytest

from memory_system.schema_classifier import SchemaClassifier, SchemaEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return path to a temporary SQLite database file."""
    return str(tmp_path / "test_schema.db")


@pytest.fixture
def classifier(db_path):
    """Return a fresh SchemaClassifier with temp DB."""
    return SchemaClassifier(db_path=db_path)


# ---------------------------------------------------------------------------
# 1. SchemaEvent dataclass
# ---------------------------------------------------------------------------

class TestSchemaEvent:
    def test_create_schema_event(self):
        event = SchemaEvent(
            memory_id="mem_001",
            event_type="assimilation",
            cluster_id="cluster_5",
            distance_from_centroid=0.15,
            timestamp="2026-02-19T10:00:00",
        )
        assert event.memory_id == "mem_001"
        assert event.event_type == "assimilation"
        assert event.cluster_id == "cluster_5"
        assert event.distance_from_centroid == 0.15
        assert event.timestamp == "2026-02-19T10:00:00"

    def test_schema_event_no_cluster(self):
        event = SchemaEvent(
            memory_id="mem_002",
            event_type="accommodation",
            cluster_id=None,
            distance_from_centroid=0.85,
            timestamp="2026-02-19T11:00:00",
        )
        assert event.cluster_id is None


# ---------------------------------------------------------------------------
# 2. Classifier initialization
# ---------------------------------------------------------------------------

class TestClassifierInit:
    def test_creates_db_table(self, db_path):
        SchemaClassifier(db_path=db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_events'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_creates_indexes(self, db_path):
        SchemaClassifier(db_path=db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        index_names = [row[0] for row in cursor.fetchall()]
        assert "idx_schema_type" in index_names
        assert "idx_schema_cluster" in index_names
        conn.close()

    def test_thresholds_are_set(self, classifier):
        assert classifier.ASSIMILATION_THRESHOLD == 0.3
        assert classifier.EXTENSION_THRESHOLD == 0.6


# ---------------------------------------------------------------------------
# 3. Centroid computation
# ---------------------------------------------------------------------------

class TestComputeCentroid:
    def test_single_vector(self, classifier):
        embeddings = [[1.0, 2.0, 3.0]]
        centroid = classifier.compute_centroid(embeddings)
        assert centroid == pytest.approx([1.0, 2.0, 3.0])

    def test_multiple_vectors(self, classifier):
        embeddings = [[1.0, 0.0], [0.0, 1.0]]
        centroid = classifier.compute_centroid(embeddings)
        assert centroid == pytest.approx([0.5, 0.5])

    def test_three_vectors(self, classifier):
        embeddings = [[3.0, 6.0], [0.0, 0.0], [6.0, 3.0]]
        centroid = classifier.compute_centroid(embeddings)
        assert centroid == pytest.approx([3.0, 3.0])

    def test_empty_embeddings_raises(self, classifier):
        with pytest.raises(ValueError):
            classifier.compute_centroid([])


# ---------------------------------------------------------------------------
# 4. Cosine distance
# ---------------------------------------------------------------------------

class TestCosineDistance:
    def test_identical_vectors_distance_zero(self, classifier):
        vec = [1.0, 2.0, 3.0]
        dist = classifier.cosine_distance(vec, vec)
        assert dist == pytest.approx(0.0, abs=1e-9)

    def test_orthogonal_vectors_distance_one(self, classifier):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        dist = classifier.cosine_distance(a, b)
        assert dist == pytest.approx(1.0, abs=1e-9)

    def test_opposite_vectors_distance_two(self, classifier):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        dist = classifier.cosine_distance(a, b)
        assert dist == pytest.approx(2.0, abs=1e-9)

    def test_similar_vectors_low_distance(self, classifier):
        a = [1.0, 1.0]
        b = [1.0, 1.1]
        dist = classifier.cosine_distance(a, b)
        assert dist < 0.01

    def test_zero_vector_raises(self, classifier):
        with pytest.raises(ValueError):
            classifier.cosine_distance([0.0, 0.0], [1.0, 1.0])


# ---------------------------------------------------------------------------
# 5. Classification — core thresholds
# ---------------------------------------------------------------------------

class TestClassify:
    def test_assimilation_close_vector(self, classifier):
        """A new vector very close to existing cluster should be assimilation."""
        neighbors = [[1.0, 0.0, 0.0], [1.0, 0.1, 0.0], [1.0, -0.1, 0.0]]
        new_vec = [1.0, 0.05, 0.0]  # very similar
        event = classifier.classify(new_vec, neighbors, cluster_id="c1")
        assert event.event_type == "assimilation"
        assert event.distance_from_centroid < 0.3

    def test_accommodation_distant_vector(self, classifier):
        """A vector far from neighbors should be accommodation."""
        neighbors = [[1.0, 0.0, 0.0], [1.0, 0.1, 0.0]]
        new_vec = [0.0, 0.0, 1.0]  # orthogonal
        event = classifier.classify(new_vec, neighbors, cluster_id="c2")
        assert event.event_type == "accommodation"
        assert event.distance_from_centroid > 0.6

    def test_extension_midrange_vector(self, classifier):
        """A vector at moderate distance should be extension."""
        # Craft vectors where cosine distance to centroid is between 0.3 and 0.6
        neighbors = [[1.0, 0.0]]
        # cos_dist([1, 0], [cos(theta), sin(theta)]) = 1 - cos(theta)
        # For distance ~0.45: theta = arccos(1 - 0.45) = arccos(0.55) ≈ 56.6°
        theta = math.acos(0.55)
        new_vec = [math.cos(theta), math.sin(theta)]
        event = classifier.classify(new_vec, neighbors, cluster_id="c3")
        assert event.event_type == "extension"
        assert 0.3 <= event.distance_from_centroid <= 0.6

    def test_classify_without_cluster_id(self, classifier):
        neighbors = [[1.0, 0.0], [0.9, 0.1]]
        new_vec = [1.0, 0.05]
        event = classifier.classify(new_vec, neighbors)
        assert event.cluster_id is None
        assert event.event_type == "assimilation"

    def test_classify_memory_id_generated(self, classifier):
        neighbors = [[1.0, 0.0]]
        new_vec = [1.0, 0.01]
        event = classifier.classify(new_vec, neighbors)
        assert event.memory_id  # should be non-empty
        assert event.timestamp  # should be non-empty


# ---------------------------------------------------------------------------
# 6. Boundary values
# ---------------------------------------------------------------------------

class TestBoundaryValues:
    def test_exact_assimilation_boundary(self, classifier):
        """Distance exactly at 0.3 should be assimilation (< 0.3 is strict)."""
        # cos_distance = 0.3 means cos_sim = 0.7
        # theta = arccos(0.7) ≈ 45.57°
        neighbors = [[1.0, 0.0]]
        theta = math.acos(0.7)
        new_vec = [math.cos(theta), math.sin(theta)]
        event = classifier.classify(new_vec, neighbors)
        # At exactly 0.3, it should be extension (>= 0.3)
        assert event.event_type == "extension"

    def test_just_below_assimilation_boundary(self, classifier):
        """Distance at 0.29 should be assimilation."""
        neighbors = [[1.0, 0.0]]
        theta = math.acos(0.71)  # 1 - 0.71 = 0.29
        new_vec = [math.cos(theta), math.sin(theta)]
        event = classifier.classify(new_vec, neighbors)
        assert event.event_type == "assimilation"

    def test_exact_extension_boundary(self, classifier):
        """Distance exactly at 0.6 should be extension."""
        neighbors = [[1.0, 0.0]]
        theta = math.acos(0.4)  # 1 - 0.4 = 0.6
        new_vec = [math.cos(theta), math.sin(theta)]
        event = classifier.classify(new_vec, neighbors)
        # At exactly 0.6, should be extension (< 0.6 is strict for accommodation)
        assert event.event_type == "extension"

    def test_just_above_extension_boundary(self, classifier):
        """Distance at 0.61 should be accommodation."""
        neighbors = [[1.0, 0.0]]
        theta = math.acos(0.39)  # 1 - 0.39 = 0.61
        new_vec = [math.cos(theta), math.sin(theta)]
        event = classifier.classify(new_vec, neighbors)
        assert event.event_type == "accommodation"


# ---------------------------------------------------------------------------
# 7. Record and retrieve events
# ---------------------------------------------------------------------------

class TestRecordEvent:
    def test_record_and_retrieve_accommodation(self, classifier):
        event = SchemaEvent(
            memory_id="mem_100",
            event_type="accommodation",
            cluster_id="c1",
            distance_from_centroid=0.75,
            timestamp="2026-02-19T10:00:00",
        )
        classifier.record_event(event)
        results = classifier.get_accommodation_events(limit=10)
        assert len(results) == 1
        assert results[0].memory_id == "mem_100"
        assert results[0].event_type == "accommodation"

    def test_record_multiple_events(self, classifier):
        for i in range(5):
            event = SchemaEvent(
                memory_id=f"mem_{i}",
                event_type="assimilation",
                cluster_id="c1",
                distance_from_centroid=0.1 + i * 0.02,
                timestamp=f"2026-02-19T1{i}:00:00",
            )
            classifier.record_event(event)
        # Accommodation events should be empty
        results = classifier.get_accommodation_events()
        assert len(results) == 0

    def test_accommodation_limit(self, classifier):
        for i in range(10):
            event = SchemaEvent(
                memory_id=f"mem_{i}",
                event_type="accommodation",
                cluster_id="c1",
                distance_from_centroid=0.7 + i * 0.01,
                timestamp=f"2026-02-19T1{i}:00:00",
            )
            classifier.record_event(event)
        results = classifier.get_accommodation_events(limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# 8. Event distribution
# ---------------------------------------------------------------------------

class TestEventDistribution:
    def test_empty_distribution(self, classifier):
        dist = classifier.get_event_distribution()
        assert dist["assimilation_count"] == 0
        assert dist["extension_count"] == 0
        assert dist["accommodation_count"] == 0

    def test_mixed_distribution(self, classifier):
        events = [
            ("mem_1", "assimilation", 0.1),
            ("mem_2", "assimilation", 0.2),
            ("mem_3", "extension", 0.45),
            ("mem_4", "accommodation", 0.8),
        ]
        for mid, etype, dist_val in events:
            classifier.record_event(SchemaEvent(
                memory_id=mid,
                event_type=etype,
                cluster_id="c1",
                distance_from_centroid=dist_val,
                timestamp="2026-02-19T10:00:00",
            ))
        dist = classifier.get_event_distribution()
        assert dist["assimilation_count"] == 2
        assert dist["extension_count"] == 1
        assert dist["accommodation_count"] == 1


# ---------------------------------------------------------------------------
# 9. Cluster stability
# ---------------------------------------------------------------------------

class TestClusterStability:
    def test_stable_cluster(self, classifier):
        """Cluster with only assimilations is very stable."""
        for i in range(5):
            classifier.record_event(SchemaEvent(
                memory_id=f"mem_{i}",
                event_type="assimilation",
                cluster_id="stable_cluster",
                distance_from_centroid=0.1,
                timestamp=f"2026-02-19T1{i}:00:00",
            ))
        stability = classifier.get_cluster_stability("stable_cluster")
        assert stability["accommodation_rate"] == 0.0
        assert stability["last_accommodation"] is None
        assert stability["event_count"] == 5

    def test_unstable_cluster(self, classifier):
        """Cluster with many accommodations is unstable."""
        events = [
            ("mem_1", "accommodation"),
            ("mem_2", "accommodation"),
            ("mem_3", "assimilation"),
            ("mem_4", "accommodation"),
        ]
        for mid, etype in events:
            dist_val = 0.8 if etype == "accommodation" else 0.1
            classifier.record_event(SchemaEvent(
                memory_id=mid,
                event_type=etype,
                cluster_id="unstable_cluster",
                distance_from_centroid=dist_val,
                timestamp="2026-02-19T10:00:00",
            ))
        stability = classifier.get_cluster_stability("unstable_cluster")
        assert stability["accommodation_rate"] == 0.75
        assert stability["last_accommodation"] is not None
        assert stability["event_count"] == 4

    def test_nonexistent_cluster_stability(self, classifier):
        stability = classifier.get_cluster_stability("no_such_cluster")
        assert stability["accommodation_rate"] == 0.0
        assert stability["event_count"] == 0


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_neighbor(self, classifier):
        """Classification works with just one neighbor."""
        neighbors = [[1.0, 0.0, 0.0]]
        new_vec = [0.95, 0.1, 0.0]
        event = classifier.classify(new_vec, neighbors)
        assert event.event_type == "assimilation"

    def test_high_dimensional_vectors(self, classifier):
        """Works with 768-dimensional vectors (typical embedding size)."""
        import random
        random.seed(42)
        base = [random.gauss(0, 1) for _ in range(768)]
        # Create neighbors close to base
        neighbors = []
        for _ in range(5):
            neighbor = [b + random.gauss(0, 0.01) for b in base]
            neighbors.append(neighbor)
        # New vector very close to base should assimilate
        new_vec = [b + random.gauss(0, 0.01) for b in base]
        event = classifier.classify(new_vec, neighbors)
        assert event.event_type == "assimilation"

    def test_empty_neighbors_raises(self, classifier):
        with pytest.raises(ValueError):
            classifier.classify([1.0, 0.0], [])

    def test_classify_records_event_automatically(self, classifier):
        """classify() should record the event to the database."""
        neighbors = [[1.0, 0.0]]
        new_vec = [1.0, 0.01]
        event = classifier.classify(new_vec, neighbors, cluster_id="auto_c")
        # Verify it was stored
        dist = classifier.get_event_distribution()
        assert dist["assimilation_count"] >= 1
