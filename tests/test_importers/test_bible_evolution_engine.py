"""Tests for BibleEvolutionEngine — Bible change tracking + principle reinforcement."""
import pytest
from pathlib import Path

from memory_system.importers.bible_evolution_engine import (
    BibleEvolutionEngine,
    BibleSnapshot,
    BibleSectionSnapshot,
    BibleExperience,
)


# ---------------------------------------------------------------------------
# Sample content
# ---------------------------------------------------------------------------

SAMPLE_BIBLE_V1 = """\
# How we build
**Version:** 1.5.1

---

## 1. Core principles

### 1.1 Orchestrate, don't execute

The primary directive is orchestration, not solo execution.
Delegate to specialist agents. Target 80% delegation rate.

### 1.2 QA the design before writing code

Review the design before any implementation. Steelman every plan.

---

## 2. Reusable patterns

### 2.1 Hierarchical cost optimization (80/15/5)

Route work to the cheapest model that can handle it.
Haiku for routine tasks, Sonnet for synthesis, Opus for architecture.

---

## 6. Anti-patterns

### 6.1 The 49-day research agent

An automation that runs without checkpoint validation will run
indefinitely. Always set measurable checkpoints with explicit failure plans.
"""

# V2: 1.1 body changed, 1.2 body changed, 2.1 and 6.1 unchanged
SAMPLE_BIBLE_V2 = """\
# How we build
**Version:** 1.5.2

---

## 1. Core principles

### 1.1 Orchestrate, don't execute

The primary directive is orchestration, not solo execution.
Delegate to specialist agents. Target 90% delegation rate.

### 1.2 QA the design before writing code

Review the design before any implementation. Steelman every plan.
Use QA swarm for builds over 2 hours.

---

## 2. Reusable patterns

### 2.1 Hierarchical cost optimization (80/15/5)

Route work to the cheapest model that can handle it.
Haiku for routine tasks, Sonnet for synthesis, Opus for architecture.

---

## 6. Anti-patterns

### 6.1 The 49-day research agent

An automation that runs without checkpoint validation will run
indefinitely. Always set measurable checkpoints with explicit failure plans.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    return BibleEvolutionEngine(db_path=tmp_path / "bible_evo.db")


@pytest.fixture
def bible_v1(tmp_path):
    p = tmp_path / "Build Bible v1.md"
    p.write_text(SAMPLE_BIBLE_V1)
    return p


@pytest.fixture
def bible_v2(tmp_path):
    p = tmp_path / "Build Bible v2.md"
    p.write_text(SAMPLE_BIBLE_V2)
    return p


# ---------------------------------------------------------------------------
# Snapshot — first run
# ---------------------------------------------------------------------------

class TestSnapshotInitial:
    def test_returns_bible_snapshot(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        assert isinstance(snap, BibleSnapshot)

    def test_first_snapshot_marks_all_initial(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        assert all(s.change_type == "initial" for s in snap.sections)

    def test_snapshot_covers_importable_sections(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        ids = {s.section_id for s in snap.sections}
        assert {"1.1", "1.2", "2.1", "6.1"}.issubset(ids)

    def test_snapshot_skips_non_importable_sections(self, engine, tmp_path):
        bible = tmp_path / "b.md"
        bible.write_text(SAMPLE_BIBLE_V1 + "\n## 7. Operations\n### 7.1 Reference\n\nSkip me.\n")
        snap = engine.snapshot(bible)
        assert not any(s.section_id.startswith("7.") for s in snap.sections)

    def test_snapshot_section_types_correct(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        by_id = {s.section_id: s for s in snap.sections}
        assert by_id["1.1"].section_type == "principle"
        assert by_id["2.1"].section_type == "pattern"
        assert by_id["6.1"].section_type == "anti_pattern"

    def test_snapshot_records_timestamp(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        assert snap.snapshotted_at

    def test_initial_snap_changed_count_is_zero(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        assert snap.changed_count == 0

    def test_initial_snap_unchanged_count_is_zero(self, engine, bible_v1):
        snap = engine.snapshot(bible_v1)
        assert snap.unchanged_count == 0


# ---------------------------------------------------------------------------
# Snapshot — subsequent runs
# ---------------------------------------------------------------------------

class TestSnapshotSubsequent:
    def test_identical_resnapshot_marks_unchanged(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v1)
        assert all(s.change_type == "unchanged" for s in snap2.sections)

    def test_changed_sections_detected(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        changed = {s.section_id: s.change_type for s in snap2.sections}
        assert changed["1.1"] == "changed"
        assert changed["1.2"] == "changed"

    def test_unchanged_sections_correct(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        changed = {s.section_id: s.change_type for s in snap2.sections}
        assert changed["2.1"] == "unchanged"
        assert changed["6.1"] == "unchanged"

    def test_changed_count_matches(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        assert snap2.changed_count == 2

    def test_unchanged_count_matches(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        assert snap2.unchanged_count == 2

    def test_diff_populated_for_changed_section(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        s = next(x for x in snap2.sections if x.section_id == "1.1")
        assert s.diff

    def test_diff_empty_for_unchanged_section(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        snap2 = engine.snapshot(bible_v2)
        s = next(x for x in snap2.sections if x.section_id == "2.1")
        assert s.diff == ""


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_empty_before_snapshot(self, engine):
        assert engine.get_history("1.1") == []

    def test_history_grows_per_snapshot(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        engine.snapshot(bible_v2)
        assert len(engine.get_history("1.1")) == 2

    def test_history_ordered_newest_first(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        engine.snapshot(bible_v2)
        hist = engine.get_history("1.1")
        assert hist[0].change_type == "changed"
        assert hist[1].change_type == "initial"

    def test_history_returns_section_snapshots(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        hist = engine.get_history("1.1")
        assert isinstance(hist[0], BibleSectionSnapshot)

    def test_history_independent_per_section(self, engine, bible_v1, bible_v2):
        engine.snapshot(bible_v1)
        engine.snapshot(bible_v2)
        # 2.1 unchanged — still 2 history entries, both in 2.1's history
        assert len(engine.get_history("2.1")) == 2
        assert engine.get_history("2.1")[0].change_type == "unchanged"


# ---------------------------------------------------------------------------
# Experience recording
# ---------------------------------------------------------------------------

class TestExperience:
    def test_record_returns_experience(self, engine):
        exp = engine.record_experience("1.1", "mem-abc", "supporting")
        assert isinstance(exp, BibleExperience)

    def test_experience_stored(self, engine):
        engine.record_experience("1.1", "mem-abc", "supporting")
        exps = engine.get_experiences("1.1")
        assert len(exps) == 1
        assert exps[0].memory_id == "mem-abc"

    def test_experience_type_preserved(self, engine):
        engine.record_experience("1.1", "m1", "supporting")
        engine.record_experience("1.1", "m2", "conflicting")
        types = {e.experience_type for e in engine.get_experiences("1.1")}
        assert types == {"supporting", "conflicting"}

    def test_strength_defaults_to_one(self, engine):
        engine.record_experience("1.1", "m1", "supporting")
        assert engine.get_experiences("1.1")[0].strength == 1.0

    def test_custom_strength_stored(self, engine):
        engine.record_experience("1.1", "m1", "supporting", strength=0.6)
        assert engine.get_experiences("1.1")[0].strength == pytest.approx(0.6)

    def test_experiences_empty_for_unknown_section(self, engine):
        assert engine.get_experiences("9.9") == []

    def test_invalid_experience_type_raises(self, engine):
        with pytest.raises(ValueError):
            engine.record_experience("1.1", "m1", "neutral")

    def test_multiple_experiences_different_sections(self, engine):
        engine.record_experience("1.1", "m1", "supporting")
        engine.record_experience("2.1", "m2", "conflicting")
        assert len(engine.get_experiences("1.1")) == 1
        assert len(engine.get_experiences("2.1")) == 1


# ---------------------------------------------------------------------------
# Reinforcement score
# ---------------------------------------------------------------------------

class TestReinforcementScore:
    def test_zero_with_no_experiences(self, engine):
        assert engine.get_reinforcement_score("1.1") == pytest.approx(0.0)

    def test_all_supporting_is_positive(self, engine):
        engine.record_experience("1.1", "m1", "supporting")
        engine.record_experience("1.1", "m2", "supporting")
        assert engine.get_reinforcement_score("1.1") > 0.0

    def test_all_conflicting_is_negative(self, engine):
        engine.record_experience("1.1", "m1", "conflicting")
        engine.record_experience("1.1", "m2", "conflicting")
        assert engine.get_reinforcement_score("1.1") < 0.0

    def test_score_bounded_to_minus_one_one(self, engine):
        for i in range(10):
            engine.record_experience("1.1", f"m{i}", "supporting")
        score = engine.get_reinforcement_score("1.1")
        assert -1.0 <= score <= 1.0

    def test_equal_support_and_conflict_cancels(self, engine):
        engine.record_experience("1.1", "m1", "supporting", strength=1.0)
        engine.record_experience("1.1", "m2", "conflicting", strength=1.0)
        assert engine.get_reinforcement_score("1.1") == pytest.approx(0.0)

    def test_strength_weighting(self, engine):
        engine.record_experience("1.1", "m1", "supporting", strength=0.9)
        engine.record_experience("1.1", "m2", "conflicting", strength=0.1)
        score = engine.get_reinforcement_score("1.1")
        assert score > 0.0  # net positive


# ---------------------------------------------------------------------------
# Stale sections
# ---------------------------------------------------------------------------

class TestStaleSections:
    def test_recently_snapshotted_not_stale(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        assert engine.get_stale_sections(threshold_days=30) == []

    def test_no_snapshots_returns_empty(self, engine):
        assert engine.get_stale_sections(threshold_days=30) == []


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------

class TestHealthReport:
    def test_empty_before_any_snapshots(self, engine):
        assert engine.get_section_health_report() == {}

    def test_includes_all_snapshotted_sections(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        report = engine.get_section_health_report()
        assert {"1.1", "1.2", "2.1", "6.1"}.issubset(report.keys())

    def test_report_has_required_keys(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        entry = engine.get_section_health_report()["1.1"]
        assert "reinforcement_score" in entry
        assert "experience_count" in entry
        assert "section_type" in entry
        assert "last_snapshotted" in entry

    def test_report_reflects_reinforcement(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        engine.record_experience("1.1", "m1", "supporting")
        engine.record_experience("1.1", "m2", "supporting")
        report = engine.get_section_health_report()
        assert report["1.1"]["reinforcement_score"] > 0
        assert report["1.1"]["experience_count"] == 2

    def test_section_type_correct_in_report(self, engine, bible_v1):
        engine.snapshot(bible_v1)
        report = engine.get_section_health_report()
        assert report["1.1"]["section_type"] == "principle"
        assert report["6.1"]["section_type"] == "anti_pattern"
