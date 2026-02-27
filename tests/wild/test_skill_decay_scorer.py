"""Tests for skill decay scorer — frequency-aware half-life decay for skill staleness."""

import pytest
import tempfile
import os
import sqlite3
import math
from datetime import datetime, timedelta

from memory_system.wild.skill_decay_scorer import SkillDecayScorer


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def scorer(temp_db):
    """Create SkillDecayScorer with temp database."""
    return SkillDecayScorer(db_path=temp_db)


def _insert_skill(db_path, skill_name, first_seen, last_used=None,
                   use_count=0, decay_score=0.0, flagged_for_review=0,
                   flag_dismissed_at=None):
    """Helper to insert a skill directly into the database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO skill_registry
           (skill_name, first_seen, last_used, use_count, decay_score,
            flagged_for_review, flag_dismissed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (skill_name, first_seen, last_used, use_count, decay_score,
         flagged_for_review, flag_dismissed_at),
    )
    conn.commit()
    conn.close()


def _get_skill(db_path, skill_name):
    """Helper to read a skill row from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM skill_registry WHERE skill_name = ?",
        (skill_name,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── adjusted_half_life (static) ────────────────────────────────────────────

class TestAdjustedHalfLife:
    """Tests for the static adjusted_half_life formula."""

    def test_use_count_1_gives_30_days(self):
        """use_count=1 -> 30 * (1 + log2(1)) = 30 * 1 = 30."""
        assert SkillDecayScorer.adjusted_half_life(1) == 30.0

    def test_use_count_8_gives_120_days(self):
        """use_count=8 -> 30 * (1 + log2(8)) = 30 * 4 = 120."""
        assert SkillDecayScorer.adjusted_half_life(8) == 120.0

    def test_use_count_0_gives_30_days(self):
        """use_count=0 -> max(1,0)=1, log2(1)=0, 30 * 1 = 30."""
        assert SkillDecayScorer.adjusted_half_life(0) == 30.0

    def test_use_count_2_gives_60_days(self):
        """use_count=2 -> 30 * (1 + log2(2)) = 30 * 2 = 60."""
        assert SkillDecayScorer.adjusted_half_life(2) == 60.0

    def test_use_count_4_gives_90_days(self):
        """use_count=4 -> 30 * (1 + log2(4)) = 30 * 3 = 90."""
        assert SkillDecayScorer.adjusted_half_life(4) == 90.0

    def test_high_use_count_extends_halflife(self):
        """Higher use_count always produces longer half-life."""
        h1 = SkillDecayScorer.adjusted_half_life(1)
        h10 = SkillDecayScorer.adjusted_half_life(10)
        h100 = SkillDecayScorer.adjusted_half_life(100)
        assert h1 < h10 < h100


# ─── decay_score (static) ───────────────────────────────────────────────────

class TestDecayScore:
    """Tests for the static decay_score formula."""

    def test_zero_days_returns_zero(self):
        """At 0 days since last use, decay = 0.0 (just used)."""
        assert SkillDecayScorer.decay_score(0.0, 30.0) == 0.0

    def test_at_half_life_returns_0_5(self):
        """At exactly half_life days, decay = 0.5."""
        result = SkillDecayScorer.decay_score(30.0, 30.0)
        assert abs(result - 0.5) < 1e-9

    def test_at_two_half_lives_returns_0_75(self):
        """At 2*half_life, decay = 0.75."""
        result = SkillDecayScorer.decay_score(60.0, 30.0)
        assert abs(result - 0.75) < 1e-9

    def test_large_days_approaches_one(self):
        """At very large days, decay approaches 1.0 but never exceeds it."""
        result = SkillDecayScorer.decay_score(10000.0, 30.0)
        assert result > 0.99
        assert result <= 1.0

    def test_negative_days_returns_negative(self):
        """Negative days (future use) produces negative decay (edge case)."""
        result = SkillDecayScorer.decay_score(-5.0, 30.0)
        assert result < 0.0


# ─── compute_decay ──────────────────────────────────────────────────────────

class TestComputeDecay:
    """Tests for compute_decay with actual database skills."""

    def test_never_used_skill_returns_zero(self, scorer, temp_db):
        """Skill with last_used=NULL returns decay 0.0."""
        _insert_skill(temp_db, "unused-skill",
                       first_seen="2026-01-01T00:00:00",
                       last_used=None, use_count=0)
        assert scorer.compute_decay("unused-skill") == 0.0

    def test_recently_used_skill_has_low_decay(self, scorer, temp_db):
        """Skill used 1 day ago has low decay."""
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        _insert_skill(temp_db, "recent-skill",
                       first_seen="2026-01-01T00:00:00",
                       last_used=yesterday, use_count=5)
        decay = scorer.compute_decay("recent-skill")
        assert 0.0 < decay < 0.1

    def test_long_unused_skill_has_high_decay(self, scorer, temp_db):
        """Skill unused for 200 days has high decay."""
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        _insert_skill(temp_db, "stale-skill",
                       first_seen="2026-01-01T00:00:00",
                       last_used=long_ago, use_count=1)
        decay = scorer.compute_decay("stale-skill")
        assert decay > 0.9

    def test_high_use_count_slows_decay(self, scorer, temp_db):
        """Skill with high use_count decays slower than low use_count."""
        sixty_days_ago = (datetime.now() - timedelta(days=60)).isoformat()
        _insert_skill(temp_db, "low-use",
                       first_seen="2026-01-01T00:00:00",
                       last_used=sixty_days_ago, use_count=1)
        _insert_skill(temp_db, "high-use",
                       first_seen="2026-01-01T00:00:00",
                       last_used=sixty_days_ago, use_count=64)
        decay_low = scorer.compute_decay("low-use")
        decay_high = scorer.compute_decay("high-use")
        assert decay_low > decay_high

    def test_as_of_parameter_fixes_time(self, scorer, temp_db):
        """as_of parameter controls the reference time for decay calculation."""
        _insert_skill(temp_db, "test-skill",
                       first_seen="2026-01-01T00:00:00",
                       last_used="2026-01-15T00:00:00", use_count=1)
        # as_of = exactly half-life later (30 days after last_used)
        as_of = datetime(2026, 2, 14, 0, 0, 0)
        decay = scorer.compute_decay("test-skill", as_of=as_of)
        assert abs(decay - 0.5) < 1e-6

    def test_unknown_skill_returns_zero(self, scorer):
        """Unknown skill name returns 0.0 decay."""
        assert scorer.compute_decay("nonexistent-skill") == 0.0


# ─── compute_all_decay_scores ───────────────────────────────────────────────

class TestComputeAllDecayScores:
    """Tests for compute_all_decay_scores batch operation."""

    def test_empty_registry_returns_empty(self, scorer):
        """Empty skill registry returns empty list."""
        result = scorer.compute_all_decay_scores()
        assert result == []

    def test_returns_correct_structure(self, scorer, temp_db):
        """Each result dict contains expected keys."""
        _insert_skill(temp_db, "skill-a",
                       first_seen="2026-01-01T00:00:00",
                       last_used="2026-01-15T00:00:00", use_count=3)
        results = scorer.compute_all_decay_scores()
        assert len(results) == 1
        result = results[0]
        assert "skill_name" in result
        assert "use_count" in result
        assert "last_used" in result
        assert "decay_score" in result
        assert "flagged" in result

    def test_updates_database_decay_scores(self, scorer, temp_db):
        """compute_all_decay_scores writes decay_score back to the database."""
        long_ago = (datetime.now() - timedelta(days=100)).isoformat()
        _insert_skill(temp_db, "aging-skill",
                       first_seen="2026-01-01T00:00:00",
                       last_used=long_ago, use_count=1)
        scorer.compute_all_decay_scores()
        skill = _get_skill(temp_db, "aging-skill")
        assert skill["decay_score"] > 0.0

    def test_processes_all_skills(self, scorer, temp_db):
        """All skills in registry are processed."""
        for i in range(5):
            _insert_skill(temp_db, f"skill-{i}",
                           first_seen="2026-01-01T00:00:00",
                           last_used="2026-01-15T00:00:00", use_count=i + 1)
        results = scorer.compute_all_decay_scores()
        assert len(results) == 5


# ─── flag_for_review ────────────────────────────────────────────────────────

class TestFlagForReview:
    """Tests for flag_for_review thresholding and rules."""

    def test_flags_high_decay_skill(self, scorer, temp_db):
        """Skill with decay >= 0.8 is flagged for review."""
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        old_first_seen = (datetime.now() - timedelta(days=300)).isoformat()
        _insert_skill(temp_db, "stale-skill",
                       first_seen=old_first_seen,
                       last_used=long_ago, use_count=1)
        flagged = scorer.flag_for_review(threshold=0.8)
        assert len(flagged) == 1
        assert flagged[0]["skill_name"] == "stale-skill"

    def test_skips_skill_within_grace_period(self, scorer, temp_db):
        """Skill first_seen within grace_period_days is not flagged."""
        recent = (datetime.now() - timedelta(days=5)).isoformat()
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        _insert_skill(temp_db, "new-skill",
                       first_seen=recent,
                       last_used=long_ago, use_count=1)
        flagged = scorer.flag_for_review(threshold=0.0, grace_period_days=14)
        assert len(flagged) == 0

    def test_skips_recently_dismissed_flag(self, scorer, temp_db):
        """Skill with flag_dismissed_at within 30 days is not re-flagged."""
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        old_first_seen = (datetime.now() - timedelta(days=300)).isoformat()
        recently_dismissed = (datetime.now() - timedelta(days=10)).isoformat()
        _insert_skill(temp_db, "dismissed-skill",
                       first_seen=old_first_seen,
                       last_used=long_ago, use_count=1,
                       flag_dismissed_at=recently_dismissed)
        flagged = scorer.flag_for_review(threshold=0.8)
        assert len(flagged) == 0

    def test_allows_reflag_after_dismiss_cooldown(self, scorer, temp_db):
        """Skill dismissed > 30 days ago can be re-flagged."""
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        old_first_seen = (datetime.now() - timedelta(days=300)).isoformat()
        old_dismiss = (datetime.now() - timedelta(days=45)).isoformat()
        _insert_skill(temp_db, "reflag-skill",
                       first_seen=old_first_seen,
                       last_used=long_ago, use_count=1,
                       flag_dismissed_at=old_dismiss)
        flagged = scorer.flag_for_review(threshold=0.8)
        assert len(flagged) == 1

    def test_sets_flagged_for_review_in_db(self, scorer, temp_db):
        """Flag sets flagged_for_review = 1 in the database."""
        long_ago = (datetime.now() - timedelta(days=200)).isoformat()
        old_first_seen = (datetime.now() - timedelta(days=300)).isoformat()
        _insert_skill(temp_db, "flag-me",
                       first_seen=old_first_seen,
                       last_used=long_ago, use_count=1)
        scorer.flag_for_review(threshold=0.8)
        skill = _get_skill(temp_db, "flag-me")
        assert skill["flagged_for_review"] == 1

    def test_does_not_flag_low_decay_skill(self, scorer, temp_db):
        """Skill with decay below threshold is not flagged."""
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        old_first_seen = (datetime.now() - timedelta(days=100)).isoformat()
        _insert_skill(temp_db, "fresh-skill",
                       first_seen=old_first_seen,
                       last_used=yesterday, use_count=10)
        flagged = scorer.flag_for_review(threshold=0.8)
        assert len(flagged) == 0


# ─── dismiss_flag ───────────────────────────────────────────────────────────

class TestDismissFlag:
    """Tests for dismiss_flag."""

    def test_dismiss_sets_flag_to_zero(self, scorer, temp_db):
        """Dismissing clears flagged_for_review and sets flag_dismissed_at."""
        old_first_seen = (datetime.now() - timedelta(days=100)).isoformat()
        _insert_skill(temp_db, "flagged-skill",
                       first_seen=old_first_seen,
                       last_used="2026-01-01T00:00:00", use_count=1,
                       flagged_for_review=1)
        result = scorer.dismiss_flag("flagged-skill")
        assert result is True
        skill = _get_skill(temp_db, "flagged-skill")
        assert skill["flagged_for_review"] == 0
        assert skill["flag_dismissed_at"] is not None

    def test_dismiss_unknown_skill_returns_false(self, scorer):
        """Dismissing a nonexistent skill returns False."""
        result = scorer.dismiss_flag("no-such-skill")
        assert result is False


# ─── get_flagged_skills ─────────────────────────────────────────────────────

class TestGetFlaggedSkills:
    """Tests for get_flagged_skills."""

    def test_returns_flagged_skills_only(self, scorer, temp_db):
        """Only skills with flagged_for_review=1 are returned."""
        old = (datetime.now() - timedelta(days=100)).isoformat()
        _insert_skill(temp_db, "flagged-one", first_seen=old,
                       last_used=old, use_count=1, flagged_for_review=1)
        _insert_skill(temp_db, "not-flagged", first_seen=old,
                       last_used=old, use_count=1, flagged_for_review=0)
        _insert_skill(temp_db, "flagged-two", first_seen=old,
                       last_used=old, use_count=1, flagged_for_review=1)
        result = scorer.get_flagged_skills()
        names = [r["skill_name"] for r in result]
        assert sorted(names) == ["flagged-one", "flagged-two"]

    def test_returns_empty_when_none_flagged(self, scorer, temp_db):
        """Returns empty list when no skills are flagged."""
        old = (datetime.now() - timedelta(days=100)).isoformat()
        _insert_skill(temp_db, "clean-skill", first_seen=old,
                       last_used=old, use_count=1, flagged_for_review=0)
        result = scorer.get_flagged_skills()
        assert result == []

    def test_returns_empty_for_empty_registry(self, scorer):
        """Returns empty list when registry is empty."""
        result = scorer.get_flagged_skills()
        assert result == []
