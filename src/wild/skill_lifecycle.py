"""Skill lifecycle manager — facade orchestrating all skill lifecycle sub-modules.

Provides a single entry point for daily maintenance, usage recording, and
lifecycle summary by coordinating:
- SkillActionTracker (action pattern tracking)
- SkillRegistryScanner (filesystem skill discovery)
- SkillDecayScorer (staleness scoring)
- SkillProposalEngine (proposal generation)

Usage:
    from memory_system.wild.skill_lifecycle import SkillLifecycleManager

    mgr = SkillLifecycleManager()

    # Daily maintenance pipeline
    summary = mgr.run_daily_maintenance()

    # Record a skill usage
    mgr.record_skill_usage("copywriting", session_id="abc123")

    # Get full lifecycle summary
    overview = mgr.get_lifecycle_summary()
"""

import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.wild.intelligence_db import IntelligenceDB
from memory_system.wild.skill_action_tracker import SkillActionTracker
from memory_system.wild.skill_registry_scanner import SkillRegistryScanner
from memory_system.wild.skill_decay_scorer import SkillDecayScorer
from memory_system.wild.skill_proposal_engine import SkillProposalEngine

logger = logging.getLogger(__name__)


class SkillLifecycleManager:
    """Facade orchestrating all skill lifecycle sub-modules."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        state_path: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
    ):
        resolved_db = db_path or cfg.intelligence_db_path
        resolved_state = state_path or cfg.skill_lifecycle_state_path
        resolved_skills_dir = skills_dir or cfg.skills_dir

        self.db = IntelligenceDB(resolved_db)

        try:
            self.tracker = SkillActionTracker(
                state_path=resolved_state, db_path=resolved_db
            )
        except Exception:
            logger.warning(
                "Failed to load action tracker state at %s; resetting to defaults",
                resolved_state,
            )
            # Reset corrupted state file and retry
            if Path(resolved_state).exists():
                Path(resolved_state).unlink()
            self.tracker = SkillActionTracker(
                state_path=resolved_state, db_path=resolved_db
            )

        self.scanner = SkillRegistryScanner(
            skills_dir=resolved_skills_dir, db_path=resolved_db
        )
        self.decay_scorer = SkillDecayScorer(db_path=resolved_db)

        try:
            self.proposal_engine = SkillProposalEngine(
                db_path=resolved_db, state_path=resolved_state
            )
        except Exception:
            logger.warning(
                "Failed to initialize proposal engine; resetting state",
            )
            if Path(resolved_state).exists():
                Path(resolved_state).unlink()
            self.proposal_engine = SkillProposalEngine(
                db_path=resolved_db, state_path=resolved_state
            )

    # ── Daily maintenance pipeline ───────────────────────────────────────

    def run_daily_maintenance(self) -> dict:
        """Run the full daily lifecycle pipeline.

        Steps:
        1. Scanner: sync skills from filesystem
        2. Decay scorer: compute all decay scores
        3. Decay scorer: flag stale skills for review
        4. Proposal engine: evaluate patterns for proposals
        5. Persist any new proposals

        Returns summary dict with keys:
            skills_synced, decay_scores_updated, newly_flagged, new_proposals
        """
        # Step 1: scan and sync skills from filesystem
        try:
            sync_result = self.scanner.sync_to_db()
        except Exception:
            logger.exception("Scanner sync failed")
            sync_result = {"new": 0, "updated": 0, "total": 0}

        # Step 2: compute all decay scores
        try:
            decay_scores = self.decay_scorer.compute_all_decay_scores()
        except Exception:
            logger.exception("Decay scoring failed")
            decay_scores = []

        # Step 3: flag stale skills for review
        try:
            newly_flagged = self.decay_scorer.flag_for_review()
        except Exception:
            logger.exception("Flag for review failed")
            newly_flagged = []

        # Step 4: evaluate patterns for proposals
        try:
            proposals = self.proposal_engine.evaluate_patterns()
        except Exception:
            logger.exception("Pattern evaluation failed")
            proposals = []

        # Step 5: persist new proposals
        persisted_proposals = []
        for proposal in proposals:
            try:
                proposal_id = self.proposal_engine.create_proposal(proposal)
                persisted_proposals.append({
                    "id": proposal_id,
                    "proposed_name": proposal.proposed_name,
                    "trigger_reason": proposal.trigger_reason,
                    "confidence": proposal.confidence,
                })
            except Exception:
                logger.exception("Failed to create proposal: %s", proposal.proposed_name)

        return {
            "skills_synced": sync_result,
            "decay_scores_updated": len(decay_scores),
            "newly_flagged": newly_flagged,
            "new_proposals": persisted_proposals,
        }

    # ── Usage recording ──────────────────────────────────────────────────

    def record_skill_usage(self, skill_name: str, session_id: str = "") -> None:
        """Record a skill usage event.

        1. Insert into skill_usage_events table
        2. Update skill_registry: increment use_count, set last_used
        """
        now_iso = datetime.now().isoformat()
        cursor = self.db.conn.cursor()

        # Insert usage event
        cursor.execute(
            "INSERT INTO skill_usage_events (skill_name, session_id, used_at) "
            "VALUES (?, ?, ?)",
            (skill_name, session_id, now_iso),
        )

        # Update registry (no-op if skill not in registry)
        cursor.execute(
            "UPDATE skill_registry SET use_count = use_count + 1, last_used = ? "
            "WHERE skill_name = ?",
            (now_iso, skill_name),
        )

        self.db.conn.commit()

    # ── Lifecycle summary ────────────────────────────────────────────────

    def get_lifecycle_summary(self) -> dict:
        """Return comprehensive lifecycle summary.

        Returns:
            {
                "proposals": {"pending": [...], "total_pending": int},
                "flagged_skills": [...],
                "decay_scores": [...],
                "action_patterns": {"total": int, "recent": [...]},
                "registry": {"total_skills": int},
            }
        """
        # Proposals
        try:
            pending = self.proposal_engine.get_pending_proposals()
        except Exception:
            logger.exception("Failed to get pending proposals")
            pending = []

        # Flagged skills
        try:
            flagged = self.decay_scorer.get_flagged_skills()
        except Exception:
            logger.exception("Failed to get flagged skills")
            flagged = []

        # Decay scores
        try:
            scores = self.decay_scorer.compute_all_decay_scores()
        except Exception:
            logger.exception("Failed to compute decay scores")
            scores = []

        # Action patterns
        try:
            all_patterns = self.tracker.get_patterns()
            pattern_dicts = [asdict(p) for p in all_patterns]
            recent = pattern_dicts[-10:] if len(pattern_dicts) > 10 else pattern_dicts
        except Exception:
            logger.exception("Failed to get action patterns")
            pattern_dicts = []
            recent = []

        # Registry count
        try:
            cursor = self.db.conn.cursor()
            row = cursor.execute("SELECT COUNT(*) as cnt FROM skill_registry").fetchone()
            total_skills = row["cnt"] if row else 0
        except Exception:
            logger.exception("Failed to count skills")
            total_skills = 0

        return {
            "proposals": {
                "pending": pending,
                "total_pending": len(pending),
            },
            "flagged_skills": flagged,
            "decay_scores": scores,
            "action_patterns": {
                "total": len(pattern_dicts),
                "recent": recent,
            },
            "registry": {
                "total_skills": total_skills,
            },
        }

    # ── Delegation methods ───────────────────────────────────────────────

    def get_proposals(self, status: str = "pending") -> list[dict]:
        """Get proposals filtered by status. Delegates to proposal engine."""
        if status == "pending":
            return self.proposal_engine.get_pending_proposals()
        # For other statuses, query directly
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT * FROM skill_proposals WHERE status = ? ORDER BY id",
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_proposal(self, proposal_id: int, status: str) -> bool:
        """Update proposal status. Delegates to proposal engine."""
        return self.proposal_engine.update_proposal_status(proposal_id, status)

    def get_flagged_skills(self) -> list[dict]:
        """Get all currently flagged skills. Delegates to decay scorer."""
        return self.decay_scorer.get_flagged_skills()

    def dismiss_flag(self, skill_name: str) -> bool:
        """Dismiss a review flag. Delegates to decay scorer."""
        return self.decay_scorer.dismiss_flag(skill_name)

    def get_decay_scores(self) -> list[dict]:
        """Get decay scores for all skills. Delegates to decay scorer."""
        return self.decay_scorer.compute_all_decay_scores()

    def get_action_patterns(self, min_frequency: int = 1) -> list[dict]:
        """Get action patterns as list of dicts. Delegates to action tracker."""
        patterns = self.tracker.get_patterns(min_frequency=min_frequency)
        return [asdict(p) for p in patterns]
