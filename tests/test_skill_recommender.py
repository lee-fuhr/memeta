"""Tests for pull-based skill recommendation engine.

On-demand skill suggestions based on task description.
Distinct from the push-based hooks (which fire automatically):
this is queried explicitly by the user or conductor.

Sources: skill invocation history, task-type pattern matching,
and skill keyword overlap with the query.
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.skill_recommender import (
    SkillRecommender,
    Recommendation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_recommender(tmp_path, skills_dir=None):
    db_path = tmp_path / "intelligence.db"
    return SkillRecommender(db_path=db_path, skills_dir=skills_dir or tmp_path / "skills")


def _seed_provenance(db_path, skill_name, session_id, outcome="success", context=""):
    """Seed a skill_provenance row directly."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            session_id TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'unknown',
            context_snippet TEXT NOT NULL DEFAULT '',
            invoked_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "INSERT INTO skill_provenance (skill_name, session_id, outcome, context_snippet) VALUES (?,?,?,?)",
        (skill_name, session_id, outcome, context),
    )
    conn.commit()
    conn.close()


def _make_skill_dir(skills_dir: Path, skill_name: str, when_to_use: str = "") -> None:
    d = skills_dir / skill_name
    d.mkdir(parents=True, exist_ok=True)
    skill_md = d / "SKILL.md"
    content = f"# {skill_name}\n\n## When to use\n\n{when_to_use}\n"
    skill_md.write_text(content)


# ---------------------------------------------------------------------------
# Import + instantiation
# ---------------------------------------------------------------------------

class TestImport:
    def test_imports(self):
        from memory_system.skill_recommender import SkillRecommender
        assert SkillRecommender is not None

    def test_recommendation_importable(self):
        from memory_system.skill_recommender import Recommendation
        assert Recommendation is not None

    def test_instantiates(self, tmp_path):
        r = _make_recommender(tmp_path)
        assert r is not None


# ---------------------------------------------------------------------------
# recommend() — basic contract
# ---------------------------------------------------------------------------

class TestRecommendContract:
    def test_returns_list(self, tmp_path):
        r = _make_recommender(tmp_path)
        result = r.recommend("fix a bug")
        assert isinstance(result, list)

    def test_returns_recommendation_objects(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs or errors.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("fix a bug in the database")
        assert all(isinstance(x, Recommendation) for x in results)

    def test_empty_query_returns_empty(self, tmp_path):
        r = _make_recommender(tmp_path)
        assert r.recommend("") == []

    def test_whitespace_query_returns_empty(self, tmp_path):
        r = _make_recommender(tmp_path)
        assert r.recommend("   ") == []

    def test_returns_at_most_top_k(self, tmp_path):
        skills_dir = tmp_path / "skills"
        for name in ["debugging", "testing", "deployment", "review", "docs"]:
            _make_skill_dir(skills_dir, name, f"Use when working on {name}.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("debug test deploy", top_k=3)
        assert len(results) <= 3

    def test_recommendation_has_skill_name(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("fix a bug")
        if results:
            assert hasattr(results[0], "skill_name")
            assert isinstance(results[0].skill_name, str)

    def test_recommendation_has_score(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("fix a bug")
        if results:
            assert hasattr(results[0], "score")
            assert results[0].score >= 0

    def test_recommendation_has_reason(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("fix a bug")
        if results:
            assert hasattr(results[0], "reason")
            assert isinstance(results[0].reason, str)

    def test_sorted_by_score_descending(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use for debugging and bug fixing.")
        _make_skill_dir(skills_dir, "deployment", "Use for deploying to production.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("debug this bug")
        scores = [rec.score for rec in results]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Keyword matching source
# ---------------------------------------------------------------------------

class TestKeywordMatching:
    def test_matches_skill_name_words(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("debugging the database")
        names = [rec.skill_name for rec in results]
        assert "debugging" in names

    def test_matches_when_to_use_content(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "my-skill", "Use when you need to analyze performance metrics.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("analyze performance")
        names = [rec.skill_name for rec in results]
        assert "my-skill" in names

    def test_no_match_returns_empty(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "cooking-tips", "Use when preparing dinner recipes.")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("deploy kubernetes pod to production")
        assert results == [] or all(rec.skill_name != "cooking-tips" for rec in results)

    def test_missing_skills_dir_returns_empty(self, tmp_path):
        r = _make_recommender(tmp_path, tmp_path / "nonexistent")
        assert r.recommend("fix a bug") == []


# ---------------------------------------------------------------------------
# Usage history source (provenance boost)
# ---------------------------------------------------------------------------

class TestUsageHistoryBoost:
    def test_successful_past_use_boosts_score(self, tmp_path):
        db_path = tmp_path / "intelligence.db"
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs.")
        _seed_provenance(db_path, "debugging", "sess-001", outcome="success",
                         context="fix a bug in the login module")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("fix a bug")
        # debugging should appear and have a decent score
        names = [rec.skill_name for rec in results]
        assert "debugging" in names

    def test_failed_past_use_does_not_boost(self, tmp_path):
        db_path = tmp_path / "intelligence.db"
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "debugging", "Use when fixing bugs.")
        _make_skill_dir(skills_dir, "testing", "Use when writing or running tests.")
        _seed_provenance(db_path, "debugging", "sess-001", outcome="partial",
                         context="test the login module")
        _seed_provenance(db_path, "testing", "sess-002", outcome="success",
                         context="test the login module")
        r = _make_recommender(tmp_path, skills_dir)
        results = r.recommend("test the login module")
        # testing (success) should rank higher or equal to debugging (partial)
        if len(results) >= 2:
            testing_score = next((rec.score for rec in results if rec.skill_name == "testing"), 0)
            debugging_score = next((rec.score for rec in results if rec.skill_name == "debugging"), 0)
            assert testing_score >= debugging_score

    def test_usage_boost_requires_context_overlap(self, tmp_path):
        """History boost only applies when past context overlaps with current query."""
        db_path = tmp_path / "intelligence.db"
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "my-skill", "")
        # Seed with unrelated context
        _seed_provenance(db_path, "my-skill", "sess-001", outcome="success",
                         context="completely unrelated context about cooking")
        r = _make_recommender(tmp_path, skills_dir)
        # Query doesn't match either the skill name or past context
        results = r.recommend("deploy kubernetes pod")
        assert results == []


# ---------------------------------------------------------------------------
# format_recommendations
# ---------------------------------------------------------------------------

class TestFormatRecommendations:
    def test_formats_as_markdown(self, tmp_path):
        r = _make_recommender(tmp_path)
        recs = [
            Recommendation(skill_name="debugging", score=2.5, reason="keyword match: debug"),
            Recommendation(skill_name="testing", score=1.2, reason="past success"),
        ]
        text = r.format_recommendations(recs)
        assert "debugging" in text
        assert "testing" in text

    def test_empty_list_returns_empty_string(self, tmp_path):
        r = _make_recommender(tmp_path)
        assert r.format_recommendations([]) == ""

    def test_returns_string(self, tmp_path):
        r = _make_recommender(tmp_path)
        recs = [Recommendation(skill_name="debugging", score=1.0, reason="match")]
        result = r.format_recommendations(recs)
        assert isinstance(result, str)

    def test_includes_reason(self, tmp_path):
        r = _make_recommender(tmp_path)
        recs = [Recommendation(skill_name="debugging", score=1.0, reason="past success 3x")]
        text = r.format_recommendations(recs)
        assert "past success" in text or "3x" in text or "debugging" in text
