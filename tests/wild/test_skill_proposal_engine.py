"""Tests for skill proposal engine — analyzes action patterns to propose new skills."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta

from memory_system.wild.skill_proposal_engine import SkillProposalEngine, SkillProposal


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def temp_state(tmp_path):
    """Create temporary state file path."""
    return tmp_path / "action-patterns.json"


@pytest.fixture
def engine(temp_db, temp_state):
    """Create SkillProposalEngine with temp database and state file."""
    return SkillProposalEngine(db_path=temp_db, state_path=temp_state)


# --- Helpers ---

def _seed_daily_burst(engine, action, count=3):
    """Record the same action multiple times today."""
    for i in range(count):
        engine.tracker.record_action(action, session_id=f"s{i}")


def _seed_sustained_pattern(engine, action, days=7):
    """Seed a pattern appearing on multiple distinct days."""
    state = engine.tracker._load_state()
    hash_id = engine.tracker._generate_pattern_hash(action)
    daily = {}
    for d in range(days):
        date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        daily[date] = 1
    state["action_patterns"][hash_id] = {
        "id": hash_id,
        "action_signature": action,
        "canonical_form": engine.tracker._generate_canonical_form(action),
        "first_seen": (datetime.now() - timedelta(days=days)).isoformat(),
        "last_seen": datetime.now().isoformat(),
        "frequency": days,
        "daily_occurrences": daily,
        "session_ids": [f"s{i}" for i in range(days)],
        "mapped_skill": None,
        "proposed_skill": None,
    }
    engine.tracker._save_state(state)


def _add_skill_to_registry(engine, skill_name, keywords):
    """Insert a skill into the skill_registry table."""
    keywords_json = json.dumps(keywords)
    engine.db.conn.execute(
        "INSERT INTO skill_registry (skill_name, keywords, first_seen) VALUES (?, ?, ?)",
        (skill_name, keywords_json, datetime.now().isoformat()),
    )
    engine.db.conn.commit()


# --- keyword_overlap ---

class TestKeywordOverlap:
    """Tests for keyword_overlap computation."""

    def test_identical_words_returns_one(self, engine):
        """Identical word sets yield Jaccard coefficient of 1.0."""
        result = engine.keyword_overlap("create google doc", ["create", "google", "doc"])
        assert result == 1.0

    def test_no_overlap_returns_zero(self, engine):
        """Completely disjoint word sets yield 0.0."""
        result = engine.keyword_overlap("apple banana cherry", ["dog", "elephant", "frog"])
        assert result == 0.0

    def test_partial_overlap_returns_intermediate(self, engine):
        """Partial overlap yields a value between 0 and 1."""
        result = engine.keyword_overlap("create google doc", ["create", "notion", "page"])
        assert 0.0 < result < 1.0

    def test_empty_action_empty_keywords_returns_zero(self, engine):
        """Both empty inputs yield 0.0."""
        result = engine.keyword_overlap("", [])
        assert result == 0.0

    def test_case_insensitive(self, engine):
        """Comparison is case-insensitive."""
        result = engine.keyword_overlap("Create Google Doc", ["create", "google", "doc"])
        assert result == 1.0

    def test_empty_action_nonempty_keywords_returns_zero(self, engine):
        """Empty action with non-empty keywords yields 0.0."""
        result = engine.keyword_overlap("", ["create", "doc"])
        assert result == 0.0

    def test_nonempty_action_empty_keywords_returns_zero(self, engine):
        """Non-empty action with empty keywords yields 0.0."""
        result = engine.keyword_overlap("create doc", [])
        assert result == 0.0


# --- check_existing_coverage ---

class TestCheckExistingCoverage:
    """Tests for checking whether an existing skill covers an action."""

    def test_no_skills_in_registry_returns_false(self, engine):
        """When no skills exist, nothing can cover the action."""
        is_covered, skill_name = engine.check_existing_coverage("create google doc")
        assert is_covered is False
        assert skill_name is None

    def test_skill_with_high_overlap_returns_covered(self, engine):
        """Skill with overlap > 0.6 is considered covering."""
        _add_skill_to_registry(engine, "google-docs-editor", ["create", "google", "doc", "format"])
        is_covered, skill_name = engine.check_existing_coverage("create google doc")
        assert is_covered is True
        assert skill_name == "google-docs-editor"

    def test_skill_with_low_overlap_returns_not_covered(self, engine):
        """Skill with overlap <= 0.6 is not covering."""
        _add_skill_to_registry(engine, "seo-audit", ["seo", "audit", "ranking", "meta", "tags"])
        is_covered, skill_name = engine.check_existing_coverage("create google doc")
        assert is_covered is False
        assert skill_name is None

    def test_multiple_skills_returns_best_match(self, engine):
        """When multiple skills exist, the one with highest overlap wins."""
        _add_skill_to_registry(engine, "seo-audit", ["seo", "audit", "ranking"])
        _add_skill_to_registry(engine, "google-docs-editor", ["create", "google", "doc", "format"])
        is_covered, skill_name = engine.check_existing_coverage("create google doc")
        assert is_covered is True
        assert skill_name == "google-docs-editor"

    def test_skill_with_null_keywords_skipped(self, engine):
        """Skills with NULL keywords are gracefully skipped."""
        engine.db.conn.execute(
            "INSERT INTO skill_registry (skill_name, keywords, first_seen) VALUES (?, NULL, ?)",
            ("broken-skill", datetime.now().isoformat()),
        )
        engine.db.conn.commit()
        is_covered, skill_name = engine.check_existing_coverage("create google doc")
        assert is_covered is False
        assert skill_name is None


# --- evaluate_patterns ---

class TestEvaluatePatterns:
    """Tests for pattern evaluation and proposal generation."""

    def test_no_patterns_returns_empty(self, engine):
        """When no action patterns exist, no proposals are generated."""
        proposals = engine.evaluate_patterns()
        assert proposals == []

    def test_daily_burst_generates_proposal(self, engine):
        """3+ occurrences in a single day triggers a daily_burst proposal."""
        _seed_daily_burst(engine, "create google doc", count=3)
        proposals = engine.evaluate_patterns()
        assert len(proposals) == 1
        assert proposals[0].trigger_reason == "daily_burst"
        assert proposals[0].confidence == pytest.approx(0.6)
        assert "google" in proposals[0].action_signature.lower()

    def test_sustained_pattern_generates_proposal(self, engine):
        """7+ distinct days triggers a sustained_pattern proposal."""
        _seed_sustained_pattern(engine, "create google doc", days=7)
        proposals = engine.evaluate_patterns()
        assert len(proposals) == 1
        assert proposals[0].trigger_reason == "sustained_pattern"
        assert proposals[0].confidence == pytest.approx(0.7)

    def test_covered_by_existing_skill_skipped(self, engine):
        """Pattern covered by existing skill does not generate a proposal."""
        _add_skill_to_registry(engine, "google-docs-editor", ["create", "google", "doc"])
        _seed_daily_burst(engine, "create google doc", count=3)
        proposals = engine.evaluate_patterns()
        assert proposals == []

    def test_already_pending_proposal_no_duplicate(self, engine):
        """Pattern with an existing pending proposal does not create duplicate."""
        _seed_daily_burst(engine, "create google doc", count=3)
        # First evaluation creates the proposal
        proposals_1 = engine.evaluate_patterns()
        assert len(proposals_1) == 1
        # Persist the proposal
        engine.create_proposal(proposals_1[0])
        # Second evaluation should skip it
        proposals_2 = engine.evaluate_patterns()
        assert proposals_2 == []

    def test_both_triggers_met_uses_sustained(self, engine):
        """When both daily burst and sustained pattern are met, sustained wins."""
        # Seed sustained (7+ days) plus enough for daily burst today
        _seed_sustained_pattern(engine, "create google doc", days=7)
        # Add extra occurrences today to also trigger daily burst
        state = engine.tracker._load_state()
        hash_id = engine.tracker._generate_pattern_hash("create google doc")
        today = datetime.now().strftime("%Y-%m-%d")
        state["action_patterns"][hash_id]["daily_occurrences"][today] = 3
        engine.tracker._save_state(state)

        proposals = engine.evaluate_patterns()
        assert len(proposals) == 1
        assert proposals[0].trigger_reason == "sustained_pattern"
        assert proposals[0].confidence == pytest.approx(0.7)

    def test_below_threshold_no_proposal(self, engine):
        """Pattern with only 2 daily occurrences and < 7 days does not trigger."""
        _seed_daily_burst(engine, "create google doc", count=2)
        proposals = engine.evaluate_patterns()
        assert proposals == []

    def test_proposal_has_mapped_pattern_id(self, engine):
        """Generated proposal includes the pattern hash as mapped_pattern_id."""
        _seed_daily_burst(engine, "create google doc", count=3)
        proposals = engine.evaluate_patterns()
        assert proposals[0].mapped_pattern_id is not None
        expected_hash = engine.tracker._generate_pattern_hash("create google doc")
        assert proposals[0].mapped_pattern_id == expected_hash


# --- create_proposal ---

class TestCreateProposal:
    """Tests for inserting proposals into the database."""

    def test_inserts_and_returns_row_id(self, engine):
        """create_proposal inserts a row and returns its ID."""
        proposal = SkillProposal(
            proposed_name="auto-google-doc",
            action_signature="create google doc",
            trigger_reason="daily_burst",
            confidence=0.6,
            mapped_pattern_id="abc123",
        )
        row_id = engine.create_proposal(proposal)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_all_fields_persisted(self, engine):
        """All proposal fields are correctly persisted in the database."""
        proposal = SkillProposal(
            proposed_name="auto-google-doc",
            action_signature="create google doc",
            trigger_reason="daily_burst",
            confidence=0.65,
            status="pending",
            mapped_pattern_id="xyz789",
        )
        row_id = engine.create_proposal(proposal)
        stored = engine.get_proposal(row_id)
        assert stored is not None
        assert stored["proposed_name"] == "auto-google-doc"
        assert stored["action_signature"] == "create google doc"
        assert stored["trigger_reason"] == "daily_burst"
        assert stored["confidence"] == pytest.approx(0.65)
        assert stored["status"] == "pending"
        assert stored["mapped_pattern_id"] == "xyz789"
        assert stored["created_at"] is not None
        assert stored["resolved_at"] is None


# --- get_pending_proposals ---

class TestGetPendingProposals:
    """Tests for retrieving pending proposals."""

    def test_returns_only_pending(self, engine):
        """get_pending_proposals returns only proposals with status='pending'."""
        p1 = SkillProposal(proposed_name="a", action_signature="a", trigger_reason="daily_burst", confidence=0.6)
        p2 = SkillProposal(proposed_name="b", action_signature="b", trigger_reason="daily_burst", confidence=0.6)
        id1 = engine.create_proposal(p1)
        engine.create_proposal(p2)
        engine.update_proposal_status(id1, "approved")

        pending = engine.get_pending_proposals()
        assert len(pending) == 1
        assert pending[0]["proposed_name"] == "b"

    def test_returns_empty_when_none(self, engine):
        """get_pending_proposals returns empty list when no pending proposals exist."""
        pending = engine.get_pending_proposals()
        assert pending == []


# --- update_proposal_status ---

class TestUpdateProposalStatus:
    """Tests for updating proposal status."""

    def test_approved_sets_resolved_at(self, engine):
        """Approving a proposal sets resolved_at timestamp."""
        p = SkillProposal(proposed_name="x", action_signature="x", trigger_reason="daily_burst", confidence=0.6)
        row_id = engine.create_proposal(p)
        result = engine.update_proposal_status(row_id, "approved")
        assert result is True
        stored = engine.get_proposal(row_id)
        assert stored["status"] == "approved"
        assert stored["resolved_at"] is not None

    def test_rejected_sets_resolved_at(self, engine):
        """Rejecting a proposal sets resolved_at timestamp."""
        p = SkillProposal(proposed_name="x", action_signature="x", trigger_reason="daily_burst", confidence=0.6)
        row_id = engine.create_proposal(p)
        result = engine.update_proposal_status(row_id, "rejected")
        assert result is True
        stored = engine.get_proposal(row_id)
        assert stored["status"] == "rejected"
        assert stored["resolved_at"] is not None

    def test_implemented_sets_resolved_at(self, engine):
        """Implementing a proposal sets resolved_at timestamp."""
        p = SkillProposal(proposed_name="x", action_signature="x", trigger_reason="daily_burst", confidence=0.6)
        row_id = engine.create_proposal(p)
        result = engine.update_proposal_status(row_id, "implemented")
        assert result is True
        stored = engine.get_proposal(row_id)
        assert stored["status"] == "implemented"
        assert stored["resolved_at"] is not None

    def test_unknown_id_returns_false(self, engine):
        """Updating a non-existent proposal returns False."""
        result = engine.update_proposal_status(9999, "approved")
        assert result is False

    def test_invalid_status_raises(self, engine):
        """Updating with an invalid status raises ValueError."""
        p = SkillProposal(proposed_name="x", action_signature="x", trigger_reason="daily_burst", confidence=0.6)
        row_id = engine.create_proposal(p)
        with pytest.raises(ValueError):
            engine.update_proposal_status(row_id, "bogus")


# --- get_proposal ---

class TestGetProposal:
    """Tests for retrieving a single proposal."""

    def test_returns_dict_for_existing(self, engine):
        """get_proposal returns a dict for an existing proposal."""
        p = SkillProposal(proposed_name="x", action_signature="x", trigger_reason="daily_burst", confidence=0.6)
        row_id = engine.create_proposal(p)
        result = engine.get_proposal(row_id)
        assert isinstance(result, dict)
        assert result["id"] == row_id

    def test_returns_none_for_unknown(self, engine):
        """get_proposal returns None for a non-existent ID."""
        result = engine.get_proposal(9999)
        assert result is None
