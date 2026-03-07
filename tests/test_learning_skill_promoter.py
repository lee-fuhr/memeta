"""Tests for the Learning-to-SKILL.md pipeline.

When a learning is surfaced in 3+ session briefings, generate a proposal
to promote it as a permanent note in the relevant SKILL.md. Closes the
loop between experience (memory) and capability (skill docs).
"""
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.learning_skill_promoter import (
    LearningSkillPromoter,
    LearningAppearance,
    PromotionProposal,
    ProposalStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_promoter(tmp_path):
    db_path = tmp_path / "intelligence.db"
    return LearningSkillPromoter(db_path=db_path)


def _seed_appearances(
    promoter, learning_id, skill_name, count, start_date=None, learning_content=""
):
    """Seed `count` briefing appearances for a learning."""
    base = start_date or date.today()
    session_ids = [f"session-{i:03d}" for i in range(count)]
    for i, sid in enumerate(session_ids):
        d = base - timedelta(days=count - i - 1)
        promoter.record_appearance(
            learning_id=learning_id,
            skill_name=skill_name,
            session_id=sid,
            briefing_date=d,
            learning_content=learning_content,
        )
    return session_ids


# ---------------------------------------------------------------------------
# Import + instantiation
# ---------------------------------------------------------------------------

class TestImport:
    def test_imports(self):
        from memory_system.learning_skill_promoter import LearningSkillPromoter
        assert LearningSkillPromoter is not None

    def test_namedtuples_importable(self):
        from memory_system.learning_skill_promoter import (
            LearningAppearance, PromotionProposal, ProposalStatus
        )
        assert LearningAppearance is not None

    def test_instantiates_with_db_path(self, tmp_path):
        p = _make_promoter(tmp_path)
        assert p is not None

    def test_creates_tables_on_init(self, tmp_path):
        p = _make_promoter(tmp_path)
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "learning_briefing_appearances" in tables
        assert "learning_promotion_proposals" in tables
        conn.close()


# ---------------------------------------------------------------------------
# record_appearance
# ---------------------------------------------------------------------------

class TestRecordAppearance:
    def test_records_a_single_appearance(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.record_appearance("learn-001", "debugging", "sess-001", date.today(), "Check logs.")
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        rows = conn.execute("SELECT * FROM learning_briefing_appearances").fetchall()
        assert len(rows) == 1
        conn.close()

    def test_returns_row_id(self, tmp_path):
        p = _make_promoter(tmp_path)
        row_id = p.record_appearance("learn-001", "debugging", "sess-001", date.today())
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_deduplicates_same_session(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.record_appearance("learn-001", "debugging", "sess-001", date.today())
        p.record_appearance("learn-001", "debugging", "sess-001", date.today())
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        rows = conn.execute("SELECT * FROM learning_briefing_appearances").fetchall()
        assert len(rows) == 1
        conn.close()

    def test_different_sessions_accumulate(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3)
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM learning_briefing_appearances WHERE learning_id='learn-001'"
        ).fetchone()[0]
        assert count == 3
        conn.close()

    def test_stores_skill_name(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.record_appearance("learn-001", "my-skill", "sess-001", date.today())
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        row = conn.execute(
            "SELECT skill_name FROM learning_briefing_appearances WHERE learning_id='learn-001'"
        ).fetchone()
        assert row[0] == "my-skill"
        conn.close()

    def test_accepts_string_date(self, tmp_path):
        p = _make_promoter(tmp_path)
        row_id = p.record_appearance("learn-001", "debugging", "sess-001", "2026-03-01")
        assert isinstance(row_id, int)


# ---------------------------------------------------------------------------
# get_promotion_candidates
# ---------------------------------------------------------------------------

class TestGetPromotionCandidates:
    def test_returns_empty_when_no_appearances(self, tmp_path):
        p = _make_promoter(tmp_path)
        assert p.get_promotion_candidates() == []

    def test_returns_empty_below_threshold(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 2)
        assert p.get_promotion_candidates() == []

    def test_returns_candidate_at_threshold(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3)
        candidates = p.get_promotion_candidates()
        assert len(candidates) == 1
        assert candidates[0].learning_id == "learn-001"

    def test_returns_candidate_above_threshold(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 5)
        candidates = p.get_promotion_candidates()
        assert len(candidates) == 1

    def test_respects_custom_min_appearances(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 2)
        candidates = p.get_promotion_candidates(min_appearances=2)
        assert len(candidates) == 1

    def test_candidate_has_appearance_count(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 4)
        candidates = p.get_promotion_candidates()
        assert candidates[0].appearance_count == 4

    def test_candidate_has_skill_name(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "my-skill", 3)
        candidates = p.get_promotion_candidates()
        assert candidates[0].skill_name == "my-skill"

    def test_multiple_learnings_both_returned(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "skill-a", 3)
        _seed_appearances(p, "learn-002", "skill-b", 4)
        candidates = p.get_promotion_candidates()
        ids = {c.learning_id for c in candidates}
        assert "learn-001" in ids
        assert "learn-002" in ids

    def test_excludes_already_proposed(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3)
        # Generate a proposal first
        p.generate_proposal("learn-001", "debugging", "Always check logs first.")
        # Candidate should be excluded (already proposed)
        candidates = p.get_promotion_candidates()
        assert candidates == []

    def test_sorted_by_appearance_count_desc(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "skill-a", 3)
        _seed_appearances(p, "learn-002", "skill-b", 5)
        candidates = p.get_promotion_candidates()
        assert candidates[0].learning_id == "learn-002"


# ---------------------------------------------------------------------------
# generate_proposal
# ---------------------------------------------------------------------------

class TestGenerateProposal:
    def test_returns_proposal(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs before anything.")
        assert isinstance(proposal, PromotionProposal)

    def test_proposal_has_learning_id(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs first.")
        assert proposal.learning_id == "learn-001"

    def test_proposal_has_skill_name(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs first.")
        assert proposal.skill_name == "debugging"

    def test_proposal_text_contains_learning_content(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Always check logs first.")
        assert "Always check logs first." in proposal.proposed_text

    def test_proposal_status_defaults_to_pending(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        assert proposal.status == ProposalStatus.PENDING

    def test_proposal_persisted_to_db(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.generate_proposal("learn-001", "debugging", "Check logs.")
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        row = conn.execute("SELECT * FROM learning_promotion_proposals").fetchone()
        assert row is not None
        conn.close()

    def test_duplicate_proposal_not_created(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.generate_proposal("learn-001", "debugging", "Check logs.")
        p.generate_proposal("learn-001", "debugging", "Different text.")
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM learning_promotion_proposals WHERE learning_id='learn-001'"
        ).fetchone()[0]
        assert count == 1
        conn.close()


# ---------------------------------------------------------------------------
# get_pending_proposals
# ---------------------------------------------------------------------------

class TestGetPendingProposals:
    def test_returns_empty_when_none(self, tmp_path):
        p = _make_promoter(tmp_path)
        assert p.get_pending_proposals() == []

    def test_returns_pending_proposal(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.generate_proposal("learn-001", "debugging", "Check logs.")
        proposals = p.get_pending_proposals()
        assert len(proposals) == 1

    def test_does_not_return_applied_proposals(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        p.mark_applied(proposal.proposal_id)
        assert p.get_pending_proposals() == []

    def test_does_not_return_dismissed_proposals(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        p.mark_dismissed(proposal.proposal_id)
        assert p.get_pending_proposals() == []

    def test_returns_multiple_pending(self, tmp_path):
        p = _make_promoter(tmp_path)
        p.generate_proposal("learn-001", "skill-a", "Note one.")
        p.generate_proposal("learn-002", "skill-b", "Note two.")
        assert len(p.get_pending_proposals()) == 2


# ---------------------------------------------------------------------------
# mark_applied / mark_dismissed
# ---------------------------------------------------------------------------

class TestMarkApplied:
    def test_mark_applied_changes_status(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        p.mark_applied(proposal.proposal_id)
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        row = conn.execute(
            "SELECT status FROM learning_promotion_proposals WHERE id=?",
            (proposal.proposal_id,),
        ).fetchone()
        assert row[0] == ProposalStatus.APPLIED.value
        conn.close()

    def test_mark_dismissed_changes_status(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        p.mark_dismissed(proposal.proposal_id)
        conn = sqlite3.connect(tmp_path / "intelligence.db")
        row = conn.execute(
            "SELECT status FROM learning_promotion_proposals WHERE id=?",
            (proposal.proposal_id,),
        ).fetchone()
        assert row[0] == ProposalStatus.DISMISSED.value
        conn.close()

    def test_mark_applied_returns_true_on_success(self, tmp_path):
        p = _make_promoter(tmp_path)
        proposal = p.generate_proposal("learn-001", "debugging", "Check logs.")
        result = p.mark_applied(proposal.proposal_id)
        assert result is True

    def test_mark_applied_returns_false_on_missing_id(self, tmp_path):
        p = _make_promoter(tmp_path)
        result = p.mark_applied(99999)
        assert result is False


# ---------------------------------------------------------------------------
# format_skill_md_addition
# ---------------------------------------------------------------------------

class TestFormatSkillMdAddition:
    def test_formats_markdown_note(self, tmp_path):
        p = _make_promoter(tmp_path)
        text = p.format_skill_md_addition(
            skill_name="debugging",
            learning_content="Always check logs before diagnosing the issue.",
            appearance_count=4,
        )
        assert "debugging" in text
        assert "Always check logs" in text

    def test_includes_promoted_from_note(self, tmp_path):
        p = _make_promoter(tmp_path)
        text = p.format_skill_md_addition(
            skill_name="debugging",
            learning_content="Check logs first.",
            appearance_count=4,
        )
        assert "4" in text or "briefing" in text.lower()

    def test_returns_string(self, tmp_path):
        p = _make_promoter(tmp_path)
        result = p.format_skill_md_addition("s", "content", 3)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Pipeline integration: auto_promote_pending
# ---------------------------------------------------------------------------

class TestAutoPromotePending:
    def test_generates_proposals_for_threshold_learnings(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3, learning_content="Check logs first.")
        _seed_appearances(p, "learn-002", "skill-b", 2, learning_content="Use types.")
        count = p.auto_promote_pending()
        assert count == 1

    def test_returns_zero_when_nothing_qualifies(self, tmp_path):
        p = _make_promoter(tmp_path)
        assert p.auto_promote_pending() == 0

    def test_does_not_double_promote(self, tmp_path):
        p = _make_promoter(tmp_path)
        _seed_appearances(p, "learn-001", "debugging", 3, learning_content="Check logs.")
        p.auto_promote_pending()
        count = p.auto_promote_pending()
        assert count == 0
