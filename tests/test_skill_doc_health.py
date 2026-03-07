"""Tests for skill_doc_health.py — TDD red phase.

Skill documentation health system: detect stale and incomplete SKILL.md files,
flag skills missing required sections, compute health scores.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.skill_doc_health import (
    REQUIRED_SECTIONS,
    STALE_DAYS,
    SkillDocHealth,
    SkillHealthReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_complete_skill_md(skill_dir: Path) -> Path:
    """Write a SKILL.md with all required sections present."""
    md = skill_dir / "SKILL.md"
    md.write_text(
        "# My skill\n\n"
        "## When to use\n"
        "Use this when you need to do something.\n\n"
        "## Examples\n"
        "- Example one\n\n"
        "## Limitations\n"
        "- Does not handle edge cases.\n"
    )
    return md


def make_skill_dir(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def set_mtime_days_ago(path: Path, days: int) -> None:
    """Set a file's mtime to N days in the past."""
    old_ts = time.time() - days * 86400
    os.utime(path, (old_ts, old_ts))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def skills_dir(tmp_path):
    return tmp_path / "skills"


@pytest.fixture
def health(skills_dir):
    skills_dir.mkdir()
    return SkillDocHealth(skills_dir=skills_dir)


@pytest.fixture
def complete_skill(skills_dir):
    skills_dir.mkdir(exist_ok=True)
    d = make_skill_dir(skills_dir, "my-skill")
    make_complete_skill_md(d)
    return d


# ---------------------------------------------------------------------------
# check_skill() — basic presence
# ---------------------------------------------------------------------------

class TestCheckSkillPresence:
    def test_no_skill_md_health_score_zero(self, health, skills_dir):
        make_skill_dir(skills_dir, "empty-skill")
        report = health.check_skill("empty-skill")
        assert report.has_skill_md is False
        assert report.health_score == 0.0

    def test_no_skill_md_is_not_complete(self, health, skills_dir):
        make_skill_dir(skills_dir, "empty-skill")
        report = health.check_skill("empty-skill")
        assert report.is_complete is False

    def test_no_skill_md_all_sections_missing(self, health, skills_dir):
        make_skill_dir(skills_dir, "empty-skill")
        report = health.check_skill("empty-skill")
        assert len(report.missing_sections) == len(REQUIRED_SECTIONS)

    def test_has_skill_md_is_true(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert report.has_skill_md is True

    def test_skill_name_in_report(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert report.skill_name == "my-skill"

    def test_returns_skill_health_report(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert isinstance(report, SkillHealthReport)


# ---------------------------------------------------------------------------
# check_skill() — section detection
# ---------------------------------------------------------------------------

class TestCheckSkillSections:
    def test_all_sections_present_is_complete(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert report.is_complete is True
        assert report.missing_sections == []

    def test_missing_when_to_use(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "no-usage")
        (d / "SKILL.md").write_text(
            "# Skill\n\n## Examples\n- ex\n\n## Limitations\n- limit\n"
        )
        report = health.check_skill("no-usage")
        assert any("when to use" in s.lower() for s in report.missing_sections)
        assert report.is_complete is False

    def test_missing_examples(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "no-examples")
        (d / "SKILL.md").write_text(
            "# Skill\n\n## When to use\n- when\n\n## Limitations\n- limit\n"
        )
        report = health.check_skill("no-examples")
        assert any("examples" in s.lower() for s in report.missing_sections)
        assert report.is_complete is False

    def test_missing_limitations(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "no-limits")
        (d / "SKILL.md").write_text(
            "# Skill\n\n## When to use\n- when\n\n## Examples\n- ex\n"
        )
        report = health.check_skill("no-limits")
        assert any("limitations" in s.lower() for s in report.missing_sections)
        assert report.is_complete is False

    def test_all_sections_missing(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "bare-skill")
        (d / "SKILL.md").write_text("# Skill\n\nJust a title.\n")
        report = health.check_skill("bare-skill")
        assert len(report.missing_sections) == len(REQUIRED_SECTIONS)
        assert report.is_complete is False

    def test_section_match_is_case_insensitive(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "mixed-case")
        (d / "SKILL.md").write_text(
            "# Skill\n\n## WHEN TO USE\n- ok\n\n## EXAMPLES\n- ok\n\n## LIMITATIONS\n- ok\n"
        )
        report = health.check_skill("mixed-case")
        assert report.is_complete is True
        assert report.missing_sections == []

    def test_section_with_extra_whitespace(self, health, skills_dir):
        """## When to use  (trailing spaces) should still match."""
        d = make_skill_dir(skills_dir, "whitespace-skill")
        (d / "SKILL.md").write_text(
            "## When to use  \n- ok\n\n## Examples  \n- ok\n\n## Limitations  \n- ok\n"
        )
        report = health.check_skill("whitespace-skill")
        assert report.is_complete is True


# ---------------------------------------------------------------------------
# check_skill() — staleness
# ---------------------------------------------------------------------------

class TestCheckSkillStaleness:
    def test_fresh_file_not_stale(self, health, complete_skill):
        # File was just created — should not be stale
        report = health.check_skill("my-skill")
        assert report.is_stale is False

    def test_old_file_is_stale(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "old-skill")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, STALE_DAYS + 1)
        report = health.check_skill("old-skill")
        assert report.is_stale is True

    def test_exactly_stale_threshold(self, health, skills_dir):
        """File exactly at the threshold is stale."""
        d = make_skill_dir(skills_dir, "threshold-skill")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, STALE_DAYS)
        report = health.check_skill("threshold-skill")
        assert report.is_stale is True

    def test_days_since_update_computed(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "dated-skill")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, 45)
        report = health.check_skill("dated-skill")
        assert report.days_since_update is not None
        assert 44 <= report.days_since_update <= 46  # allow 1-day tolerance

    def test_no_skill_md_last_modified_is_none(self, health, skills_dir):
        make_skill_dir(skills_dir, "empty-skill")
        report = health.check_skill("empty-skill")
        assert report.last_modified is None
        assert report.days_since_update is None

    def test_last_modified_is_datetime(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert isinstance(report.last_modified, datetime)


# ---------------------------------------------------------------------------
# check_skill() — health score
# ---------------------------------------------------------------------------

class TestCheckSkillHealthScore:
    def test_perfect_health_score(self, health, complete_skill):
        """All sections, not stale → 1.0."""
        report = health.check_skill("my-skill")
        assert report.health_score == 1.0

    def test_stale_deducts_from_score(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "stale-skill")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, STALE_DAYS + 1)
        report = health.check_skill("stale-skill")
        assert report.health_score < 1.0
        assert report.health_score >= 0.0

    def test_missing_section_deducts_from_score(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "partial-skill")
        (d / "SKILL.md").write_text(
            "# Skill\n\n## When to use\n- ok\n\n## Examples\n- ok\n"
        )
        report = health.check_skill("partial-skill")
        # Missing "Limitations" — score should be < 1.0
        assert report.health_score < 1.0
        assert report.health_score > 0.0

    def test_no_file_score_is_zero(self, health, skills_dir):
        make_skill_dir(skills_dir, "missing-md")
        report = health.check_skill("missing-md")
        assert report.health_score == 0.0

    def test_health_score_in_range(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "any-skill")
        (d / "SKILL.md").write_text("# Skill\n\nNo sections.\n")
        report = health.check_skill("any-skill")
        assert 0.0 <= report.health_score <= 1.0

    def test_more_missing_sections_lower_score(self, health, skills_dir):
        """1 missing section < 2 missing sections < 3 missing sections."""
        d1 = make_skill_dir(skills_dir, "one-missing")
        (d1 / "SKILL.md").write_text(
            "# Skill\n\n## When to use\n- ok\n\n## Examples\n- ok\n"
        )  # missing Limitations
        d2 = make_skill_dir(skills_dir, "two-missing")
        (d2 / "SKILL.md").write_text(
            "# Skill\n\n## When to use\n- ok\n"
        )  # missing Examples + Limitations

        r1 = health.check_skill("one-missing")
        r2 = health.check_skill("two-missing")
        assert r1.health_score > r2.health_score


# ---------------------------------------------------------------------------
# check_skill() — issues list
# ---------------------------------------------------------------------------

class TestCheckSkillIssues:
    def test_perfect_skill_no_issues(self, health, complete_skill):
        report = health.check_skill("my-skill")
        assert report.issues == []

    def test_missing_section_in_issues(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "partial")
        (d / "SKILL.md").write_text("# Skill\n\nNo sections.\n")
        report = health.check_skill("partial")
        assert len(report.issues) > 0

    def test_stale_issue_text(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "old")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, STALE_DAYS + 10)
        report = health.check_skill("old")
        assert any("stale" in issue.lower() or "day" in issue.lower() for issue in report.issues)

    def test_no_skill_md_issue(self, health, skills_dir):
        make_skill_dir(skills_dir, "no-md")
        report = health.check_skill("no-md")
        assert any("skill.md" in issue.lower() or "missing" in issue.lower() for issue in report.issues)


# ---------------------------------------------------------------------------
# scan_all()
# ---------------------------------------------------------------------------

class TestScanAll:
    def test_returns_list(self, health):
        result = health.scan_all()
        assert isinstance(result, list)

    def test_empty_skills_dir(self, health):
        result = health.scan_all()
        assert result == []

    def test_ignores_non_directory_entries(self, health, skills_dir):
        (skills_dir / "readme.txt").write_text("not a skill")
        result = health.scan_all()
        assert result == []

    def test_scans_all_skill_dirs(self, health, skills_dir):
        for name in ("skill-a", "skill-b", "skill-c"):
            d = make_skill_dir(skills_dir, name)
            make_complete_skill_md(d)
        result = health.scan_all()
        assert len(result) == 3

    def test_returns_skill_health_reports(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "test-skill")
        make_complete_skill_md(d)
        result = health.scan_all()
        assert all(isinstance(r, SkillHealthReport) for r in result)

    def test_nonexistent_skills_dir_returns_empty(self, tmp_path):
        health = SkillDocHealth(skills_dir=tmp_path / "does-not-exist")
        assert health.scan_all() == []


# ---------------------------------------------------------------------------
# get_stale_skills()
# ---------------------------------------------------------------------------

class TestGetStaleSkills:
    def test_returns_only_stale(self, health, skills_dir):
        fresh = make_skill_dir(skills_dir, "fresh")
        make_complete_skill_md(fresh)

        old = make_skill_dir(skills_dir, "old")
        md = make_complete_skill_md(old)
        set_mtime_days_ago(md, STALE_DAYS + 5)

        result = health.get_stale_skills()
        names = [r.skill_name for r in result]
        assert "old" in names
        assert "fresh" not in names

    def test_empty_when_none_stale(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "fresh")
        make_complete_skill_md(d)
        result = health.get_stale_skills()
        assert result == []

    def test_custom_stale_threshold(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "moderately-old")
        md = make_complete_skill_md(d)
        set_mtime_days_ago(md, 10)

        # Default 30-day threshold: not stale
        assert health.get_stale_skills() == []
        # Custom 7-day threshold: stale
        result = health.get_stale_skills(days=7)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# get_incomplete_skills()
# ---------------------------------------------------------------------------

class TestGetIncompleteSkills:
    def test_returns_only_incomplete(self, health, skills_dir):
        complete = make_skill_dir(skills_dir, "complete")
        make_complete_skill_md(complete)

        incomplete = make_skill_dir(skills_dir, "incomplete")
        (incomplete / "SKILL.md").write_text("# Skill\n\nNo required sections.\n")

        result = health.get_incomplete_skills()
        names = [r.skill_name for r in result]
        assert "incomplete" in names
        assert "complete" not in names

    def test_empty_when_all_complete(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "complete")
        make_complete_skill_md(d)
        result = health.get_incomplete_skills()
        assert result == []


# ---------------------------------------------------------------------------
# get_missing_skills()
# ---------------------------------------------------------------------------

class TestGetMissingSkills:
    def test_returns_skills_without_skill_md(self, health, skills_dir):
        make_skill_dir(skills_dir, "no-doc")  # no SKILL.md
        d = make_skill_dir(skills_dir, "has-doc")
        make_complete_skill_md(d)

        result = health.get_missing_skills()
        names = [r.skill_name for r in result]
        assert "no-doc" in names
        assert "has-doc" not in names

    def test_empty_when_all_have_skill_md(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "documented")
        make_complete_skill_md(d)
        result = health.get_missing_skills()
        assert result == []


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_returns_dict(self, health):
        result = health.summary()
        assert isinstance(result, dict)

    def test_summary_has_required_keys(self, health):
        result = health.summary()
        for key in ("total", "stale", "incomplete", "missing_skill_md", "avg_health_score", "healthy"):
            assert key in result, f"Missing key: {key}"

    def test_summary_counts_correct(self, health, skills_dir):
        # Complete + fresh
        d1 = make_skill_dir(skills_dir, "good")
        make_complete_skill_md(d1)

        # Complete but stale
        d2 = make_skill_dir(skills_dir, "stale")
        md2 = make_complete_skill_md(d2)
        set_mtime_days_ago(md2, STALE_DAYS + 5)

        # No SKILL.md
        make_skill_dir(skills_dir, "no-doc")

        result = health.summary()
        assert result["total"] == 3
        assert result["stale"] == 1
        assert result["missing_skill_md"] == 1

    def test_summary_avg_health_score(self, health, skills_dir):
        d = make_skill_dir(skills_dir, "perfect")
        make_complete_skill_md(d)
        result = health.summary()
        assert result["avg_health_score"] == 1.0

    def test_summary_empty_dir(self, health):
        result = health.summary()
        assert result["total"] == 0
        assert result["avg_health_score"] == 0.0

    def test_summary_healthy_count(self, health, skills_dir):
        """'healthy' counts skills with health_score >= 0.8."""
        d = make_skill_dir(skills_dir, "perfect")
        make_complete_skill_md(d)
        result = health.summary()
        assert result["healthy"] == 1
