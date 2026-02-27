"""Skill decay scorer — frequency-aware half-life decay for skill staleness.

Scores how stale each skill in the registry is, using a half-life decay
formula adjusted by usage frequency. Skills used more often get a longer
half-life (they decay slower). Skills that haven't been used recently
accumulate decay toward 1.0.

Formula:
    adjusted_half_life = 30 * (1 + log2(max(1, use_count)))
    decay = 1.0 - (0.5 ** (days_since_last_use / adjusted_half_life))

Usage:
    from memory_system.wild.skill_decay_scorer import SkillDecayScorer

    scorer = SkillDecayScorer()

    # Single skill
    decay = scorer.compute_decay("copywriting")

    # All skills (also updates DB)
    results = scorer.compute_all_decay_scores()

    # Flag stale skills for review
    flagged = scorer.flag_for_review(threshold=0.8)

    # Dismiss a flag
    scorer.dismiss_flag("copywriting")
"""

import math
from datetime import datetime, timedelta
from typing import Optional

from memory_system.wild.intelligence_db import IntelligenceDB


class SkillDecayScorer:
    """Scores skill staleness using frequency-aware half-life decay."""

    def __init__(self, db_path=None):
        self.db = IntelligenceDB(db_path)

    # ── Static formula methods ──────────────────────────────────────────────

    @staticmethod
    def adjusted_half_life(use_count: int) -> float:
        """Calculate the frequency-aware half-life in days.

        Formula: 30 * (1 + log2(max(1, use_count)))

        More usage = longer half-life = slower decay.
        """
        return 30.0 * (1.0 + math.log2(max(1, use_count)))

    @staticmethod
    def decay_score(days_since_last_use: float, half_life: float) -> float:
        """Calculate the decay value.

        Formula: 1.0 - (0.5 ** (days / half_life))

        Returns 0.0 (just used) to ~1.0 (very stale).
        """
        return 1.0 - (0.5 ** (days_since_last_use / half_life))

    # ── Instance methods ────────────────────────────────────────────────────

    def compute_decay(self, skill_name: str, as_of: Optional[datetime] = None) -> float:
        """Compute decay score for a skill.

        Returns 0.0 if skill has never been used (last_used is NULL).
        Returns 0.0 if skill is not found in the registry.
        """
        cursor = self.db.conn.cursor()
        row = cursor.execute(
            "SELECT use_count, last_used FROM skill_registry WHERE skill_name = ?",
            (skill_name,),
        ).fetchone()

        if row is None:
            return 0.0

        use_count = row["use_count"]
        last_used_str = row["last_used"]

        if last_used_str is None:
            return 0.0

        last_used = datetime.fromisoformat(last_used_str)
        now = as_of or datetime.now()

        # Normalize tz-awareness: if one is aware and the other naive, strip tzinfo
        # so the subtraction doesn't raise TypeError.
        if last_used.tzinfo is not None and now.tzinfo is None:
            last_used = last_used.replace(tzinfo=None)
        elif last_used.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        days_elapsed = (now - last_used).total_seconds() / 86400.0

        half_life = self.adjusted_half_life(use_count)
        return self.decay_score(days_elapsed, half_life)

    def compute_all_decay_scores(self, as_of: Optional[datetime] = None) -> list[dict]:
        """Compute decay scores for all skills in registry.

        Returns list of dicts with: skill_name, use_count, last_used,
        decay_score, flagged. Also updates the decay_score column
        in skill_registry.
        """
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT skill_name, use_count, last_used, flagged_for_review "
            "FROM skill_registry"
        ).fetchall()

        results = []
        for row in rows:
            skill_name = row["skill_name"]
            score = self.compute_decay(skill_name, as_of=as_of)

            # Update decay_score in database
            cursor.execute(
                "UPDATE skill_registry SET decay_score = ? WHERE skill_name = ?",
                (score, skill_name),
            )

            results.append({
                "skill_name": skill_name,
                "use_count": row["use_count"],
                "last_used": row["last_used"],
                "decay_score": score,
                "flagged": bool(row["flagged_for_review"]),
            })

        self.db.conn.commit()
        return results

    def flag_for_review(self, threshold: float = 0.8,
                        grace_period_days: int = 14) -> list[dict]:
        """Flag skills with decay >= threshold for review.

        Rules:
        - Skip skills with first_seen within grace_period_days (new skills)
        - Skip skills already flagged where flag_dismissed_at is within 30 days
        - Set flagged_for_review = 1 on qualifying skills
        - Returns list of newly flagged skill dicts
        """
        # First recompute all decay scores
        self.compute_all_decay_scores()

        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT skill_name, first_seen, use_count, last_used, "
            "decay_score, flagged_for_review, flag_dismissed_at "
            "FROM skill_registry WHERE decay_score >= ?",
            (threshold,),
        ).fetchall()

        now = datetime.now()
        grace_cutoff = now - timedelta(days=grace_period_days)
        dismiss_cutoff = now - timedelta(days=30)

        newly_flagged = []
        for row in rows:
            first_seen = datetime.fromisoformat(row["first_seen"])

            # Skip new skills within grace period
            if first_seen > grace_cutoff:
                continue

            # Skip recently dismissed flags
            dismissed_str = row["flag_dismissed_at"]
            if dismissed_str is not None:
                dismissed_at = datetime.fromisoformat(dismissed_str)
                if dismissed_at > dismiss_cutoff:
                    continue

            # Flag the skill
            cursor.execute(
                "UPDATE skill_registry SET flagged_for_review = 1 "
                "WHERE skill_name = ?",
                (row["skill_name"],),
            )

            newly_flagged.append({
                "skill_name": row["skill_name"],
                "use_count": row["use_count"],
                "last_used": row["last_used"],
                "decay_score": row["decay_score"],
            })

        self.db.conn.commit()
        return newly_flagged

    def dismiss_flag(self, skill_name: str) -> bool:
        """Dismiss a review flag.

        Sets flag_dismissed_at to now, flagged_for_review = 0.
        Returns True if skill was found and updated, False otherwise.
        """
        cursor = self.db.conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute(
            "UPDATE skill_registry SET flagged_for_review = 0, "
            "flag_dismissed_at = ? WHERE skill_name = ?",
            (now_iso, skill_name),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def get_flagged_skills(self) -> list[dict]:
        """Get all currently flagged skills from database."""
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT skill_name, use_count, last_used, decay_score, "
            "first_seen, flag_dismissed_at "
            "FROM skill_registry WHERE flagged_for_review = 1"
        ).fetchall()
        return [dict(row) for row in rows]
