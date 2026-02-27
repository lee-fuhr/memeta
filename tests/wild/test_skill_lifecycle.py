"""Tests for skill lifecycle manager — facade orchestrating all skill sub-modules."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from memory_system.wild.skill_lifecycle import SkillLifecycleManager


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def temp_state(tmp_path):
    """Create temporary state file path."""
    return tmp_path / "action-patterns.json"


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with one skill."""
    skills = tmp_path / "skills"
    skills.mkdir()
    skill_dir = skills / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "# Test skill\n\n"
        "A skill for testing purposes.\n\n"
        "## Triggers\n\n"
        "- testing\n"
        "- verification\n"
    )
    return skills


@pytest.fixture
def manager(temp_db, temp_state, skills_dir):
    """Create a SkillLifecycleManager with temp paths."""
    return SkillLifecycleManager(
        db_path=temp_db,
        state_path=temp_state,
        skills_dir=skills_dir,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _insert_skill(manager, name, use_count=0, last_used=None, decay_score=0.0):
    """Insert a skill directly into the registry."""
    now = datetime.now().isoformat()
    manager.db.conn.execute(
        "INSERT INTO skill_registry "
        "(skill_name, skill_path, description, keywords, first_seen, last_used, use_count, decay_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, f"/skills/{name}", f"Desc for {name}", "[]", now, last_used, use_count, decay_score),
    )
    manager.db.conn.commit()


def _seed_daily_burst(manager, action, count=3):
    """Record the same action multiple times today."""
    for i in range(count):
        manager.tracker.record_action(action, session_id=f"s{i}")


def _seed_sustained_pattern(manager, action, days=7):
    """Seed a pattern appearing on multiple distinct days."""
    state = manager.tracker._load_state()
    hash_id = manager.tracker._generate_pattern_hash(action)
    daily = {}
    for d in range(days):
        date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        daily[date] = 1
    state["action_patterns"][hash_id] = {
        "id": hash_id,
        "action_signature": action,
        "canonical_form": manager.tracker._generate_canonical_form(action),
        "first_seen": (datetime.now() - timedelta(days=days)).isoformat(),
        "last_seen": datetime.now().isoformat(),
        "frequency": days,
        "daily_occurrences": daily,
        "session_ids": [f"s{i}" for i in range(days)],
        "mapped_skill": None,
        "proposed_skill": None,
    }
    manager.tracker._save_state(state)


# ── 1. Initialization ───────────────────────────────────────────────────────


class TestInitialization:
    """Tests for SkillLifecycleManager construction."""

    def test_creates_with_custom_paths(self, temp_db, temp_state, skills_dir):
        """Manager initializes with explicitly provided paths."""
        mgr = SkillLifecycleManager(
            db_path=temp_db, state_path=temp_state, skills_dir=skills_dir
        )
        assert mgr.db is not None
        assert mgr.scanner is not None
        assert mgr.decay_scorer is not None
        assert mgr.proposal_engine is not None
        assert mgr.tracker is not None

    def test_creates_with_defaults(self, temp_db):
        """Manager initializes when only db_path is provided, using config defaults."""
        mgr = SkillLifecycleManager(db_path=temp_db)
        assert mgr.db is not None

    def test_sub_modules_share_database(self, manager):
        """All sub-modules should share the same db_path."""
        # They each create their own IntelligenceDB but point to the same file
        assert str(manager.scanner.db.db_path) == str(manager.db.db_path)
        assert str(manager.decay_scorer.db.db_path) == str(manager.db.db_path)
        assert str(manager.proposal_engine.db.db_path) == str(manager.db.db_path)


# ── 2. run_daily_maintenance ─────────────────────────────────────────────────


class TestRunDailyMaintenance:
    """Tests for the full daily lifecycle pipeline."""

    def test_returns_correct_summary_shape(self, manager):
        """Return value has all required keys with correct types."""
        result = manager.run_daily_maintenance()
        assert "skills_synced" in result
        assert "decay_scores_updated" in result
        assert "newly_flagged" in result
        assert "new_proposals" in result
        assert isinstance(result["skills_synced"], dict)
        assert isinstance(result["decay_scores_updated"], int)
        assert isinstance(result["newly_flagged"], list)
        assert isinstance(result["new_proposals"], list)

    def test_scanner_syncs_skills_from_filesystem(self, manager):
        """Scanner discovers skills from the skills directory."""
        result = manager.run_daily_maintenance()
        assert result["skills_synced"]["new"] >= 1
        assert result["skills_synced"]["total"] >= 1

    def test_decay_scores_updated_for_all_skills(self, manager):
        """Decay scores are computed for all skills in registry."""
        # First sync to populate registry
        manager.scanner.sync_to_db()
        result = manager.run_daily_maintenance()
        assert result["decay_scores_updated"] >= 1

    def test_proposals_created_when_patterns_exist(self, manager):
        """When qualifying patterns exist, proposals are generated and persisted."""
        _seed_daily_burst(manager, "deploy website changes", count=4)
        result = manager.run_daily_maintenance()
        assert len(result["new_proposals"]) >= 1

    def test_handles_empty_state_gracefully(self, temp_db, tmp_path):
        """Works cleanly with no skills dir, no patterns, empty DB."""
        empty_skills = tmp_path / "empty_skills"
        empty_skills.mkdir()
        state = tmp_path / "state.json"
        mgr = SkillLifecycleManager(
            db_path=temp_db, state_path=state, skills_dir=empty_skills
        )
        result = mgr.run_daily_maintenance()
        assert result["skills_synced"]["new"] == 0
        assert result["decay_scores_updated"] == 0
        assert result["newly_flagged"] == []
        assert result["new_proposals"] == []

    def test_flagged_skills_included_in_result(self, manager):
        """Skills exceeding decay threshold appear in newly_flagged."""
        # Insert a skill with very old first_seen and last_used so decay > 0.8
        # half_life for use_count=1 is 30*(1+log2(1))=30 days
        # At 90 days: decay = 1 - 0.5^(90/30) = 1 - 0.125 = 0.875 > 0.8
        old_date = (datetime.now() - timedelta(days=90)).isoformat()
        manager.db.conn.execute(
            "INSERT INTO skill_registry "
            "(skill_name, skill_path, description, keywords, first_seen, last_used, use_count, decay_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("stale-skill", "/path", "old", "[]", old_date, old_date, 1, 0.0),
        )
        manager.db.conn.commit()
        result = manager.run_daily_maintenance()
        flagged_names = [f["skill_name"] for f in result["newly_flagged"]]
        assert "stale-skill" in flagged_names


# ── 3. record_skill_usage ────────────────────────────────────────────────────


class TestRecordSkillUsage:
    """Tests for recording a skill usage event."""

    def test_inserts_usage_event(self, manager):
        """Usage event is inserted into skill_usage_events table."""
        _insert_skill(manager, "copywriting")
        manager.record_skill_usage("copywriting", session_id="sess-1")
        rows = manager.db.conn.execute(
            "SELECT * FROM skill_usage_events WHERE skill_name = 'copywriting'"
        ).fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["session_id"] == "sess-1"

    def test_increments_use_count(self, manager):
        """use_count in skill_registry is incremented."""
        _insert_skill(manager, "copywriting", use_count=5)
        manager.record_skill_usage("copywriting")
        row = manager.db.conn.execute(
            "SELECT use_count FROM skill_registry WHERE skill_name = 'copywriting'"
        ).fetchone()
        assert row["use_count"] == 6

    def test_updates_last_used(self, manager):
        """last_used in skill_registry is set to current timestamp."""
        _insert_skill(manager, "copywriting", last_used=None)
        manager.record_skill_usage("copywriting")
        row = manager.db.conn.execute(
            "SELECT last_used FROM skill_registry WHERE skill_name = 'copywriting'"
        ).fetchone()
        assert row["last_used"] is not None

    def test_handles_unknown_skill_gracefully(self, manager):
        """Recording usage for a skill not in registry does not crash."""
        # Should not raise; event still gets logged
        manager.record_skill_usage("nonexistent-skill", session_id="s1")
        rows = manager.db.conn.execute(
            "SELECT * FROM skill_usage_events WHERE skill_name = 'nonexistent-skill'"
        ).fetchall()
        assert len(rows) == 1


# ── 4. get_lifecycle_summary ─────────────────────────────────────────────────


class TestGetLifecycleSummary:
    """Tests for the comprehensive lifecycle summary."""

    def test_returns_correct_shape(self, manager):
        """Summary dict has all required keys."""
        summary = manager.get_lifecycle_summary()
        assert "proposals" in summary
        assert "pending" in summary["proposals"]
        assert "total_pending" in summary["proposals"]
        assert "flagged_skills" in summary
        assert "decay_scores" in summary
        assert "action_patterns" in summary
        assert "total" in summary["action_patterns"]
        assert "recent" in summary["action_patterns"]
        assert "registry" in summary
        assert "total_skills" in summary["registry"]

    def test_includes_pending_proposals(self, manager):
        """Summary includes pending proposals when they exist."""
        from memory_system.wild.skill_proposal_engine import SkillProposal

        p = SkillProposal(
            proposed_name="auto-test",
            action_signature="test action",
            trigger_reason="daily_burst",
            confidence=0.6,
        )
        manager.proposal_engine.create_proposal(p)
        summary = manager.get_lifecycle_summary()
        assert summary["proposals"]["total_pending"] == 1
        assert len(summary["proposals"]["pending"]) == 1

    def test_includes_flagged_skills(self, manager):
        """Summary includes flagged skills."""
        _insert_skill(manager, "old-skill")
        manager.db.conn.execute(
            "UPDATE skill_registry SET flagged_for_review = 1 WHERE skill_name = 'old-skill'"
        )
        manager.db.conn.commit()
        summary = manager.get_lifecycle_summary()
        flagged_names = [s["skill_name"] for s in summary["flagged_skills"]]
        assert "old-skill" in flagged_names

    def test_handles_empty_db(self, manager):
        """Summary works cleanly with empty database."""
        summary = manager.get_lifecycle_summary()
        assert summary["proposals"]["total_pending"] == 0
        assert summary["flagged_skills"] == []
        assert summary["decay_scores"] == []
        assert summary["action_patterns"]["total"] == 0
        assert summary["registry"]["total_skills"] == 0


# ── 5. Delegation methods ───────────────────────────────────────────────────


class TestGetProposals:
    """Tests for get_proposals delegation."""

    def test_returns_pending_by_default(self, manager):
        """get_proposals('pending') delegates to proposal engine."""
        from memory_system.wild.skill_proposal_engine import SkillProposal

        p = SkillProposal(
            proposed_name="auto-test",
            action_signature="test",
            trigger_reason="daily_burst",
            confidence=0.6,
        )
        manager.proposal_engine.create_proposal(p)
        proposals = manager.get_proposals()
        assert len(proposals) == 1
        assert proposals[0]["proposed_name"] == "auto-test"

    def test_filters_by_status(self, manager):
        """get_proposals with a different status filters correctly."""
        from memory_system.wild.skill_proposal_engine import SkillProposal

        p = SkillProposal(
            proposed_name="auto-test",
            action_signature="test",
            trigger_reason="daily_burst",
            confidence=0.6,
        )
        pid = manager.proposal_engine.create_proposal(p)
        manager.proposal_engine.update_proposal_status(pid, "approved")
        # No pending proposals remain
        assert manager.get_proposals("pending") == []


class TestUpdateProposal:
    """Tests for update_proposal delegation."""

    def test_updates_status_via_facade(self, manager):
        """update_proposal delegates to proposal engine's update_proposal_status."""
        from memory_system.wild.skill_proposal_engine import SkillProposal

        p = SkillProposal(
            proposed_name="auto-test",
            action_signature="test",
            trigger_reason="daily_burst",
            confidence=0.6,
        )
        pid = manager.proposal_engine.create_proposal(p)
        result = manager.update_proposal(pid, "approved")
        assert result is True
        stored = manager.proposal_engine.get_proposal(pid)
        assert stored["status"] == "approved"

    def test_returns_false_for_unknown_id(self, manager):
        """update_proposal returns False for non-existent proposal."""
        result = manager.update_proposal(9999, "approved")
        assert result is False


class TestGetFlaggedSkills:
    """Tests for get_flagged_skills delegation."""

    def test_returns_flagged_from_db(self, manager):
        """get_flagged_skills delegates to decay scorer."""
        _insert_skill(manager, "flagged-one")
        manager.db.conn.execute(
            "UPDATE skill_registry SET flagged_for_review = 1 WHERE skill_name = 'flagged-one'"
        )
        manager.db.conn.commit()
        flagged = manager.get_flagged_skills()
        assert len(flagged) == 1
        assert flagged[0]["skill_name"] == "flagged-one"


class TestDismissFlag:
    """Tests for dismiss_flag delegation."""

    def test_dismisses_flag_via_facade(self, manager):
        """dismiss_flag delegates to decay scorer's dismiss_flag."""
        _insert_skill(manager, "stale-skill")
        manager.db.conn.execute(
            "UPDATE skill_registry SET flagged_for_review = 1 WHERE skill_name = 'stale-skill'"
        )
        manager.db.conn.commit()
        result = manager.dismiss_flag("stale-skill")
        assert result is True
        flagged = manager.get_flagged_skills()
        assert len(flagged) == 0

    def test_returns_false_for_unknown_skill(self, manager):
        """dismiss_flag returns False for a non-existent skill."""
        result = manager.dismiss_flag("nonexistent-skill")
        assert result is False


class TestGetDecayScores:
    """Tests for get_decay_scores delegation."""

    def test_returns_scores_for_all_skills(self, manager):
        """get_decay_scores returns list of dicts for all registered skills."""
        _insert_skill(manager, "skill-a", use_count=2, last_used=datetime.now().isoformat())
        _insert_skill(manager, "skill-b", use_count=0)
        scores = manager.get_decay_scores()
        assert len(scores) == 2
        names = {s["skill_name"] for s in scores}
        assert names == {"skill-a", "skill-b"}


class TestGetActionPatterns:
    """Tests for get_action_patterns delegation."""

    def test_returns_patterns_as_dicts(self, manager):
        """get_action_patterns converts ActionPatterns to dicts."""
        manager.tracker.record_action("test action one", session_id="s1")
        patterns = manager.get_action_patterns()
        assert len(patterns) == 1
        assert isinstance(patterns[0], dict)
        assert "action_signature" in patterns[0]

    def test_respects_min_frequency(self, manager):
        """get_action_patterns filters by min_frequency."""
        manager.tracker.record_action("rare action", session_id="s1")
        manager.tracker.record_action("common action", session_id="s1")
        manager.tracker.record_action("common action", session_id="s2")
        manager.tracker.record_action("common action", session_id="s3")
        patterns = manager.get_action_patterns(min_frequency=3)
        assert len(patterns) == 1
        assert patterns[0]["action_signature"] == "common action"


# ── 6. Error handling ────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for graceful error handling."""

    def test_missing_skills_dir_does_not_crash(self, temp_db, tmp_path):
        """Manager handles a non-existent skills directory gracefully."""
        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=tmp_path / "state.json",
            skills_dir=tmp_path / "no_such_dir",
        )
        result = mgr.run_daily_maintenance()
        assert result["skills_synced"]["new"] == 0

    def test_corrupted_state_file_does_not_crash(self, temp_db, tmp_path, skills_dir):
        """Manager handles a corrupted state file gracefully."""
        state_path = tmp_path / "bad-state.json"
        state_path.write_text("{invalid json!!!}")
        # The tracker should handle the corrupted file
        # The facade should catch any errors from sub-modules
        mgr = SkillLifecycleManager(
            db_path=temp_db, state_path=state_path, skills_dir=skills_dir
        )
        result = mgr.run_daily_maintenance()
        # Should complete without raising
        assert isinstance(result, dict)

    def test_empty_db_lifecycle_summary(self, temp_db, tmp_path, skills_dir):
        """Lifecycle summary works with a completely empty DB."""
        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=tmp_path / "state.json",
            skills_dir=skills_dir,
        )
        summary = mgr.get_lifecycle_summary()
        assert isinstance(summary, dict)
        assert summary["registry"]["total_skills"] == 0
