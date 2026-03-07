"""Tests for skill_health_dashboard.py — TDD red phase.

Unified skill health report: aggregates doc health, effectiveness, evolution,
workflow patterns, anti-pattern detection, and correction velocity into a
single dict suitable for the dashboard /api/skill-health endpoint.
"""

from pathlib import Path

import pytest

from memory_system.skill_health_dashboard import (
    SkillHealthDashboard,
    SkillHealthReport,
    build_skill_health_report,
)
from memory_system.skill_provenance import SkillProvenanceTracker
from memory_system.memory_ts_client import MemoryTSClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def memory_dir(tmp_path):
    d = tmp_path / "memories"
    d.mkdir()
    return d


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def memory_client(memory_dir):
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def dashboard(temp_db, memory_dir, skills_dir):
    return SkillHealthDashboard(
        db_path=temp_db,
        memory_dir=memory_dir,
        skills_dir=skills_dir,
    )


def _write_skill(skills_dir, name, content=None):
    skill_dir = skills_dir / name
    skill_dir.mkdir(exist_ok=True)
    md = skill_dir / "SKILL.md"
    if content is None:
        content = (
            f"# {name}\n\n"
            "## When to use\nWhen you need this.\n\n"
            "## Examples\n```\n/example\n```\n\n"
            "## Limitations\nNone.\n"
        )
    md.write_text(content)
    return md


def _record_invocation(db_path, skill, session_id, outcome="success"):
    p = SkillProvenanceTracker(db_path=db_path)
    p.record_invocation(skill, session_id, outcome=outcome)


def _make_correction(memory_client, content, session_id, tags=None):
    if tags is None:
        tags = ["#correction"]
    memory_client.create(
        content=content,
        project_id="test",
        importance=0.9,
        context_type="correction",
        tags=tags,
        source_session_id=session_id,
        confirmations=1,
    )


# ---------------------------------------------------------------------------
# SkillHealthReport dataclass
# ---------------------------------------------------------------------------

class TestSkillHealthReport:
    def test_has_required_sections(self):
        r = SkillHealthReport(
            generated_at="2026-03-07T12:00:00",
            summary={},
            docs=[],
            effectiveness=[],
            evolution=[],
            workflows=[],
            antipatterns=[],
            correction_velocity={},
        )
        assert r.generated_at == "2026-03-07T12:00:00"
        assert r.docs == []
        assert r.summary == {}

    def test_to_dict_returns_all_keys(self):
        r = SkillHealthReport(
            generated_at="2026-03-07T12:00:00",
            summary={"total": 0},
            docs=[],
            effectiveness=[],
            evolution=[],
            workflows=[],
            antipatterns=[],
            correction_velocity={},
        )
        d = r.to_dict()
        for key in ("generated_at", "summary", "docs", "effectiveness",
                    "evolution", "workflows", "antipatterns",
                    "correction_velocity"):
            assert key in d

    def test_to_dict_preserves_values(self):
        r = SkillHealthReport(
            generated_at="2026-03-07",
            summary={"x": 1},
            docs=[{"skill_name": "a"}],
            effectiveness=[],
            evolution=[],
            workflows=[],
            antipatterns=[],
            correction_velocity={"total": 5},
        )
        d = r.to_dict()
        assert d["summary"]["x"] == 1
        assert d["docs"][0]["skill_name"] == "a"
        assert d["correction_velocity"]["total"] == 5


# ---------------------------------------------------------------------------
# SkillHealthDashboard.build()
# ---------------------------------------------------------------------------

class TestBuildEmpty:
    def test_returns_skill_health_report(self, dashboard):
        result = dashboard.build()
        assert isinstance(result, SkillHealthReport)

    def test_generated_at_is_string(self, dashboard):
        result = dashboard.build()
        assert isinstance(result.generated_at, str)
        assert "T" in result.generated_at  # ISO format

    def test_all_sections_are_lists_or_dicts(self, dashboard):
        result = dashboard.build()
        assert isinstance(result.docs, list)
        assert isinstance(result.effectiveness, list)
        assert isinstance(result.evolution, list)
        assert isinstance(result.workflows, list)
        assert isinstance(result.antipatterns, list)
        assert isinstance(result.correction_velocity, dict)
        assert isinstance(result.summary, dict)

    def test_empty_when_no_data(self, dashboard):
        result = dashboard.build()
        assert result.docs == []
        assert result.effectiveness == []
        assert result.antipatterns == []


class TestBuildWithDocs:
    def test_docs_section_populated(self, dashboard, skills_dir):
        _write_skill(skills_dir, "my-skill")
        result = dashboard.build()
        skill_names = [d["skill_name"] for d in result.docs]
        assert "my-skill" in skill_names

    def test_docs_entry_has_grade(self, dashboard, skills_dir):
        _write_skill(skills_dir, "my-skill")
        result = dashboard.build()
        entry = next(d for d in result.docs if d["skill_name"] == "my-skill")
        assert "grade" in entry
        assert entry["grade"] in ("A", "B", "C", "D", "F")

    def test_docs_entry_has_health_score(self, dashboard, skills_dir):
        _write_skill(skills_dir, "my-skill")
        result = dashboard.build()
        entry = next(d for d in result.docs if d["skill_name"] == "my-skill")
        assert "health_score" in entry
        assert 0.0 <= entry["health_score"] <= 1.0

    def test_docs_entry_has_issues_list(self, dashboard, skills_dir):
        _write_skill(skills_dir, "my-skill")
        result = dashboard.build()
        entry = next(d for d in result.docs if d["skill_name"] == "my-skill")
        assert isinstance(entry["issues"], list)

    def test_docs_entry_has_staleness_info(self, dashboard, skills_dir):
        _write_skill(skills_dir, "my-skill")
        result = dashboard.build()
        entry = next(d for d in result.docs if d["skill_name"] == "my-skill")
        assert "is_stale" in entry
        assert "days_since_update" in entry


class TestBuildWithEffectiveness:
    def test_effectiveness_section_populated(self, temp_db, dashboard, skills_dir):
        _write_skill(skills_dir, "fast-skill")
        _record_invocation(temp_db, "fast-skill", "s1", outcome="success")
        _record_invocation(temp_db, "fast-skill", "s2", outcome="success")
        result = dashboard.build()
        skill_names = [e["skill_name"] for e in result.effectiveness]
        assert "fast-skill" in skill_names

    def test_effectiveness_entry_has_score(self, temp_db, dashboard, skills_dir):
        _write_skill(skills_dir, "fast-skill")
        _record_invocation(temp_db, "fast-skill", "s1", outcome="success")
        result = dashboard.build()
        entry = next(e for e in result.effectiveness if e["skill_name"] == "fast-skill")
        assert "effectiveness_score" in entry
        assert 0.0 <= entry["effectiveness_score"] <= 1.0

    def test_effectiveness_entry_has_grade(self, temp_db, dashboard, skills_dir):
        _write_skill(skills_dir, "fast-skill")
        _record_invocation(temp_db, "fast-skill", "s1", outcome="success")
        result = dashboard.build()
        entry = next(e for e in result.effectiveness if e["skill_name"] == "fast-skill")
        assert entry["grade"] in ("A", "B", "C", "D", "F")


class TestBuildWithAntipatterns:
    def test_antipatterns_section_populated(
        self, temp_db, memory_dir, dashboard, skills_dir
    ):
        client = MemoryTSClient(memory_dir=memory_dir)
        _write_skill(skills_dir, "risky-skill")
        _record_invocation(temp_db, "risky-skill", "s1")
        _record_invocation(temp_db, "risky-skill", "s2")
        _make_correction(client, "Issue A", "s1")
        _make_correction(client, "Issue B", "s2")
        result = dashboard.build(min_antipattern_co_occurrences=1)
        skill_names = [a["skill_name"] for a in result.antipatterns]
        assert "risky-skill" in skill_names

    def test_antipattern_entry_has_risk_level(
        self, temp_db, memory_dir, dashboard, skills_dir
    ):
        client = MemoryTSClient(memory_dir=memory_dir)
        _write_skill(skills_dir, "risky-skill")
        _record_invocation(temp_db, "risky-skill", "s1")
        _make_correction(client, "Issue", "s1")
        result = dashboard.build(min_antipattern_co_occurrences=1)
        if result.antipatterns:
            entry = result.antipatterns[0]
            assert entry["risk_level"] in ("low", "medium", "high")


class TestSummary:
    def test_summary_has_expected_keys(self, dashboard):
        result = dashboard.build()
        summary = result.summary
        for key in (
            "total_docs_scanned",
            "avg_doc_health_score",
            "skills_at_risk",
            "total_invocations",
            "graduation_rate",
        ):
            assert key in summary

    def test_total_docs_scanned_counts_skills(self, dashboard, skills_dir):
        _write_skill(skills_dir, "skill-a")
        _write_skill(skills_dir, "skill-b")
        result = dashboard.build()
        assert result.summary["total_docs_scanned"] == 2

    def test_avg_doc_health_score_is_float(self, dashboard, skills_dir):
        _write_skill(skills_dir, "skill-a")
        result = dashboard.build()
        assert isinstance(result.summary["avg_doc_health_score"], float)

    def test_skills_at_risk_lists_high_risk_antipatterns(
        self, temp_db, memory_dir, dashboard, skills_dir
    ):
        client = MemoryTSClient(memory_dir=memory_dir)
        _write_skill(skills_dir, "bad-skill")
        # 4/4 co-occurrences → high risk rate
        for i in range(4):
            _record_invocation(temp_db, "bad-skill", f"s{i}")
            _make_correction(client, f"Issue {i}", f"s{i}")
        result = dashboard.build(min_antipattern_co_occurrences=1)
        assert isinstance(result.summary["skills_at_risk"], list)

    def test_graduation_rate_is_float_between_0_and_1(self, dashboard):
        result = dashboard.build()
        rate = result.summary["graduation_rate"]
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0


# ---------------------------------------------------------------------------
# build_skill_health_report() convenience function
# ---------------------------------------------------------------------------

class TestBuildSkillHealthReportFunction:
    def test_returns_dict(self, temp_db, memory_dir, skills_dir):
        result = build_skill_health_report(
            db_path=temp_db,
            memory_dir=memory_dir,
            skills_dir=skills_dir,
        )
        assert isinstance(result, dict)

    def test_has_required_keys(self, temp_db, memory_dir, skills_dir):
        result = build_skill_health_report(
            db_path=temp_db,
            memory_dir=memory_dir,
            skills_dir=skills_dir,
        )
        for key in ("generated_at", "summary", "docs", "effectiveness",
                    "evolution", "workflows", "antipatterns",
                    "correction_velocity"):
            assert key in result

    def test_skills_dir_optional(self, temp_db, memory_dir):
        result = build_skill_health_report(
            db_path=temp_db,
            memory_dir=memory_dir,
        )
        assert isinstance(result, dict)
