"""Skill effectiveness tracker — synthesizes provenance and evolution into a score.

Combines invocation outcomes (from skill_provenance) and change history
(from skill_evolution_snapshots) to compute an effectiveness score (0.0–1.0)
and letter grade (A–F) per skill.

Scoring weights:
    65% success rate   — did it work when used?
    25% usage volume   — is it actually being used? (normalized at 10 invocations)
    10% evolution      — is it being maintained/improved?

Usage:
    from memory_system.skill_effectiveness import SkillEffectivenessTracker

    tracker = SkillEffectivenessTracker()
    report = tracker.assess("my-skill")
    print(report.grade, report.effectiveness_score)

    top = tracker.get_top_skills(limit=5)
    underperformers = tracker.get_underperforming_skills(threshold=0.4)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from memory_system.config import cfg
from memory_system.skill_evolution import SkillEvolutionTracker
from memory_system.skill_provenance import SkillProvenanceTracker

logger = logging.getLogger(__name__)

_SCORE_WEIGHT_SUCCESS = 0.65
_SCORE_WEIGHT_VOLUME = 0.25
_SCORE_WEIGHT_EVOLVED = 0.10
_VOLUME_SATURATION = 10       # invocations to reach full volume score
_FAILURE_RATE_THRESHOLD = 0.5 # above this → flag as issue
_RECENT_DAYS = 30


@dataclass
class EffectivenessReport:
    """Effectiveness assessment for a single skill."""

    skill_name: str
    invocation_count: int
    success_rate: float
    failure_rate: float
    unknown_rate: float
    recent_invocations: int
    has_evolved: bool
    effectiveness_score: float     # 0.0–1.0
    grade: str                     # A, B, C, D, F
    issues: list[str] = field(default_factory=list)


class SkillEffectivenessTracker:
    """Synthesize provenance outcomes and evolution history into effectiveness scores.

    Shares the same SQLite database as SkillProvenanceTracker and
    SkillEvolutionTracker — both underlying tables are created on init.
    """

    def __init__(
        self,
        db_path: str | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._skills_dir = Path(skills_dir) if skills_dir else cfg.skills_dir
        # Instantiating these ensures both tables are created in the shared DB.
        self._provenance = SkillProvenanceTracker(db_path=self._db_path)
        self._evolution = SkillEvolutionTracker(
            db_path=self._db_path, skills_dir=self._skills_dir
        )

    # ── Public API ────────────────────────────────────────────────────────

    def assess(self, skill_name: str) -> EffectivenessReport:
        """Compute an EffectivenessReport for skill_name."""
        invocation_count = self._provenance.invocation_count(skill_name)

        if invocation_count == 0:
            success_rate = failure_rate = unknown_rate = 0.0
        else:
            summary = self._provenance.outcome_summary(skill_name)
            success_rate = summary.get("success", 0) / invocation_count
            failure_rate = summary.get("failure", 0) / invocation_count
            unknown_rate = summary.get("unknown", 0) / invocation_count

        # Recent invocations
        cutoff = (datetime.now() - timedelta(days=_RECENT_DAYS)).isoformat()
        history = self._provenance.get_history(skill_name)
        recent_invocations = sum(1 for r in history if r.invoked_at >= cutoff)

        # Evolution
        evo_history = self._evolution.get_history(skill_name)
        has_evolved = any(s.change_type == "meaningful" for s in evo_history)

        # Score
        effectiveness_score = _compute_score(invocation_count, success_rate, has_evolved)
        grade = _compute_grade(effectiveness_score)
        issues = _compute_issues(invocation_count, failure_rate)

        return EffectivenessReport(
            skill_name=skill_name,
            invocation_count=invocation_count,
            success_rate=round(success_rate, 4),
            failure_rate=round(failure_rate, 4),
            unknown_rate=round(unknown_rate, 4),
            recent_invocations=recent_invocations,
            has_evolved=has_evolved,
            effectiveness_score=round(effectiveness_score, 4),
            grade=grade,
            issues=issues,
        )

    def assess_all(self) -> list[EffectivenessReport]:
        """Assess all skills that have provenance records."""
        rows = self._provenance._conn.execute(
            "SELECT DISTINCT skill_name FROM skill_provenance ORDER BY skill_name ASC"
        ).fetchall()
        reports = []
        for row in rows:
            try:
                reports.append(self.assess(row["skill_name"]))
            except Exception:
                logger.debug("Failed to assess skill %s", row["skill_name"], exc_info=True)
        return reports

    def get_top_skills(self, limit: int = 10) -> list[EffectivenessReport]:
        """Return the top-scoring skills, ordered by effectiveness_score descending."""
        reports = sorted(
            self.assess_all(),
            key=lambda r: r.effectiveness_score,
            reverse=True,
        )
        return reports[:limit]

    def get_underperforming_skills(
        self, threshold: float = 0.4
    ) -> list[EffectivenessReport]:
        """Return skills whose effectiveness_score is below threshold."""
        return [r for r in self.assess_all() if r.effectiveness_score < threshold]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_score(invocation_count: int, success_rate: float, has_evolved: bool) -> float:
    """Compute 0.0–1.0 effectiveness score from available signals."""
    if invocation_count == 0:
        return 0.0
    volume_factor = min(1.0, invocation_count / _VOLUME_SATURATION)
    score = (
        _SCORE_WEIGHT_SUCCESS * success_rate
        + _SCORE_WEIGHT_VOLUME * volume_factor
        + _SCORE_WEIGHT_EVOLVED * (1.0 if has_evolved else 0.0)
    )
    return max(0.0, min(1.0, score))


def _compute_grade(score: float) -> str:
    if score >= 0.8:
        return "A"
    if score >= 0.6:
        return "B"
    if score >= 0.4:
        return "C"
    if score >= 0.2:
        return "D"
    return "F"


def _compute_issues(invocation_count: int, failure_rate: float) -> list[str]:
    issues = []
    if invocation_count == 0:
        issues.append("No recorded invocations — skill may be unused")
    elif failure_rate > _FAILURE_RATE_THRESHOLD:
        issues.append(
            f"High failure rate: {failure_rate:.0%} — review skill instructions"
        )
    return issues
