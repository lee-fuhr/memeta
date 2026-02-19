"""
Tests for the memory health score module.

Covers:
- Component weight validation (sum to 1.0)
- Grade boundaries (A/B/C/D/F)
- Baseline score when no data provided
- Compute from raw memories
- Compute from pre-aggregated stats
- Record and retrieve (get_latest)
- Trend query (get_trend)
- Alert checking (check_alert)
- Weakest component identification
- Empty memories edge case
- Mixed quality memories
- Compression / redundancy detection
- DB persistence across instances
- Context manager support
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure this worktree's src/ is first on sys.path so the import resolves
# to the local memory_health.py rather than the editable install from another
# worktree.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from memory_health import COMPONENT_WEIGHTS, MemoryHealthScore


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_health.db")


@pytest.fixture
def health(tmp_db):
    h = MemoryHealthScore(db_path=tmp_db)
    yield h
    h.close()


# ---------------------------------------------------------------------------
# 1. Component weights sum to 1.0
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(COMPONENT_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_all_six_components_present(self):
        expected = {
            "pct_high_confidence",
            "pct_recently_confirmed",
            "pct_with_provenance",
            "avg_freshness",
            "low_contradiction_rate",
            "compression_potential",
        }
        assert set(COMPONENT_WEIGHTS.keys()) == expected

    def test_all_weights_positive(self):
        for k, v in COMPONENT_WEIGHTS.items():
            assert v > 0, f"Weight for {k} must be positive, got {v}"


# ---------------------------------------------------------------------------
# 2. Grade boundaries
# ---------------------------------------------------------------------------

class TestGrading:
    @pytest.mark.parametrize(
        "score, expected_grade",
        [
            (100, "A"),
            (95, "A"),
            (90, "A"),
            (89, "B"),
            (80, "B"),
            (79, "C"),
            (70, "C"),
            (69, "D"),
            (60, "D"),
            (59, "F"),
            (0, "F"),
        ],
    )
    def test_grade_boundaries(self, score, expected_grade):
        assert MemoryHealthScore._score_to_grade(score) == expected_grade


# ---------------------------------------------------------------------------
# 3. Baseline score
# ---------------------------------------------------------------------------

class TestBaseline:
    def test_baseline_returns_50(self, health):
        result = health.compute()
        assert result["score"] == 50
        assert result["grade"] == "F"

    def test_baseline_all_components_50(self, health):
        result = health.compute()
        for k in COMPONENT_WEIGHTS:
            assert result["components"][k] == 50.0

    def test_baseline_has_timestamp(self, health):
        result = health.compute()
        assert "computed_at" in result
        # Should be a parseable ISO timestamp
        datetime.fromisoformat(result["computed_at"])


# ---------------------------------------------------------------------------
# 4. Compute from stats
# ---------------------------------------------------------------------------

class TestComputeFromStats:
    def test_perfect_stats(self, health):
        stats = {k: 100.0 for k in COMPONENT_WEIGHTS}
        result = health.compute(stats=stats)
        assert result["score"] == 100
        assert result["grade"] == "A"

    def test_zero_stats(self, health):
        stats = {k: 0.0 for k in COMPONENT_WEIGHTS}
        result = health.compute(stats=stats)
        assert result["score"] == 0
        assert result["grade"] == "F"

    def test_partial_stats_defaults_to_50(self, health):
        stats = {"pct_high_confidence": 100.0}
        result = health.compute(stats=stats)
        # Only one component is 100, rest default to 50
        assert result["components"]["pct_high_confidence"] == 100.0
        assert result["components"]["avg_freshness"] == 50.0

    def test_mixed_stats(self, health):
        stats = {
            "pct_high_confidence": 90.0,
            "pct_recently_confirmed": 80.0,
            "pct_with_provenance": 70.0,
            "avg_freshness": 60.0,
            "low_contradiction_rate": 50.0,
            "compression_potential": 40.0,
        }
        result = health.compute(stats=stats)
        # Weighted: 90*.20 + 80*.20 + 70*.15 + 60*.20 + 50*.15 + 40*.10
        #         = 18 + 16 + 10.5 + 12 + 7.5 + 4 = 68
        assert result["score"] == 68
        assert result["grade"] == "D"


# ---------------------------------------------------------------------------
# 5. Compute from memories
# ---------------------------------------------------------------------------

class TestComputeFromMemories:
    def _make_memory(
        self,
        confidence=0.5,
        confirmed_at=None,
        source=None,
        session_id=None,
        created_at=None,
        contradictions=0,
        title=None,
    ):
        m = {
            "confidence_score": confidence,
            "contradictions": contradictions,
        }
        if confirmed_at:
            m["last_confirmed"] = confirmed_at
        if source:
            m["source"] = source
        if session_id:
            m["session_id"] = session_id
        if created_at:
            m["created_at"] = created_at
        if title:
            m["title"] = title
        return m

    def test_high_quality_memories(self, health):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        memories = [
            self._make_memory(
                confidence=0.9,
                confirmed_at=(now - timedelta(days=5)).isoformat(),
                source="session-abc",
                created_at=(now - timedelta(days=10)).isoformat(),
                title=f"unique-{i}",
            )
            for i in range(10)
        ]
        result = health.compute(memories=memories)
        assert result["score"] >= 80
        assert result["grade"] in ("A", "B")

    def test_empty_memories(self, health):
        result = health.compute(memories=[])
        assert result["score"] == 0
        assert result["grade"] == "F"

    def test_contradicted_memories(self, health):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        memories = [
            self._make_memory(
                confidence=0.3,
                contradictions=2,
                created_at=(now - timedelta(days=5)).isoformat(),
                title=f"m-{i}",
            )
            for i in range(10)
        ]
        result = health.compute(memories=memories)
        # Low confidence + high contradiction -> low scores
        assert result["components"]["pct_high_confidence"] == 0.0
        assert result["components"]["low_contradiction_rate"] == 0.0

    def test_duplicate_titles_reduce_compression(self, health):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        memories = [
            self._make_memory(
                confidence=0.8,
                created_at=(now - timedelta(days=1)).isoformat(),
                title="same-title",
            )
            for _ in range(10)
        ]
        result = health.compute(memories=memories)
        # 10 titles, 1 unique -> 90% redundancy -> compression_potential = 10
        assert result["components"]["compression_potential"] == 10.0


# ---------------------------------------------------------------------------
# 6. Record and retrieve
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_record_and_get_latest(self, health):
        score_dict = health.compute()
        health.record(score_dict)
        latest = health.get_latest()
        assert latest is not None
        assert latest["score"] == 50
        assert latest["grade"] == "F"

    def test_get_latest_none_when_empty(self, health):
        assert health.get_latest() is None

    def test_multiple_records_returns_most_recent(self, health):
        s1 = health.compute(stats={k: 100.0 for k in COMPONENT_WEIGHTS})
        health.record(s1)
        s2 = health.compute(stats={k: 0.0 for k in COMPONENT_WEIGHTS})
        health.record(s2)
        latest = health.get_latest()
        assert latest["score"] == 0

    def test_persistence_across_instances(self, tmp_db):
        h1 = MemoryHealthScore(db_path=tmp_db)
        s = h1.compute(stats={k: 80.0 for k in COMPONENT_WEIGHTS})
        h1.record(s)
        h1.close()

        h2 = MemoryHealthScore(db_path=tmp_db)
        latest = h2.get_latest()
        h2.close()
        assert latest is not None
        assert latest["score"] == 80


# ---------------------------------------------------------------------------
# 7. Trend query
# ---------------------------------------------------------------------------

class TestTrend:
    def test_trend_empty(self, health):
        assert health.get_trend() == []

    def test_trend_returns_recent(self, health):
        s = health.compute()
        health.record(s)
        trend = health.get_trend(days=30)
        assert len(trend) == 1

    def test_trend_excludes_old(self, health):
        # Insert a score with old timestamp manually
        old_time = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)).isoformat(
            timespec="seconds"
        )
        health.conn.execute(
            "INSERT INTO health_scores (score, grade, components_json, computed_at) "
            "VALUES (?, ?, ?, ?)",
            (50, "F", json.dumps({}), old_time),
        )
        health.conn.commit()
        trend = health.get_trend(days=30)
        assert len(trend) == 0


# ---------------------------------------------------------------------------
# 8. Alerts
# ---------------------------------------------------------------------------

class TestAlerts:
    def test_no_alert_when_no_scores(self, health):
        assert health.check_alert() is None

    def test_alert_below_threshold(self, health):
        s = health.compute(stats={k: 30.0 for k in COMPONENT_WEIGHTS})
        health.record(s)
        alert = health.check_alert(threshold=50)
        assert alert is not None
        assert "below threshold" in alert

    def test_no_alert_above_threshold(self, health):
        s = health.compute(stats={k: 80.0 for k in COMPONENT_WEIGHTS})
        health.record(s)
        assert health.check_alert(threshold=50) is None

    def test_alert_identifies_weakest_component(self, health):
        stats = {k: 80.0 for k in COMPONENT_WEIGHTS}
        stats["compression_potential"] = 5.0
        s = health.compute(stats=stats)
        health.record(s)
        alert = health.check_alert(threshold=80)
        assert alert is not None
        assert "compression_potential" in alert


# ---------------------------------------------------------------------------
# 9. Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager(self, tmp_db):
        with MemoryHealthScore(db_path=tmp_db) as h:
            result = h.compute()
            h.record(result)
            assert h.get_latest() is not None
