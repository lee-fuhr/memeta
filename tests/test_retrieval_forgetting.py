"""
Tests for retrieval-induced forgetting detector.

Cognitive psychology feature based on Anderson, Bjork & Bjork (1994).
Tracks retrieval imbalance within clusters using Gini coefficient.
"""

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

try:
    from memory_system.retrieval_forgetting import RetrievalForgettingDetector
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from retrieval_forgetting import RetrievalForgettingDetector


@pytest.fixture
def detector(tmp_path):
    """Provide a fresh RetrievalForgettingDetector backed by a temp database."""
    db = tmp_path / "test_retrieval.db"
    d = RetrievalForgettingDetector(db_path=str(db))
    yield d
    d.close()


@pytest.fixture
def populated_detector(tmp_path):
    """Detector pre-loaded with imbalanced retrieval data for a cluster."""
    db = tmp_path / "test_populated.db"
    d = RetrievalForgettingDetector(db_path=str(db), gini_threshold=0.5)
    # Cluster "webflow" has 5 memories. mem-1 and mem-2 dominate.
    for _ in range(50):
        d.log_retrieval("mem-1", cluster_id="webflow", query="deploy")
    for _ in range(40):
        d.log_retrieval("mem-2", cluster_id="webflow", query="layout")
    for _ in range(3):
        d.log_retrieval("mem-3", cluster_id="webflow", query="misc")
    # mem-4 and mem-5 never retrieved
    yield d
    d.close()


# ── Schema / init ──────────────────────────────────────────────────────────


class TestInit:
    def test_creates_retrieval_log_table(self, detector):
        """Table retrieval_log exists after init."""
        cur = detector.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='retrieval_log'"
        )
        assert cur.fetchone() is not None

    def test_creates_blind_spots_table(self, detector):
        """Table retrieval_blind_spots exists after init."""
        cur = detector.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='retrieval_blind_spots'"
        )
        assert cur.fetchone() is not None

    def test_creates_indexes(self, detector):
        """Both indexes on retrieval_log are created."""
        cur = detector.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        names = {r[0] for r in cur.fetchall()}
        assert "idx_retrieval_memory" in names
        assert "idx_retrieval_cluster" in names

    def test_idempotent_init(self, tmp_path):
        """Creating two detectors on the same DB does not raise."""
        db = tmp_path / "idempotent.db"
        d1 = RetrievalForgettingDetector(db_path=str(db))
        d2 = RetrievalForgettingDetector(db_path=str(db))
        d1.close()
        d2.close()

    def test_default_thresholds(self, detector):
        """Default gini_threshold is 0.7."""
        assert detector.gini_threshold == 0.7

    def test_custom_thresholds(self, tmp_path):
        """Custom thresholds are stored correctly."""
        db = tmp_path / "custom.db"
        d = RetrievalForgettingDetector(
            db_path=str(db), gini_threshold=0.5
        )
        assert d.gini_threshold == 0.5
        d.close()


# ── Gini coefficient ──────────────────────────────────────────────────────


class TestGiniCoefficient:
    def test_perfect_equality(self, detector):
        """All equal values should yield Gini = 0."""
        gini = detector.compute_gini([10, 10, 10, 10])
        assert gini == pytest.approx(0.0, abs=0.01)

    def test_perfect_inequality(self, detector):
        """One item gets everything, rest get zero. Gini should approach 1."""
        gini = detector.compute_gini([0, 0, 0, 0, 100])
        assert gini >= 0.75  # With 5 items, theoretical max is (n-1)/n = 0.8

    def test_moderate_imbalance(self, detector):
        """Skewed but not extreme distribution."""
        gini = detector.compute_gini([1, 1, 1, 1, 50])
        assert 0.4 < gini < 0.9

    def test_two_items_equal(self, detector):
        """Two equal items: Gini = 0."""
        gini = detector.compute_gini([5, 5])
        assert gini == pytest.approx(0.0, abs=0.01)

    def test_two_items_unequal(self, detector):
        """Two items, one zero: Gini = 0.5 (theoretical max for n=2)."""
        gini = detector.compute_gini([0, 10])
        assert gini == pytest.approx(0.5, abs=0.05)

    def test_single_item(self, detector):
        """Single item: Gini = 0 (no inequality possible)."""
        gini = detector.compute_gini([42])
        assert gini == pytest.approx(0.0, abs=0.01)

    def test_empty_list(self, detector):
        """Empty input returns 0."""
        gini = detector.compute_gini([])
        assert gini == 0.0

    def test_all_zeros(self, detector):
        """All zeros returns 0 (no retrievals yet)."""
        gini = detector.compute_gini([0, 0, 0])
        assert gini == 0.0

    def test_gini_range(self, detector):
        """Gini coefficient is always in [0, 1]."""
        import random

        random.seed(42)
        for _ in range(20):
            values = [random.randint(0, 100) for _ in range(random.randint(1, 20))]
            gini = detector.compute_gini(values)
            assert 0.0 <= gini <= 1.0, f"Gini {gini} out of range for {values}"


# ── log_retrieval ─────────────────────────────────────────────────────────


class TestLogRetrieval:
    def test_basic_log(self, detector):
        """Logging a retrieval writes a row to retrieval_log."""
        detector.log_retrieval("mem-1", cluster_id="c1", query="test")
        cur = detector.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM retrieval_log")
        assert cur.fetchone()[0] == 1

    def test_log_without_cluster(self, detector):
        """Logging without cluster_id stores NULL."""
        detector.log_retrieval("mem-1", query="test")
        cur = detector.conn.cursor()
        cur.execute("SELECT cluster_id FROM retrieval_log WHERE memory_id='mem-1'")
        row = cur.fetchone()
        assert row[0] is None

    def test_log_without_query(self, detector):
        """Logging without query stores empty string."""
        detector.log_retrieval("mem-1", cluster_id="c1")
        cur = detector.conn.cursor()
        cur.execute("SELECT query FROM retrieval_log WHERE memory_id='mem-1'")
        row = cur.fetchone()
        assert row[0] == ""

    def test_multiple_logs(self, detector):
        """Multiple logs accumulate correctly."""
        for i in range(10):
            detector.log_retrieval(f"mem-{i}", cluster_id="c1")
        cur = detector.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM retrieval_log")
        assert cur.fetchone()[0] == 10

    def test_timestamp_stored(self, detector):
        """Each log has a non-empty retrieved_at timestamp."""
        detector.log_retrieval("mem-1", cluster_id="c1")
        cur = detector.conn.cursor()
        cur.execute("SELECT retrieved_at FROM retrieval_log")
        ts = cur.fetchone()[0]
        assert ts is not None
        # Should parse as ISO format
        datetime.fromisoformat(ts)


# ── analyze_cluster ───────────────────────────────────────────────────────


class TestAnalyzeCluster:
    def test_empty_cluster(self, detector):
        """Empty cluster returns Gini 0, no dominant/neglected."""
        result = detector.analyze_cluster("empty-cluster", [])
        assert result["gini"] == 0.0
        assert result["dominant_ids"] == []
        assert result["neglected_ids"] == []
        assert result["is_imbalanced"] is False

    def test_single_memory_cluster(self, detector):
        """Single-memory cluster returns Gini 0."""
        detector.log_retrieval("mem-1", cluster_id="solo")
        result = detector.analyze_cluster("solo", ["mem-1"])
        assert result["gini"] == pytest.approx(0.0, abs=0.01)
        assert result["is_imbalanced"] is False

    def test_balanced_cluster(self, detector):
        """Evenly retrieved cluster has low Gini."""
        for mem_id in ["m1", "m2", "m3", "m4"]:
            for _ in range(10):
                detector.log_retrieval(mem_id, cluster_id="balanced")
        result = detector.analyze_cluster("balanced", ["m1", "m2", "m3", "m4"])
        assert result["gini"] < 0.3
        assert result["is_imbalanced"] is False

    def test_imbalanced_cluster(self, populated_detector):
        """Heavily skewed cluster is flagged as imbalanced."""
        all_ids = ["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]
        result = populated_detector.analyze_cluster("webflow", all_ids)
        assert result["gini"] > 0.5
        assert result["is_imbalanced"] is True
        # mem-1 and mem-2 dominate
        assert "mem-1" in result["dominant_ids"]
        assert "mem-2" in result["dominant_ids"]
        # mem-4 and mem-5 (never retrieved) should be neglected
        assert "mem-4" in result["neglected_ids"]
        assert "mem-5" in result["neglected_ids"]

    def test_result_keys(self, detector):
        """Result dict has expected keys."""
        result = detector.analyze_cluster("c1", ["m1"])
        expected_keys = {"gini", "dominant_ids", "neglected_ids", "is_imbalanced"}
        assert set(result.keys()) == expected_keys


# ── get_neglected_memories ────────────────────────────────────────────────


class TestGetNeglectedMemories:
    def test_no_retrievals_all_neglected(self, detector):
        """Memories with zero retrievals are all neglected."""
        neglected = detector.get_neglected_memories("c1", ["m1", "m2", "m3"])
        assert set(neglected) == {"m1", "m2", "m3"}

    def test_evenly_retrieved_none_neglected(self, detector):
        """When all memories have equal retrievals, bottom 50% by count is empty or minimal."""
        for mem_id in ["m1", "m2", "m3", "m4"]:
            for _ in range(10):
                detector.log_retrieval(mem_id, cluster_id="c1")
        neglected = detector.get_neglected_memories("c1", ["m1", "m2", "m3", "m4"])
        # All equal, so none should be flagged as truly neglected
        # (depends on implementation - bottom 50% of equal means none are significantly behind)
        assert len(neglected) == 0

    def test_skewed_retrievals(self, populated_detector):
        """Heavily skewed: bottom-50% memories are flagged."""
        all_ids = ["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]
        neglected = populated_detector.get_neglected_memories("webflow", all_ids)
        assert "mem-4" in neglected
        assert "mem-5" in neglected
        assert "mem-1" not in neglected  # dominant


# ── find_blind_spots ──────────────────────────────────────────────────────


class TestFindBlindSpots:
    def test_no_data_no_blind_spots(self, detector):
        """No retrieval data yields no blind spots."""
        spots = detector.find_blind_spots()
        assert spots == []

    def test_detects_imbalanced_clusters(self, populated_detector):
        """Finds clusters with high Gini above threshold."""
        # We need to tell the detector what clusters/memories exist.
        # find_blind_spots uses retrieval_log to discover clusters.
        all_ids = ["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]
        spots = populated_detector.find_blind_spots(
            cluster_memories={"webflow": all_ids}
        )
        assert len(spots) >= 1
        webflow_spot = [s for s in spots if s["cluster_id"] == "webflow"]
        assert len(webflow_spot) == 1
        assert webflow_spot[0]["gini"] > 0.5

    def test_stores_blind_spots_in_db(self, populated_detector):
        """Found blind spots are persisted in retrieval_blind_spots table."""
        all_ids = ["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]
        populated_detector.find_blind_spots(
            cluster_memories={"webflow": all_ids}
        )
        cur = populated_detector.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM retrieval_blind_spots")
        assert cur.fetchone()[0] >= 1

    def test_blind_spot_has_dominant_and_neglected(self, populated_detector):
        """Blind spot records include dominant and neglected memory IDs."""
        all_ids = ["mem-1", "mem-2", "mem-3", "mem-4", "mem-5"]
        spots = populated_detector.find_blind_spots(
            cluster_memories={"webflow": all_ids}
        )
        spot = spots[0]
        assert len(spot["dominant"]) > 0
        assert len(spot["neglected"]) > 0


# ── get_retrieval_stats ───────────────────────────────────────────────────


class TestGetRetrievalStats:
    def test_empty_stats(self, detector):
        """Empty DB returns zero stats."""
        stats = detector.get_retrieval_stats()
        assert stats["total_retrievals"] == 0
        assert stats["unique_memories_retrieved"] == 0

    def test_populated_stats(self, populated_detector):
        """Stats reflect actual retrieval counts."""
        stats = populated_detector.get_retrieval_stats()
        assert stats["total_retrievals"] == 93  # 50 + 40 + 3
        assert stats["unique_memories_retrieved"] == 3  # mem-1, mem-2, mem-3


# ── close ─────────────────────────────────────────────────────────────────


class TestClose:
    def test_close_method_exists(self, tmp_path):
        """Detector has a close method that doesn't raise."""
        db = tmp_path / "close_test.db"
        d = RetrievalForgettingDetector(db_path=str(db))
        d.close()
        # Second close should not raise
        d.close()
