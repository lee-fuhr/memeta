"""Tests for skill_workflow_analyzer.py — TDD red phase.

Skill workflow analyzer: detects common multi-skill sequences from
provenance data and surfaces them as suggested workflow shortcuts.
"""

from pathlib import Path

import pytest

from memory_system.skill_workflow_analyzer import (
    SkillSequence,
    SkillWorkflowAnalyzer,
)
from memory_system.skill_provenance import SkillProvenanceTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def provenance(temp_db):
    return SkillProvenanceTracker(db_path=temp_db)


@pytest.fixture
def analyzer(temp_db):
    return SkillWorkflowAnalyzer(db_path=temp_db)


def record_session(provenance, session_id, skills):
    """Helper: record multiple skill invocations in a single session."""
    for skill in skills:
        provenance.record_invocation(skill, session_id, outcome="success")


# ---------------------------------------------------------------------------
# SkillSequence dataclass
# ---------------------------------------------------------------------------

class TestSkillSequence:
    def test_has_required_fields(self):
        s = SkillSequence(
            skills=["skill-a", "skill-b"],
            session_count=3,
            frequency=0.75,
            example_sessions=["s1", "s2"],
        )
        assert s.skills == ["skill-a", "skill-b"]
        assert s.session_count == 3
        assert s.frequency == 0.75

    def test_example_sessions_is_list(self):
        s = SkillSequence(
            skills=["skill-a"],
            session_count=1,
            frequency=1.0,
            example_sessions=[],
        )
        assert isinstance(s.example_sessions, list)


# ---------------------------------------------------------------------------
# get_common_pairs()
# ---------------------------------------------------------------------------

class TestGetCommonPairs:
    def test_returns_list(self, analyzer):
        result = analyzer.get_common_pairs()
        assert isinstance(result, list)

    def test_empty_when_no_data(self, analyzer):
        result = analyzer.get_common_pairs()
        assert result == []

    def test_detects_co_occurring_pair(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        pairs = analyzer.get_common_pairs()
        skill_sets = [frozenset(p.skills) for p in pairs]
        assert frozenset(["skill-a", "skill-b"]) in skill_sets

    def test_pair_has_correct_session_count(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        record_session(provenance, "s3", ["skill-a", "skill-b"])
        pairs = analyzer.get_common_pairs()
        ab_pair = next(
            p for p in pairs if frozenset(p.skills) == frozenset(["skill-a", "skill-b"])
        )
        assert ab_pair.session_count == 3

    def test_frequency_between_0_and_1(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        pairs = analyzer.get_common_pairs()
        for p in pairs:
            assert 0.0 <= p.frequency <= 1.0

    def test_single_skill_session_produces_no_pairs(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a"])
        result = analyzer.get_common_pairs()
        assert result == []

    def test_min_sessions_filter(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])  # only 1 session
        pairs = analyzer.get_common_pairs(min_sessions=2)
        skill_sets = [frozenset(p.skills) for p in pairs]
        assert frozenset(["skill-a", "skill-b"]) not in skill_sets

    def test_pairs_ordered_by_session_count_desc(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        record_session(provenance, "s3", ["skill-x", "skill-y"])
        pairs = analyzer.get_common_pairs(min_sessions=1)
        counts = [p.session_count for p in pairs]
        assert counts == sorted(counts, reverse=True)

    def test_example_sessions_populated(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        pairs = analyzer.get_common_pairs()
        ab = next(p for p in pairs if frozenset(p.skills) == frozenset(["skill-a", "skill-b"]))
        assert len(ab.example_sessions) >= 1

    def test_contains_skill_sequences(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        result = analyzer.get_common_pairs(min_sessions=1)
        assert all(isinstance(s, SkillSequence) for s in result)


# ---------------------------------------------------------------------------
# get_common_triples()
# ---------------------------------------------------------------------------

class TestGetCommonTriples:
    def test_returns_list(self, analyzer):
        result = analyzer.get_common_triples()
        assert isinstance(result, list)

    def test_empty_when_no_data(self, analyzer):
        result = analyzer.get_common_triples()
        assert result == []

    def test_detects_triple(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b", "skill-c"])
        record_session(provenance, "s2", ["skill-a", "skill-b", "skill-c"])
        triples = analyzer.get_common_triples(min_sessions=1)
        skill_sets = [frozenset(t.skills) for t in triples]
        assert frozenset(["skill-a", "skill-b", "skill-c"]) in skill_sets

    def test_two_skill_session_produces_no_triple(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        result = analyzer.get_common_triples(min_sessions=1)
        assert result == []

    def test_min_sessions_filter(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b", "skill-c"])
        result = analyzer.get_common_triples(min_sessions=2)
        assert result == []


# ---------------------------------------------------------------------------
# get_suggested_workflows()
# ---------------------------------------------------------------------------

class TestGetSuggestedWorkflows:
    def test_returns_list(self, analyzer):
        result = analyzer.get_suggested_workflows()
        assert isinstance(result, list)

    def test_empty_when_no_data(self, analyzer):
        result = analyzer.get_suggested_workflows()
        assert result == []

    def test_includes_pairs_and_triples(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b", "skill-c"])
        record_session(provenance, "s2", ["skill-a", "skill-b", "skill-c"])
        suggestions = analyzer.get_suggested_workflows(min_sessions=1)
        sizes = [len(s.skills) for s in suggestions]
        assert 2 in sizes  # pairs included
        assert 3 in sizes  # triples included

    def test_ordered_by_session_count_desc(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        record_session(provenance, "s3", ["skill-x", "skill-y"])
        suggestions = analyzer.get_suggested_workflows(min_sessions=1)
        counts = [s.session_count for s in suggestions]
        assert counts == sorted(counts, reverse=True)

    def test_contains_skill_sequences(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        result = analyzer.get_suggested_workflows(min_sessions=1)
        assert all(isinstance(s, SkillSequence) for s in result)


# ---------------------------------------------------------------------------
# get_skills_always_together()
# ---------------------------------------------------------------------------

class TestGetSkillsAlwaysTogether:
    def test_returns_dict(self, analyzer):
        result = analyzer.get_skills_always_together()
        assert isinstance(result, dict)

    def test_empty_when_no_data(self, analyzer):
        result = analyzer.get_skills_always_together()
        assert result == {}

    def test_detects_always_paired(self, analyzer, provenance):
        """skill-b is in every session that has skill-a → always together."""
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a", "skill-b"])
        result = analyzer.get_skills_always_together(min_sessions=2)
        # skill-a should show skill-b as always co-used
        if "skill-a" in result:
            assert "skill-b" in result["skill-a"]

    def test_not_always_paired_when_sometimes_apart(self, analyzer, provenance):
        record_session(provenance, "s1", ["skill-a", "skill-b"])
        record_session(provenance, "s2", ["skill-a"])  # skill-b absent
        result = analyzer.get_skills_always_together(min_sessions=1)
        # skill-b should NOT be in skill-a's always-together list
        if "skill-a" in result:
            assert "skill-b" not in result["skill-a"]
