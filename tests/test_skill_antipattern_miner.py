"""Tests for skill_antipattern_miner.py — TDD red phase.

Skill anti-pattern miner: detects when corrections appear in sessions
where specific skills were loaded. When a correction co-occurs with a
skill frequently enough, the skill is flagged as a potential contributor.
"""

from pathlib import Path

import pytest

from memory_system.skill_antipattern_miner import (
    AntiPatternReport,
    SkillAntiPatternMiner,
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
def provenance(temp_db):
    return SkillProvenanceTracker(db_path=temp_db)


@pytest.fixture
def memory_client(memory_dir):
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def miner(temp_db, memory_dir):
    return SkillAntiPatternMiner(db_path=temp_db, memory_dir=memory_dir)


def record_invocation(provenance, skill, session_id, outcome="success"):
    provenance.record_invocation(skill, session_id, outcome=outcome)


def make_correction(memory_client, content, session_id, confirmations=1):
    """Create a correction memory attributed to a specific session."""
    return memory_client.create(
        content=content,
        project_id="test",
        importance=0.9,
        context_type="correction",
        tags=["#correction"],
        source_session_id=session_id,
        confirmations=confirmations,
    )


# ---------------------------------------------------------------------------
# AntiPatternReport dataclass
# ---------------------------------------------------------------------------

class TestAntiPatternReport:
    def test_has_required_fields(self):
        r = AntiPatternReport(
            skill_name="my-skill",
            co_occurrence_count=3,
            total_sessions=5,
            co_occurrence_rate=0.6,
            sample_corrections=["Don't do X", "Always do Y"],
            risk_level="medium",
        )
        assert r.skill_name == "my-skill"
        assert r.co_occurrence_count == 3
        assert r.risk_level == "medium"

    def test_sample_corrections_is_list(self):
        r = AntiPatternReport(
            skill_name="my-skill",
            co_occurrence_count=0,
            total_sessions=0,
            co_occurrence_rate=0.0,
            sample_corrections=[],
            risk_level="none",
        )
        assert r.sample_corrections == []


# ---------------------------------------------------------------------------
# analyze()
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_returns_list(self, miner):
        result = miner.analyze()
        assert isinstance(result, list)

    def test_empty_when_no_data(self, miner):
        result = miner.analyze()
        assert result == []

    def test_empty_when_no_corrections(self, miner, provenance):
        record_invocation(provenance, "my-skill", "s1")
        result = miner.analyze()
        assert result == []

    def test_detects_co_occurring_skill(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        make_correction(memory_client, "Don't do X", "s1")
        result = miner.analyze(min_co_occurrences=1)
        skill_names = [r.skill_name for r in result]
        assert "my-skill" in skill_names

    def test_excludes_skill_without_co_occurrence(self, miner, provenance, memory_client):
        record_invocation(provenance, "good-skill", "s1")
        make_correction(memory_client, "Don't do X", "s2")  # different session
        result = miner.analyze(min_co_occurrences=1)
        skill_names = [r.skill_name for r in result]
        assert "good-skill" not in skill_names

    def test_co_occurrence_count_correct(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        record_invocation(provenance, "my-skill", "s2")
        make_correction(memory_client, "Issue A", "s1")
        make_correction(memory_client, "Issue B", "s2")
        result = miner.analyze(min_co_occurrences=1)
        report = next(r for r in result if r.skill_name == "my-skill")
        assert report.co_occurrence_count == 2

    def test_min_co_occurrences_filter(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        make_correction(memory_client, "Issue", "s1")
        # Only 1 co-occurrence, filter requires 2
        result = miner.analyze(min_co_occurrences=2)
        skill_names = [r.skill_name for r in result]
        assert "my-skill" not in skill_names

    def test_co_occurrence_rate_between_0_and_1(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        record_invocation(provenance, "my-skill", "s2")
        make_correction(memory_client, "Issue", "s1")
        result = miner.analyze(min_co_occurrences=1)
        for r in result:
            assert 0.0 <= r.co_occurrence_rate <= 1.0

    def test_sample_corrections_populated(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        make_correction(memory_client, "Always do X instead", "s1")
        result = miner.analyze(min_co_occurrences=1)
        report = next(r for r in result if r.skill_name == "my-skill")
        assert len(report.sample_corrections) >= 1

    def test_contains_antipattern_reports(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        make_correction(memory_client, "Issue", "s1")
        result = miner.analyze(min_co_occurrences=1)
        assert all(isinstance(r, AntiPatternReport) for r in result)

    def test_ordered_by_co_occurrence_count_desc(self, miner, provenance, memory_client):
        # skill-a co-occurs twice, skill-b once
        record_invocation(provenance, "skill-a", "s1")
        record_invocation(provenance, "skill-a", "s2")
        record_invocation(provenance, "skill-b", "s3")
        make_correction(memory_client, "C1", "s1")
        make_correction(memory_client, "C2", "s2")
        make_correction(memory_client, "C3", "s3")
        result = miner.analyze(min_co_occurrences=1)
        counts = [r.co_occurrence_count for r in result]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# risk_level classification
# ---------------------------------------------------------------------------

class TestRiskLevel:
    def test_risk_level_valid_values(self, miner, provenance, memory_client):
        record_invocation(provenance, "my-skill", "s1")
        make_correction(memory_client, "Issue", "s1")
        result = miner.analyze(min_co_occurrences=1)
        for r in result:
            assert r.risk_level in ("low", "medium", "high", "none")

    def test_high_rate_is_high_risk(self, miner, provenance, memory_client):
        # 4/4 sessions have corrections with this skill → high rate
        for i in range(4):
            record_invocation(provenance, "risky-skill", f"s{i}")
            make_correction(memory_client, f"Issue {i}", f"s{i}")
        result = miner.analyze(min_co_occurrences=1)
        report = next((r for r in result if r.skill_name == "risky-skill"), None)
        assert report is not None
        assert report.risk_level in ("medium", "high")


# ---------------------------------------------------------------------------
# get_flagged_skills()
# ---------------------------------------------------------------------------

class TestGetFlaggedSkills:
    def test_returns_list(self, miner):
        result = miner.get_flagged_skills()
        assert isinstance(result, list)

    def test_empty_when_no_flags(self, miner):
        result = miner.get_flagged_skills()
        assert result == []

    def test_returns_skill_names(self, miner, provenance, memory_client):
        record_invocation(provenance, "risky-skill", "s1")
        make_correction(memory_client, "Issue", "s1")
        result = miner.get_flagged_skills(min_co_occurrences=1)
        assert "risky-skill" in result

    def test_returns_strings_not_reports(self, miner, provenance, memory_client):
        record_invocation(provenance, "risky-skill", "s1")
        make_correction(memory_client, "Issue", "s1")
        result = miner.get_flagged_skills(min_co_occurrences=1)
        assert all(isinstance(s, str) for s in result)
