"""Tests for skill_effectiveness.py — TDD red phase.

Skill effectiveness tracker: synthesizes provenance outcomes and evolution
snapshots into an effectiveness score per skill. Tracks success rate, usage
trend, and staleness to produce an actionable health picture.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.skill_effectiveness import (
    EffectivenessReport,
    SkillEffectivenessTracker,
)
from memory_system.skill_provenance import SkillProvenanceTracker
from memory_system.skill_evolution import SkillEvolutionTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def provenance(temp_db):
    return SkillProvenanceTracker(db_path=temp_db)


@pytest.fixture
def evolution(temp_db, skills_dir):
    return SkillEvolutionTracker(db_path=temp_db, skills_dir=skills_dir)


@pytest.fixture
def tracker(temp_db, skills_dir):
    return SkillEffectivenessTracker(db_path=temp_db, skills_dir=skills_dir)


def write_skill_md(skills_dir: Path, skill_name: str, content: str) -> Path:
    d = skills_dir / skill_name
    d.mkdir(exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(content)
    return md


FULL_SKILL_MD = """# My skill

## When to use
Use this when you need to do the thing.

## Examples
- Example A

## Limitations
- None.
"""


# ---------------------------------------------------------------------------
# EffectivenessReport dataclass
# ---------------------------------------------------------------------------

class TestEffectivenessReport:
    def test_has_required_fields(self):
        r = EffectivenessReport(
            skill_name="my-skill",
            invocation_count=5,
            success_rate=0.8,
            failure_rate=0.2,
            unknown_rate=0.0,
            recent_invocations=3,
            has_evolved=True,
            effectiveness_score=0.75,
            grade="B",
            issues=[],
        )
        assert r.skill_name == "my-skill"
        assert r.effectiveness_score == 0.75
        assert r.grade == "B"

    def test_issues_defaults_to_empty_list(self):
        r = EffectivenessReport(
            skill_name="my-skill",
            invocation_count=0,
            success_rate=0.0,
            failure_rate=0.0,
            unknown_rate=0.0,
            recent_invocations=0,
            has_evolved=False,
            effectiveness_score=0.0,
            grade="F",
            issues=[],
        )
        assert r.issues == []


# ---------------------------------------------------------------------------
# assess()
# ---------------------------------------------------------------------------

class TestAssess:
    def test_returns_effectiveness_report(self, tracker):
        result = tracker.assess("my-skill")
        assert isinstance(result, EffectivenessReport)

    def test_skill_name_in_report(self, tracker):
        result = tracker.assess("my-skill")
        assert result.skill_name == "my-skill"

    def test_zero_invocations_by_default(self, tracker):
        result = tracker.assess("my-skill")
        assert result.invocation_count == 0

    def test_counts_invocations_from_provenance(self, tracker, provenance):
        provenance.record_invocation("my-skill", "s1", outcome="success")
        provenance.record_invocation("my-skill", "s2", outcome="success")
        result = tracker.assess("my-skill")
        assert result.invocation_count == 2

    def test_success_rate_all_success(self, tracker, provenance):
        for i in range(3):
            provenance.record_invocation("my-skill", f"s{i}", outcome="success")
        result = tracker.assess("my-skill")
        assert result.success_rate == pytest.approx(1.0)

    def test_success_rate_mixed(self, tracker, provenance):
        provenance.record_invocation("my-skill", "s1", outcome="success")
        provenance.record_invocation("my-skill", "s2", outcome="failure")
        result = tracker.assess("my-skill")
        assert result.success_rate == pytest.approx(0.5)
        assert result.failure_rate == pytest.approx(0.5)

    def test_success_rate_zero_when_no_invocations(self, tracker):
        result = tracker.assess("my-skill")
        assert result.success_rate == 0.0

    def test_unknown_rate(self, tracker, provenance):
        provenance.record_invocation("my-skill", "s1")  # default outcome=unknown
        result = tracker.assess("my-skill")
        assert result.unknown_rate == pytest.approx(1.0)

    def test_has_evolved_true_when_meaningful_change(
        self, tracker, evolution, skills_dir
    ):
        write_skill_md(skills_dir, "my-skill", FULL_SKILL_MD)
        evolution.snapshot("my-skill")
        write_skill_md(
            skills_dir,
            "my-skill",
            FULL_SKILL_MD + "\n## Extra section\nNew content.\n",
        )
        evolution.snapshot("my-skill")
        result = tracker.assess("my-skill")
        assert result.has_evolved is True

    def test_has_evolved_false_when_no_snapshots(self, tracker):
        result = tracker.assess("my-skill")
        assert result.has_evolved is False

    def test_effectiveness_score_between_0_and_1(self, tracker):
        result = tracker.assess("my-skill")
        assert 0.0 <= result.effectiveness_score <= 1.0

    def test_effectiveness_score_higher_with_successes(self, tracker, provenance):
        for i in range(5):
            provenance.record_invocation("my-skill", f"s{i}", outcome="success")
        result = tracker.assess("my-skill")
        no_use = SkillEffectivenessTracker.__new__(SkillEffectivenessTracker)
        # Score with successes should be higher than score with no invocations
        baseline = tracker.assess("other-skill").effectiveness_score
        assert result.effectiveness_score >= baseline

    def test_grade_is_valid_letter(self, tracker):
        result = tracker.assess("my-skill")
        assert result.grade in ("A", "B", "C", "D", "F")

    def test_grade_A_for_high_score(self, tracker, provenance):
        for i in range(10):
            provenance.record_invocation("my-skill", f"s{i}", outcome="success")
        result = tracker.assess("my-skill")
        assert result.grade in ("A", "B")  # many successes → high grade

    def test_grade_F_for_no_use(self, tracker):
        result = tracker.assess("my-skill")
        assert result.grade == "F"

    def test_issues_list_populated_for_problems(self, tracker, provenance):
        provenance.record_invocation("my-skill", "s1", outcome="failure")
        provenance.record_invocation("my-skill", "s2", outcome="failure")
        result = tracker.assess("my-skill")
        assert len(result.issues) > 0

    def test_issues_empty_for_healthy_skill(self, tracker, provenance):
        for i in range(5):
            provenance.record_invocation("my-skill", f"s{i}", outcome="success")
        result = tracker.assess("my-skill")
        # A skill with all successes and no staleness should have few/no issues
        failure_issues = [i for i in result.issues if "failure" in i.lower()]
        assert failure_issues == []


# ---------------------------------------------------------------------------
# assess_all()
# ---------------------------------------------------------------------------

class TestAssessAll:
    def test_returns_list(self, tracker):
        result = tracker.assess_all()
        assert isinstance(result, list)

    def test_empty_when_no_known_skills(self, tracker):
        result = tracker.assess_all()
        assert result == []

    def test_covers_all_skills_with_provenance(self, tracker, provenance):
        provenance.record_invocation("skill-a", "s1")
        provenance.record_invocation("skill-b", "s1")
        result = tracker.assess_all()
        names = [r.skill_name for r in result]
        assert "skill-a" in names
        assert "skill-b" in names

    def test_contains_effectiveness_reports(self, tracker, provenance):
        provenance.record_invocation("my-skill", "s1")
        result = tracker.assess_all()
        assert all(isinstance(r, EffectivenessReport) for r in result)


# ---------------------------------------------------------------------------
# get_top_skills()
# ---------------------------------------------------------------------------

class TestGetTopSkills:
    def test_returns_list(self, tracker):
        result = tracker.get_top_skills()
        assert isinstance(result, list)

    def test_ordered_by_effectiveness_score_desc(self, tracker, provenance):
        for i in range(5):
            provenance.record_invocation("skill-a", f"s{i}", outcome="success")
        provenance.record_invocation("skill-b", "s1", outcome="failure")
        top = tracker.get_top_skills()
        assert top[0].skill_name == "skill-a"

    def test_respects_limit(self, tracker, provenance):
        for name in ("skill-a", "skill-b", "skill-c"):
            provenance.record_invocation(name, "s1", outcome="success")
        top = tracker.get_top_skills(limit=2)
        assert len(top) <= 2


# ---------------------------------------------------------------------------
# get_underperforming_skills()
# ---------------------------------------------------------------------------

class TestGetUnderperformingSkills:
    def test_returns_list(self, tracker):
        result = tracker.get_underperforming_skills()
        assert isinstance(result, list)

    def test_returns_skills_below_threshold(self, tracker, provenance):
        provenance.record_invocation("bad-skill", "s1", outcome="failure")
        provenance.record_invocation("bad-skill", "s2", outcome="failure")
        result = tracker.get_underperforming_skills(threshold=0.5)
        names = [r.skill_name for r in result]
        assert "bad-skill" in names

    def test_excludes_good_skills(self, tracker, provenance):
        for i in range(5):
            provenance.record_invocation("good-skill", f"s{i}", outcome="success")
        result = tracker.get_underperforming_skills(threshold=0.3)
        names = [r.skill_name for r in result]
        assert "good-skill" not in names
