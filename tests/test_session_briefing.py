"""Tests for session_briefing.py — TDD red phase.

Session-start briefing: unified context card combining memories,
corrections, commitments, and skill recommendations.
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.session_briefing import SessionBriefing, _summarize_trigger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def empty_index(temp_dir):
    """Empty memory search index JSON file."""
    index_path = temp_dir / "memory-search-index.json"
    index_path.write_text("[]")
    return index_path


@pytest.fixture
def index_with_memories(temp_dir):
    """Index with a mix of regular memories and corrections."""
    entries = [
        {
            "id": "mem-1",
            "content": "Python BM25 search works well for keyword matching",
            "importance": 0.8,
            "context_type": "knowledge",
            "tags": ["python", "search"],
        },
        {
            "id": "mem-2",
            "content": "Always use sentence case for headings in markdown documents",
            "importance": 0.9,
            "context_type": "correction",
            "tags": ["style"],
        },
        {
            "id": "mem-3",
            "content": "Never use title case in filenames or headings",
            "importance": 0.95,
            "context_type": "correction",
            "tags": ["style"],
        },
        {
            "id": "mem-4",
            "content": "BM25 scoring relies on term frequency and inverse document frequency",
            "importance": 0.7,
            "context_type": "knowledge",
            "tags": ["search", "algorithm"],
        },
    ]
    index_path = temp_dir / "memory-search-index.json"
    index_path.write_text(json.dumps(entries))
    return index_path


@pytest.fixture
def skills_dir(temp_dir):
    """Fake skills directory with two skills."""
    sdir = temp_dir / "skills"
    sdir.mkdir()

    # Skill: python-best-practices
    python_skill = sdir / "python-best-practices"
    python_skill.mkdir()
    (python_skill / "SKILL.md").write_text(
        "# Python best practices\n\n"
        "## When to use\n"
        "Use when writing Python code, debugging Python errors, or reviewing scripts.\n\n"
        "## Examples\n"
        "- Type annotations\n"
    )

    # Skill: messaging-framework
    msg_skill = sdir / "messaging-framework"
    msg_skill.mkdir()
    (msg_skill / "SKILL.md").write_text(
        "# Messaging framework\n\n"
        "## When to use\n"
        "Use when building brand messaging, positioning, or copywriting.\n\n"
        "## Examples\n"
        "- Brand voice\n"
    )

    # Non-directory item (should be ignored)
    (sdir / "not-a-skill.txt").write_text("ignore me")

    return sdir


@pytest.fixture
def briefing_with_index(index_with_memories, temp_dir):
    return SessionBriefing(
        db_path=temp_dir / "test.db",
        index_path=index_with_memories,
        skills_dir=temp_dir / "skills",
    )


@pytest.fixture
def briefing_with_skills(index_with_memories, skills_dir, temp_dir):
    return SessionBriefing(
        db_path=temp_dir / "test.db",
        index_path=index_with_memories,
        skills_dir=skills_dir,
    )


# ---------------------------------------------------------------------------
# generate() — smoke tests
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_generate_returns_string(self, briefing_with_index):
        result = briefing_with_index.generate(topic="python search")
        assert isinstance(result, str)

    def test_generate_empty_topic_no_crash(self, briefing_with_index):
        """Empty topic must not raise."""
        result = briefing_with_index.generate(topic="")
        assert isinstance(result, str)

    def test_generate_no_args_returns_string(self, briefing_with_index):
        result = briefing_with_index.generate()
        assert isinstance(result, str)

    def test_generate_all_empty_returns_empty(self, empty_index, temp_dir):
        """When index is empty and no DB, result should be empty."""
        briefing = SessionBriefing(
            db_path=temp_dir / "nonexistent.db",
            index_path=empty_index,
            skills_dir=temp_dir / "no-skills",
        )
        result = briefing.generate(topic="")
        assert result == ""

    def test_generate_with_corrections_returns_nonempty(self, briefing_with_index):
        """Index has corrections → briefing should not be empty."""
        result = briefing_with_index.generate()
        assert result != ""

    def test_generate_with_topic_includes_memory_section(self, briefing_with_index):
        """Topic 'BM25 search' should pull relevant memories into briefing."""
        result = briefing_with_index.generate(topic="BM25 search keyword")
        # Should have memories section when topic matches
        assert "Relevant memories" in result or result == ""

    def test_generate_includes_header_when_nonempty(self, briefing_with_index):
        result = briefing_with_index.generate()
        if result:
            assert result.startswith("# Session brief")

    def test_generate_respects_max_corrections(self, index_with_memories, temp_dir):
        """max_corrections=1 should limit correction count."""
        briefing = SessionBriefing(
            db_path=temp_dir / "test.db",
            index_path=index_with_memories,
        )
        result = briefing.generate(max_corrections=1)
        # Count bullet points in corrections section
        if "Active corrections" in result:
            corrections_section = result.split("## Active corrections")[1]
            next_section_idx = corrections_section.find("\n## ")
            if next_section_idx >= 0:
                corrections_section = corrections_section[:next_section_idx]
            bullet_count = corrections_section.count("\n-")
            assert bullet_count <= 1

    def test_generate_passes_context_to_commitments(self, briefing_with_index):
        """Context dict passed through without error."""
        context = {"current_date": "2026-03-07", "keywords": ["python", "debug"]}
        result = briefing_with_index.generate(topic="python", context=context)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# get_top_memories()
# ---------------------------------------------------------------------------

class TestGetTopMemories:
    def test_empty_topic_returns_empty_list(self, briefing_with_index):
        result = briefing_with_index.get_top_memories(topic="")
        assert result == []

    def test_whitespace_topic_returns_empty_list(self, briefing_with_index):
        result = briefing_with_index.get_top_memories(topic="   ")
        assert result == []

    def test_missing_index_returns_empty_list(self, temp_dir):
        briefing = SessionBriefing(
            index_path=temp_dir / "nonexistent.json",
        )
        result = briefing.get_top_memories(topic="python")
        assert result == []

    def test_returns_list(self, briefing_with_index):
        result = briefing_with_index.get_top_memories(topic="search")
        assert isinstance(result, list)

    def test_filters_out_corrections(self, briefing_with_index):
        """Corrections must not appear in memory results."""
        result = briefing_with_index.get_top_memories(topic="sentence case headings")
        context_types = [m.get("context_type") for m in result]
        assert "correction" not in context_types

    def test_respects_top_k(self, index_with_memories, temp_dir):
        """Results must not exceed top_k."""
        briefing = SessionBriefing(index_path=index_with_memories)
        result = briefing.get_top_memories(topic="BM25 search keyword", top_k=1)
        assert len(result) <= 1

    def test_returns_dicts(self, briefing_with_index):
        result = briefing_with_index.get_top_memories(topic="BM25 search keyword")
        for item in result:
            assert isinstance(item, dict)
            assert "content" in item

    def test_empty_index_returns_empty(self, empty_index, temp_dir):
        briefing = SessionBriefing(index_path=empty_index)
        result = briefing.get_top_memories(topic="python")
        assert result == []


# ---------------------------------------------------------------------------
# get_active_corrections()
# ---------------------------------------------------------------------------

class TestGetActiveCorrections:
    def test_returns_list(self, briefing_with_index):
        result = briefing_with_index.get_active_corrections()
        assert isinstance(result, list)

    def test_empty_index_returns_empty(self, empty_index, temp_dir):
        briefing = SessionBriefing(index_path=empty_index)
        result = briefing.get_active_corrections()
        assert result == []

    def test_only_corrections_returned(self, briefing_with_index):
        result = briefing_with_index.get_active_corrections()
        for item in result:
            assert item.get("context_type") == "correction"

    def test_sorted_by_importance_descending(self, briefing_with_index):
        result = briefing_with_index.get_active_corrections()
        importances = [r.get("importance", 0.5) for r in result]
        assert importances == sorted(importances, reverse=True)

    def test_respects_limit(self, briefing_with_index):
        result = briefing_with_index.get_active_corrections(limit=1)
        assert len(result) <= 1

    def test_returns_dicts_with_content(self, briefing_with_index):
        result = briefing_with_index.get_active_corrections()
        for item in result:
            assert isinstance(item, dict)
            assert "content" in item

    def test_all_corrections_returned_within_limit(self, index_with_memories, temp_dir):
        """Index has 2 corrections; with limit=5, both should be returned."""
        briefing = SessionBriefing(index_path=index_with_memories)
        result = briefing.get_active_corrections(limit=5)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_open_commitments()
# ---------------------------------------------------------------------------

class TestGetOpenCommitments:
    def test_returns_list(self, briefing_with_index):
        result = briefing_with_index.get_open_commitments(context={})
        assert isinstance(result, list)

    def test_returns_empty_when_db_missing(self, index_with_memories, temp_dir):
        """Missing DB should return [] gracefully (not raise)."""
        briefing = SessionBriefing(
            db_path=temp_dir / "definitely_does_not_exist" / "missing.db",
            index_path=index_with_memories,
        )
        result = briefing.get_open_commitments(context={})
        assert result == []

    def test_handles_exception_gracefully(self, briefing_with_index):
        """Commitment retrieval errors should never bubble up."""
        with patch("memory_system.commitment_nudger.get_top_commitments", side_effect=RuntimeError("db error")):
            result = briefing_with_index.get_open_commitments(context={})
        assert result == []

    def test_no_commitments_when_empty_db(self, temp_dir, index_with_memories):
        """Fresh DB with no commitments → empty list."""
        briefing = SessionBriefing(
            db_path=temp_dir / "fresh.db",
            index_path=index_with_memories,
        )
        result = briefing.get_open_commitments(context={})
        assert isinstance(result, list)
        # Empty DB should yield no commitments
        assert result == []


# ---------------------------------------------------------------------------
# get_skill_recommendations()
# ---------------------------------------------------------------------------

class TestGetSkillRecommendations:
    def test_empty_topic_returns_empty(self, briefing_with_skills):
        result = briefing_with_skills.get_skill_recommendations(topic="")
        assert result == []

    def test_whitespace_topic_returns_empty(self, briefing_with_skills):
        result = briefing_with_skills.get_skill_recommendations(topic="   ")
        assert result == []

    def test_missing_skills_dir_returns_empty(self, temp_dir):
        briefing = SessionBriefing(skills_dir=temp_dir / "no-such-dir")
        result = briefing.get_skill_recommendations(topic="python")
        assert result == []

    def test_returns_list_of_strings(self, briefing_with_skills):
        result = briefing_with_skills.get_skill_recommendations(topic="python")
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    def test_name_keyword_match(self, briefing_with_skills):
        """'python' should match 'python-best-practices'."""
        result = briefing_with_skills.get_skill_recommendations(topic="python debugging")
        assert "python-best-practices" in result

    def test_when_to_use_boost(self, briefing_with_skills):
        """Topic overlapping with when-to-use section should score positively."""
        result = briefing_with_skills.get_skill_recommendations(topic="messaging brand copywriting")
        assert "messaging-framework" in result

    def test_respects_top_k(self, briefing_with_skills):
        result = briefing_with_skills.get_skill_recommendations(topic="python", top_k=1)
        assert len(result) <= 1

    def test_ignores_non_directories(self, briefing_with_skills):
        """Files in skills dir (not-a-skill.txt) should not appear in results."""
        result = briefing_with_skills.get_skill_recommendations(topic="skill txt")
        assert "not-a-skill.txt" not in result

    def test_no_match_returns_empty(self, briefing_with_skills):
        """Topic with no word overlap should return empty list."""
        result = briefing_with_skills.get_skill_recommendations(topic="xyzzy frobozz quux")
        assert result == []


# ---------------------------------------------------------------------------
# format_brief()
# ---------------------------------------------------------------------------

class TestFormatBrief:
    def test_all_empty_returns_empty_string(self, briefing_with_index):
        result = briefing_with_index.format_brief([], [], [], [])
        assert result == ""

    def test_corrections_only(self, briefing_with_index):
        corrections = [{"content": "Use sentence case always", "context_type": "correction", "importance": 0.9}]
        result = briefing_with_index.format_brief([], corrections, [], [])
        assert "Active corrections" in result
        assert "Use sentence case always" in result

    def test_memories_only(self, briefing_with_index):
        memories = [{"content": "BM25 scores by term frequency", "context_type": "knowledge", "importance": 0.7}]
        result = briefing_with_index.format_brief(memories, [], [], [])
        assert "Relevant memories" in result
        assert "BM25" in result

    def test_skills_only(self, briefing_with_index):
        result = briefing_with_index.format_brief([], [], [], ["python-best-practices", "messaging-framework"])
        assert "Recommended skills" in result
        assert "/python-best-practices" in result
        assert "/messaging-framework" in result

    def test_has_header_when_nonempty(self, briefing_with_index):
        corrections = [{"content": "Always sentence case", "context_type": "correction", "importance": 0.9}]
        result = briefing_with_index.format_brief([], corrections, [], [])
        assert result.startswith("# Session brief")

    def test_all_sections_present(self, briefing_with_index):
        memories = [{"content": "Memory content", "context_type": "knowledge", "importance": 0.7}]
        corrections = [{"content": "Correction text", "context_type": "correction", "importance": 0.9}]
        skills = ["python-best-practices"]
        result = briefing_with_index.format_brief(memories, corrections, [], skills)
        assert "Active corrections" in result
        assert "Relevant memories" in result
        assert "Recommended skills" in result

    def test_corrections_appear_before_memories(self, briefing_with_index):
        """Corrections should appear earlier in the brief than memories."""
        memories = [{"content": "Memory content", "context_type": "knowledge", "importance": 0.7}]
        corrections = [{"content": "Correction text", "context_type": "correction", "importance": 0.9}]
        result = briefing_with_index.format_brief(memories, corrections, [], [])
        corrections_idx = result.find("Active corrections")
        memories_idx = result.find("Relevant memories")
        assert corrections_idx < memories_idx

    def test_skills_appear_last(self, briefing_with_index):
        """Skills should be the last section."""
        memories = [{"content": "Memory", "context_type": "knowledge", "importance": 0.7}]
        corrections = [{"content": "Correction", "context_type": "correction", "importance": 0.9}]
        skills = ["my-skill"]
        result = briefing_with_index.format_brief(memories, corrections, [], skills)
        skills_idx = result.find("Recommended skills")
        assert skills_idx > result.find("Active corrections")
        assert skills_idx > result.find("Relevant memories")

    def test_long_content_truncated(self, briefing_with_index):
        """Content > 200 chars should be truncated in the output."""
        long_content = "x" * 300
        corrections = [{"content": long_content, "context_type": "correction", "importance": 0.9}]
        result = briefing_with_index.format_brief([], corrections, [], [])
        # The 300-char content should be truncated to ≤ 200 chars in the bullet
        lines = [l for l in result.split("\n") if l.startswith("- ")]
        if lines:
            assert len(lines[0]) <= 210  # "- " prefix + 200 chars + some tolerance

    def test_empty_content_item_skipped(self, briefing_with_index):
        """Memory with empty content should not add a blank bullet."""
        memories = [{"content": "", "context_type": "knowledge", "importance": 0.7}]
        result = briefing_with_index.format_brief(memories, [], [], [])
        # Section shouldn't appear at all if all items have empty content
        assert result == "" or "Relevant memories" not in result

    def test_corrections_with_empty_content_skipped(self, briefing_with_index):
        corrections = [{"content": "", "context_type": "correction", "importance": 0.9}]
        result = briefing_with_index.format_brief([], corrections, [], [])
        assert result == "" or "Active corrections" not in result


# ---------------------------------------------------------------------------
# is_empty()
# ---------------------------------------------------------------------------

class TestIsEmpty:
    def test_empty_string_is_empty(self, briefing_with_index):
        assert briefing_with_index.is_empty("") is True

    def test_whitespace_is_empty(self, briefing_with_index):
        assert briefing_with_index.is_empty("   \n\t  ") is True

    def test_none_is_empty(self, briefing_with_index):
        assert briefing_with_index.is_empty(None) is True

    def test_content_is_not_empty(self, briefing_with_index):
        assert briefing_with_index.is_empty("# Session brief\n\n## Corrections\n- some text") is False


# ---------------------------------------------------------------------------
# _summarize_trigger() helper
# ---------------------------------------------------------------------------

class TestSummarizeTrigger:
    def test_time_trigger(self):
        class FakeTrigger:
            trigger_type = "time"
            condition = {"after_date": "2026-03-15"}
        result = _summarize_trigger(FakeTrigger())
        assert "2026-03-15" in result

    def test_topic_trigger_with_keywords(self):
        class FakeTrigger:
            trigger_type = "topic"
            condition = {"keywords": ["python", "debugging"]}
        result = _summarize_trigger(FakeTrigger())
        assert "python" in result
        assert "debugging" in result

    def test_trigger_without_keywords(self):
        class FakeTrigger:
            trigger_type = "event"
            condition = {}
        result = _summarize_trigger(FakeTrigger())
        assert "event" in result

    def test_non_trigger_object_stringified(self):
        result = _summarize_trigger("some string commitment")
        assert "some string commitment" in result


# ---------------------------------------------------------------------------
# Anti-pattern alerts integration
# ---------------------------------------------------------------------------

class TestAntipatternAlerts:
    """Tests for get_antipattern_alerts() and _format_antipatterns_section()."""

    def setup_method(self, tmp_path_factory):
        pass

    def _make_report(self, skill_name, risk_level, rate=0.5, count=3):
        """Build a mock AntiPatternReport-like object."""
        class FakeReport:
            pass
        r = FakeReport()
        r.skill_name = skill_name
        r.risk_level = risk_level
        r.co_occurrence_rate = rate
        r.co_occurrence_count = count
        r.sample_corrections = ["correction A"]
        return r

    def test_get_antipattern_alerts_returns_list(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch("memory_system.session_briefing.SkillAntiPatternMiner") as MockMiner:
            MockMiner.return_value.analyze.return_value = []
            result = briefing.get_antipattern_alerts()
        assert isinstance(result, list)

    def test_returns_empty_when_no_high_risk(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch("memory_system.session_briefing.SkillAntiPatternMiner") as MockMiner:
            MockMiner.return_value.analyze.return_value = [
                self._make_report("low-skill", "low", rate=0.1),
            ]
            result = briefing.get_antipattern_alerts(min_risk="medium")
        assert result == []

    def test_returns_medium_and_high_by_default(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch("memory_system.session_briefing.SkillAntiPatternMiner") as MockMiner:
            MockMiner.return_value.analyze.return_value = [
                self._make_report("med-skill", "medium"),
                self._make_report("high-skill", "high"),
                self._make_report("low-skill", "low"),
            ]
            result = briefing.get_antipattern_alerts(min_risk="medium")
        names = [a["skill_name"] for a in result]
        assert "med-skill" in names
        assert "high-skill" in names
        assert "low-skill" not in names

    def test_respects_top_k_limit(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        reports = [self._make_report(f"skill-{i}", "high") for i in range(5)]
        with patch("memory_system.session_briefing.SkillAntiPatternMiner") as MockMiner:
            MockMiner.return_value.analyze.return_value = reports
            result = briefing.get_antipattern_alerts(top_k=2)
        assert len(result) <= 2

    def test_alert_dict_has_required_keys(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch("memory_system.session_briefing.SkillAntiPatternMiner") as MockMiner:
            MockMiner.return_value.analyze.return_value = [
                self._make_report("risky-skill", "high", rate=0.7),
            ]
            result = briefing.get_antipattern_alerts(min_risk="low")
        assert len(result) == 1
        alert = result[0]
        assert "skill_name" in alert
        assert "risk_level" in alert
        assert "co_occurrence_rate" in alert

    def test_returns_empty_list_on_exception(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch("memory_system.session_briefing.SkillAntiPatternMiner", side_effect=Exception("boom")):
            result = briefing.get_antipattern_alerts()
        assert result == []

    def test_format_antipatterns_section_renders_risk(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        alerts = [{"skill_name": "bad-skill", "risk_level": "high", "co_occurrence_rate": 0.75, "co_occurrence_count": 6}]
        result = briefing._format_antipatterns_section(alerts)
        assert "bad-skill" in result
        assert "high" in result
        assert "75%" in result

    def test_format_antipatterns_section_empty(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        assert briefing._format_antipatterns_section([]) == ""

    def test_format_brief_includes_antipatterns_section(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        alerts = [{"skill_name": "risky", "risk_level": "high", "co_occurrence_rate": 0.6, "co_occurrence_count": 3}]
        result = briefing.format_brief([], [], [], [], antipatterns=alerts)
        assert "Skill risk alerts" in result
        assert "risky" in result

    def test_generate_calls_get_antipattern_alerts(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch.object(briefing, "get_antipattern_alerts", return_value=[]) as mock_ap, \
             patch.object(briefing, "get_top_memories", return_value=[]), \
             patch.object(briefing, "get_active_corrections", return_value=[]), \
             patch.object(briefing, "get_open_commitments", return_value=[]), \
             patch.object(briefing, "get_skill_recommendations", return_value=[]):
            briefing.generate(topic="test")
        mock_ap.assert_called_once()


# ---------------------------------------------------------------------------
# Learning appearance recording (Phase 8)
# ---------------------------------------------------------------------------

class TestLearningAppearanceRecording:
    def test_generate_with_session_id_calls_record(self, tmp_path):
        """generate() calls _record_learning_appearances when session_id provided."""
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"id": "corr-001", "content": "Always check logs.", "importance": 0.9}]
        with patch.object(briefing, "get_active_corrections", return_value=corrections), \
             patch.object(briefing, "get_top_memories", return_value=[]), \
             patch.object(briefing, "get_open_commitments", return_value=[]), \
             patch.object(briefing, "get_skill_recommendations", return_value=[]), \
             patch.object(briefing, "get_antipattern_alerts", return_value=[]), \
             patch.object(briefing, "_record_learning_appearances") as mock_record:
            briefing.generate(topic="debugging", session_id="sess-abc")
        mock_record.assert_called_once()

    def test_generate_without_session_id_skips_record(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch.object(briefing, "get_active_corrections", return_value=[{"id": "c1", "content": "Note."}]), \
             patch.object(briefing, "get_top_memories", return_value=[]), \
             patch.object(briefing, "get_open_commitments", return_value=[]), \
             patch.object(briefing, "get_skill_recommendations", return_value=[]), \
             patch.object(briefing, "get_antipattern_alerts", return_value=[]), \
             patch.object(briefing, "_record_learning_appearances") as mock_record:
            briefing.generate(topic="debugging")  # no session_id
        mock_record.assert_not_called()

    def test_generate_with_empty_corrections_skips_record(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        with patch.object(briefing, "get_active_corrections", return_value=[]), \
             patch.object(briefing, "get_top_memories", return_value=[]), \
             patch.object(briefing, "get_open_commitments", return_value=[]), \
             patch.object(briefing, "get_skill_recommendations", return_value=[]), \
             patch.object(briefing, "get_antipattern_alerts", return_value=[]), \
             patch.object(briefing, "_record_learning_appearances") as mock_record:
            briefing.generate(topic="debugging", session_id="sess-abc")
        mock_record.assert_not_called()

    def test_record_learning_appearances_calls_promoter(self, tmp_path):
        """_record_learning_appearances writes appearances via LearningSkillPromoter."""
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"id": "corr-001", "content": "Check the logs first."}]
        with patch("memory_system.session_briefing.LearningSkillPromoter") as MockPromoter:
            mock_p = MockPromoter.return_value
            briefing._record_learning_appearances(corrections, ["debugging"], "sess-001")
        mock_p.record_appearance.assert_called_once()

    def test_record_uses_first_skill_as_skill_name(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"id": "corr-001", "content": "Note."}]
        with patch("memory_system.session_briefing.LearningSkillPromoter") as MockPromoter:
            mock_p = MockPromoter.return_value
            briefing._record_learning_appearances(corrections, ["my-skill", "other"], "sess-001")
        call_kwargs = mock_p.record_appearance.call_args
        assert call_kwargs.kwargs.get("skill_name") == "my-skill" or \
               (len(call_kwargs.args) > 1 and call_kwargs.args[1] == "my-skill")

    def test_record_uses_general_when_no_skills(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"id": "corr-001", "content": "Note."}]
        with patch("memory_system.session_briefing.LearningSkillPromoter") as MockPromoter:
            mock_p = MockPromoter.return_value
            briefing._record_learning_appearances(corrections, [], "sess-001")
        call_kwargs = mock_p.record_appearance.call_args
        # skill_name should be "general" when no skills available
        assert call_kwargs.kwargs.get("skill_name") == "general" or \
               (len(call_kwargs.args) > 1 and call_kwargs.args[1] == "general")

    def test_record_uses_content_hash_when_no_id(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"content": "No id field here."}]  # no 'id'
        with patch("memory_system.session_briefing.LearningSkillPromoter") as MockPromoter:
            mock_p = MockPromoter.return_value
            briefing._record_learning_appearances(corrections, ["debugging"], "sess-001")
        # Should still be called — falls back to hash
        mock_p.record_appearance.assert_called_once()

    def test_record_fails_silently_on_exception(self, tmp_path):
        briefing = SessionBriefing(db_path=str(tmp_path / "t.db"))
        corrections = [{"id": "corr-001", "content": "Note."}]
        with patch("memory_system.session_briefing.LearningSkillPromoter", side_effect=RuntimeError("db down")):
            # Should not raise
            briefing._record_learning_appearances(corrections, ["debugging"], "sess-001")
