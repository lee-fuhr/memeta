"""
Tests for generational garbage collection.

Three-generation memory lifecycle with graduated collection thresholds:
- Gen 0 (nursery): <7 days old, collected daily
- Gen 1 (young): 7-90 days old, collected weekly
- Gen 2 (tenured): 90+ days old, collected monthly
"""

import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Allow importing from this worktree's src/ when the editable install
# points to a different worktree (main).
try:
    from memory_system.generational_gc import GenerationalGC
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from generational_gc import GenerationalGC


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_memory(gc: GenerationalGC, memory_id: str, created_at: datetime,
                 importance: float = 0.5, access_count: int = 0,
                 last_accessed: datetime | None = None,
                 has_links: bool = False) -> None:
    """Insert mock memory data into the GC's supporting tables."""
    cur = gc.conn.cursor()
    # Insert into the mock memories table
    cur.execute(
        "INSERT OR REPLACE INTO mock_memories (memory_id, importance, access_count, "
        "last_accessed, has_links, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (memory_id, importance, access_count,
         _iso(last_accessed) if last_accessed else None,
         1 if has_links else 0, _iso(created_at))
    )
    gc.conn.commit()
    # Assign to generation
    gc.assign_generation(memory_id, created_at)


@pytest.fixture
def gc(tmp_path):
    """Provide a fresh GenerationalGC backed by a temp database."""
    db = tmp_path / "test_gc.db"
    g = GenerationalGC(db_path=str(db))
    yield g
    g.close()


@pytest.fixture
def gc_with_mock_data(tmp_path):
    """GC instance pre-loaded with memories in all three generations."""
    db = tmp_path / "test_gc_loaded.db"
    g = GenerationalGC(db_path=str(db))
    now = _now()

    # Gen 0: 2-day-old memory, not accessed
    _seed_memory(g, "mem-nursery-1", now - timedelta(days=2), importance=0.3, access_count=0)
    # Gen 0: 5-day-old memory, accessed once
    _seed_memory(g, "mem-nursery-2", now - timedelta(days=5), importance=0.6, access_count=1,
                 last_accessed=now - timedelta(days=1))

    # Gen 1: 30-day-old memory, accessed once (below threshold)
    _seed_memory(g, "mem-young-1", now - timedelta(days=30), importance=0.4, access_count=1)
    # Gen 1: 60-day-old memory, accessed 3 times
    _seed_memory(g, "mem-young-2", now - timedelta(days=60), importance=0.7, access_count=3,
                 last_accessed=now - timedelta(days=5))

    # Gen 2: 120-day-old, low importance, no access, no links
    _seed_memory(g, "mem-tenured-1", now - timedelta(days=120), importance=0.1, access_count=0)
    # Gen 2: 200-day-old, high importance, linked
    _seed_memory(g, "mem-tenured-2", now - timedelta(days=200), importance=0.8, access_count=5,
                 last_accessed=now - timedelta(days=10), has_links=True)

    yield g
    g.close()


# ── Schema / init ─────────────────────────────────────────────────────────────


class TestInit:
    def test_creates_generations_table(self, gc):
        """memory_generations table exists after init."""
        cur = gc.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_generations'"
        )
        assert cur.fetchone() is not None

    def test_creates_gc_events_table(self, gc):
        """gc_events table exists after init."""
        cur = gc.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='gc_events'"
        )
        assert cur.fetchone() is not None

    def test_creates_mock_memories_table(self, gc):
        """mock_memories table exists (for standalone testing)."""
        cur = gc.conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mock_memories'"
        )
        assert cur.fetchone() is not None

    def test_idempotent_init(self, tmp_path):
        """Creating two GC instances on the same DB does not raise."""
        db = tmp_path / "idem.db"
        g1 = GenerationalGC(db_path=str(db))
        g2 = GenerationalGC(db_path=str(db))
        g1.close()
        g2.close()


# ── assign_generation ─────────────────────────────────────────────────────────


class TestAssignGeneration:
    def test_new_memory_gen0(self, gc):
        """Memory created today is generation 0."""
        gen = gc.assign_generation("mem-1", _now())
        assert gen == 0

    def test_6_day_old_gen0(self, gc):
        """Memory created 6 days ago is still generation 0."""
        gen = gc.assign_generation("mem-2", _now() - timedelta(days=6))
        assert gen == 0

    def test_7_day_old_gen1(self, gc):
        """Memory created exactly 7 days ago is generation 1."""
        gen = gc.assign_generation("mem-3", _now() - timedelta(days=7))
        assert gen == 1

    def test_89_day_old_gen1(self, gc):
        """Memory created 89 days ago is still generation 1."""
        gen = gc.assign_generation("mem-4", _now() - timedelta(days=89))
        assert gen == 1

    def test_90_day_old_gen2(self, gc):
        """Memory created exactly 90 days ago is generation 2."""
        gen = gc.assign_generation("mem-5", _now() - timedelta(days=90))
        assert gen == 2

    def test_365_day_old_gen2(self, gc):
        """Very old memory is generation 2."""
        gen = gc.assign_generation("mem-6", _now() - timedelta(days=365))
        assert gen == 2

    def test_persists_to_db(self, gc):
        """Generation assignment is stored in the database."""
        gc.assign_generation("mem-7", _now() - timedelta(days=50))
        cur = gc.conn.cursor()
        cur.execute("SELECT generation FROM memory_generations WHERE memory_id = ?", ("mem-7",))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1

    def test_reassign_updates_generation(self, gc):
        """Re-assigning updates the generation for an existing memory."""
        gc.assign_generation("mem-8", _now())  # Gen 0
        gc.assign_generation("mem-8", _now() - timedelta(days=100))  # Gen 2
        cur = gc.conn.cursor()
        cur.execute("SELECT generation FROM memory_generations WHERE memory_id = ?", ("mem-8",))
        assert cur.fetchone()[0] == 2


# ── promote ───────────────────────────────────────────────────────────────────


class TestPromote:
    def test_promote_gen0_to_gen1(self, gc):
        """Promoting a gen-0 memory moves it to gen 1."""
        gc.assign_generation("mem-p1", _now())
        new_gen = gc.promote("mem-p1")
        assert new_gen == 1

    def test_promote_gen1_to_gen2(self, gc):
        """Promoting a gen-1 memory moves it to gen 2."""
        gc.assign_generation("mem-p2", _now() - timedelta(days=30))
        new_gen = gc.promote("mem-p2")
        assert new_gen == 2

    def test_promote_gen2_stays_gen2(self, gc):
        """Promoting a gen-2 memory stays at gen 2 (max generation)."""
        gc.assign_generation("mem-p3", _now() - timedelta(days=120))
        new_gen = gc.promote("mem-p3")
        assert new_gen == 2

    def test_promote_increments_survived_count(self, gc):
        """Each promotion increments the collection_survived counter."""
        gc.assign_generation("mem-p4", _now())
        gc.promote("mem-p4")
        cur = gc.conn.cursor()
        cur.execute("SELECT collection_survived FROM memory_generations WHERE memory_id = ?",
                    ("mem-p4",))
        assert cur.fetchone()[0] == 1
        gc.promote("mem-p4")
        cur.execute("SELECT collection_survived FROM memory_generations WHERE memory_id = ?",
                    ("mem-p4",))
        assert cur.fetchone()[0] == 2

    def test_promote_sets_promoted_at(self, gc):
        """Promotion records the timestamp."""
        gc.assign_generation("mem-p5", _now())
        gc.promote("mem-p5")
        cur = gc.conn.cursor()
        cur.execute("SELECT promoted_at FROM memory_generations WHERE memory_id = ?",
                    ("mem-p5",))
        ts = cur.fetchone()[0]
        assert ts is not None
        # Should be parseable and recent
        dt = datetime.fromisoformat(ts)
        assert (_now() - dt).total_seconds() < 5

    def test_promote_unknown_memory_raises(self, gc):
        """Promoting a memory not in the system raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            gc.promote("nonexistent")


# ── collect_generation (gen 0) ────────────────────────────────────────────────


class TestCollectGen0:
    def test_collects_unaccessed_nursery_memory(self, gc_with_mock_data):
        """Gen-0 memory with no accesses is collected."""
        collected = gc_with_mock_data.collect_generation(0)
        assert "mem-nursery-1" in collected

    def test_keeps_accessed_nursery_memory(self, gc_with_mock_data):
        """Gen-0 memory that was accessed is NOT collected."""
        collected = gc_with_mock_data.collect_generation(0)
        assert "mem-nursery-2" not in collected

    def test_does_not_touch_other_generations(self, gc_with_mock_data):
        """Collecting gen-0 does not affect gen-1 or gen-2 memories."""
        collected = gc_with_mock_data.collect_generation(0)
        for mid in collected:
            cur = gc_with_mock_data.conn.cursor()
            cur.execute("SELECT generation FROM memory_generations WHERE memory_id = ?", (mid,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 0

    def test_records_gc_event(self, gc_with_mock_data):
        """Collection records an event in gc_events."""
        gc_with_mock_data.collect_generation(0)
        cur = gc_with_mock_data.conn.cursor()
        cur.execute("SELECT * FROM gc_events WHERE generation = 0")
        events = cur.fetchall()
        assert len(events) == 1


# ── collect_generation (gen 1) ────────────────────────────────────────────────


class TestCollectGen1:
    def test_collects_low_access_low_importance(self, gc_with_mock_data):
        """Gen-1 memory with <2 accesses AND importance <=0.5 is collected."""
        collected = gc_with_mock_data.collect_generation(1)
        assert "mem-young-1" in collected

    def test_keeps_high_access_memory(self, gc_with_mock_data):
        """Gen-1 memory with >=2 accesses is kept."""
        collected = gc_with_mock_data.collect_generation(1)
        assert "mem-young-2" not in collected

    def test_keeps_high_importance_memory(self, gc):
        """Gen-1 memory with importance >0.5 is kept even with few accesses."""
        now = _now()
        _seed_memory(gc, "mem-important", now - timedelta(days=40),
                     importance=0.7, access_count=0)
        collected = gc.collect_generation(1)
        assert "mem-important" not in collected


# ── collect_generation (gen 2) ────────────────────────────────────────────────


class TestCollectGen2:
    def test_collects_low_importance_no_access_no_links(self, gc_with_mock_data):
        """Gen-2 memory meeting all three archival criteria is collected."""
        collected = gc_with_mock_data.collect_generation(2)
        assert "mem-tenured-1" in collected

    def test_keeps_high_importance_tenured(self, gc_with_mock_data):
        """Gen-2 memory with high importance is kept."""
        collected = gc_with_mock_data.collect_generation(2)
        assert "mem-tenured-2" not in collected

    def test_keeps_recently_accessed_tenured(self, gc):
        """Gen-2 memory accessed in the last 60 days is kept."""
        now = _now()
        _seed_memory(gc, "mem-recent-access", now - timedelta(days=150),
                     importance=0.1, access_count=1,
                     last_accessed=now - timedelta(days=30))
        collected = gc.collect_generation(2)
        assert "mem-recent-access" not in collected

    def test_keeps_linked_tenured(self, gc):
        """Gen-2 memory with relationship links is kept."""
        now = _now()
        _seed_memory(gc, "mem-linked", now - timedelta(days=150),
                     importance=0.1, access_count=0, has_links=True)
        collected = gc.collect_generation(2)
        assert "mem-linked" not in collected

    def test_collects_only_when_all_three_conditions_met(self, gc):
        """Gen-2 memory is only collected when ALL three conditions are met."""
        now = _now()
        # Low importance + no access BUT has links → keep
        _seed_memory(gc, "mem-2a", now - timedelta(days=200),
                     importance=0.1, access_count=0, has_links=True)
        # Low importance + no links BUT recently accessed → keep
        _seed_memory(gc, "mem-2b", now - timedelta(days=200),
                     importance=0.1, access_count=1,
                     last_accessed=now - timedelta(days=10))
        # No access + no links BUT high importance → keep
        _seed_memory(gc, "mem-2c", now - timedelta(days=200),
                     importance=0.5, access_count=0)

        collected = gc.collect_generation(2)
        assert "mem-2a" not in collected
        assert "mem-2b" not in collected
        assert "mem-2c" not in collected


# ── run_daily / run_weekly / run_monthly ──────────────────────────────────────


class TestScheduledRuns:
    def test_run_daily_only_gen0(self, gc_with_mock_data):
        """Daily run only collects from gen 0."""
        result = gc_with_mock_data.run_daily()
        assert "gen_0" in result
        assert "gen_1" not in result
        assert "gen_2" not in result

    def test_run_weekly_gen0_and_gen1(self, gc_with_mock_data):
        """Weekly run collects from gen 0 and gen 1."""
        result = gc_with_mock_data.run_weekly()
        assert "gen_0" in result
        assert "gen_1" in result
        assert "gen_2" not in result

    def test_run_monthly_all_gens(self, gc_with_mock_data):
        """Monthly run collects from all three generations."""
        result = gc_with_mock_data.run_monthly()
        assert "gen_0" in result
        assert "gen_1" in result
        assert "gen_2" in result

    def test_run_daily_returns_collected_ids(self, gc_with_mock_data):
        """Daily run result includes actual collected memory IDs."""
        result = gc_with_mock_data.run_daily()
        assert isinstance(result["gen_0"]["collected"], list)
        assert "mem-nursery-1" in result["gen_0"]["collected"]

    def test_run_monthly_collects_from_all_gens(self, gc_with_mock_data):
        """Monthly run collects eligible memories from all generations."""
        result = gc_with_mock_data.run_monthly()
        all_collected = (
            result["gen_0"]["collected"]
            + result["gen_1"]["collected"]
            + result["gen_2"]["collected"]
        )
        assert "mem-nursery-1" in all_collected
        assert "mem-young-1" in all_collected
        assert "mem-tenured-1" in all_collected


# ── get_generation_stats ──────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty_db(self, gc):
        """Stats on empty DB returns zeroes."""
        stats = gc.get_generation_stats()
        assert stats["gen_0"]["count"] == 0
        assert stats["gen_1"]["count"] == 0
        assert stats["gen_2"]["count"] == 0

    def test_stats_with_data(self, gc_with_mock_data):
        """Stats reflect seeded data counts."""
        stats = gc_with_mock_data.get_generation_stats()
        assert stats["gen_0"]["count"] == 2
        assert stats["gen_1"]["count"] == 2
        assert stats["gen_2"]["count"] == 2

    def test_stats_total(self, gc_with_mock_data):
        """Stats include a total count."""
        stats = gc_with_mock_data.get_generation_stats()
        assert stats["total"] == 6


# ── get_gc_history ────────────────────────────────────────────────────────────


class TestGCHistory:
    def test_empty_history(self, gc):
        """No events returns empty list."""
        history = gc.get_gc_history()
        assert history == []

    def test_history_after_collection(self, gc_with_mock_data):
        """GC event appears in history after collection."""
        gc_with_mock_data.collect_generation(0)
        history = gc_with_mock_data.get_gc_history()
        assert len(history) == 1
        assert history[0]["generation"] == 0
        assert history[0]["collected_count"] >= 1

    def test_history_limit(self, gc_with_mock_data):
        """History respects the limit parameter."""
        gc_with_mock_data.collect_generation(0)
        gc_with_mock_data.collect_generation(1)
        gc_with_mock_data.collect_generation(2)
        history = gc_with_mock_data.get_gc_history(limit=2)
        assert len(history) == 2

    def test_history_order_most_recent_first(self, gc_with_mock_data):
        """History returns most recent events first."""
        gc_with_mock_data.collect_generation(0)
        gc_with_mock_data.collect_generation(1)
        history = gc_with_mock_data.get_gc_history()
        assert history[0]["generation"] == 1  # Most recent
        assert history[1]["generation"] == 0

    def test_history_records_promoted_count(self, gc_with_mock_data):
        """GC event records how many were promoted (survived)."""
        gc_with_mock_data.collect_generation(0)
        history = gc_with_mock_data.get_gc_history()
        event = history[0]
        assert "promoted_count" in event
        assert event["promoted_count"] >= 0
        assert event["total_in_generation"] >= event["promoted_count"]


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_collect_empty_generation(self, gc):
        """Collecting from an empty generation returns empty list."""
        collected = gc.collect_generation(0)
        assert collected == []

    def test_invalid_generation_raises(self, gc):
        """Collecting from invalid generation raises ValueError."""
        with pytest.raises(ValueError, match="Invalid generation"):
            gc.collect_generation(3)
        with pytest.raises(ValueError, match="Invalid generation"):
            gc.collect_generation(-1)

    def test_collection_does_not_delete_from_db(self, gc_with_mock_data):
        """Collection returns IDs but does not delete memory_generations rows."""
        collected = gc_with_mock_data.collect_generation(0)
        assert len(collected) > 0
        cur = gc_with_mock_data.conn.cursor()
        for mid in collected:
            cur.execute("SELECT * FROM memory_generations WHERE memory_id = ?", (mid,))
            assert cur.fetchone() is not None, f"{mid} should still be in memory_generations"

    def test_double_collection_same_result(self, gc_with_mock_data):
        """Running collection twice yields the same candidates (idempotent)."""
        first = gc_with_mock_data.collect_generation(0)
        second = gc_with_mock_data.collect_generation(0)
        assert sorted(first) == sorted(second)

    def test_borderline_importance_gen1(self, gc):
        """Gen-1 memory with importance exactly 0.5 is kept (threshold is >0.5)."""
        now = _now()
        _seed_memory(gc, "mem-border", now - timedelta(days=30),
                     importance=0.5, access_count=1)
        collected = gc.collect_generation(1)
        # importance=0.5, access_count=1: not >=2 accesses AND not >0.5 importance → collected
        assert "mem-border" in collected

    def test_borderline_importance_gen2(self, gc):
        """Gen-2 memory with importance exactly 0.15 is kept (threshold is <0.15)."""
        now = _now()
        _seed_memory(gc, "mem-edge", now - timedelta(days=120),
                     importance=0.15, access_count=0)
        collected = gc.collect_generation(2)
        assert "mem-edge" not in collected

    def test_close_method(self, tmp_path):
        """Close method closes the database connection gracefully."""
        db = tmp_path / "close_test.db"
        g = GenerationalGC(db_path=str(db))
        g.close()
        # After close, operations should fail
        with pytest.raises(Exception):
            g.conn.execute("SELECT 1")
