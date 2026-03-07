"""Skill health dashboard — unified report aggregating all six intelligence sources.

Combines SkillDocHealth, SkillEffectivenessTracker, SkillEvolutionTracker,
SkillWorkflowAnalyzer, SkillAntiPatternMiner, and CorrectionVelocityTracker
into a single SkillHealthReport dict suitable for /api/skill-health.

Usage:
    from memory_system.skill_health_dashboard import build_skill_health_report

    report = build_skill_health_report(
        db_path="intelligence.db",
        memory_dir=Path("~/.local/share/memory/LFI/memories"),
        skills_dir=Path("~/.agents/skills"),
    )
    # report is a plain dict — serialize to JSON for the dashboard endpoint
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.skill_antipattern_miner import SkillAntiPatternMiner
from memory_system.skill_doc_health import SkillDocHealth
from memory_system.skill_effectiveness import SkillEffectivenessTracker
from memory_system.skill_evolution import SkillEvolutionTracker
from memory_system.skill_workflow_analyzer import SkillWorkflowAnalyzer
from memory_system.correction_velocity import CorrectionVelocityTracker

logger = logging.getLogger(__name__)

_DEFAULT_MIN_ANTIPATTERN = 2


@dataclass
class SkillHealthReport:
    """Unified skill health snapshot."""

    generated_at: str
    summary: dict
    docs: list = field(default_factory=list)
    effectiveness: list = field(default_factory=list)
    evolution: list = field(default_factory=list)
    workflows: list = field(default_factory=list)
    antipatterns: list = field(default_factory=list)
    correction_velocity: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "summary": self.summary,
            "docs": self.docs,
            "effectiveness": self.effectiveness,
            "evolution": self.evolution,
            "workflows": self.workflows,
            "antipatterns": self.antipatterns,
            "correction_velocity": self.correction_velocity,
        }


class SkillHealthDashboard:
    """Aggregate skill intelligence data into a single report."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        memory_dir: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
    ) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._memory_dir = Path(memory_dir) if memory_dir else cfg.project_memory_dir
        self._skills_dir = Path(skills_dir) if skills_dir else None

    def build(
        self,
        min_antipattern_co_occurrences: int = _DEFAULT_MIN_ANTIPATTERN,
    ) -> SkillHealthReport:
        """Build and return the unified health report."""
        docs = self._get_docs()
        effectiveness = self._get_effectiveness()
        evolution = self._get_evolution()
        workflows = self._get_workflows()
        antipatterns = self._get_antipatterns(min_antipattern_co_occurrences)
        correction_velocity = self._get_correction_velocity()

        summary = self._build_summary(docs, effectiveness, antipatterns, correction_velocity)

        return SkillHealthReport(
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            summary=summary,
            docs=docs,
            effectiveness=effectiveness,
            evolution=evolution,
            workflows=workflows,
            antipatterns=antipatterns,
            correction_velocity=correction_velocity,
        )

    # ── Section builders ──────────────────────────────────────────────────

    def _get_docs(self) -> list:
        if not self._skills_dir or not self._skills_dir.exists():
            return []
        try:
            checker = SkillDocHealth(skills_dir=self._skills_dir)
            reports = checker.scan_all()
            return [
                {
                    "skill_name": r.skill_name,
                    "grade": _health_grade(r.health_score),
                    "health_score": round(r.health_score, 4),
                    "issues": r.issues,
                    "is_stale": r.is_stale,
                    "missing_sections": r.missing_sections,
                    "days_since_update": r.days_since_update,
                }
                for r in reports
            ]
        except Exception:
            logger.debug("SkillDocHealth failed", exc_info=True)
            return []

    def _get_effectiveness(self) -> list:
        try:
            tracker = SkillEffectivenessTracker(
                db_path=self._db_path,
                skills_dir=self._skills_dir,
            )
            reports = tracker.assess_all()
            return [
                {
                    "skill_name": r.skill_name,
                    "grade": r.grade,
                    "effectiveness_score": round(r.effectiveness_score, 4),
                    "invocation_count": r.invocation_count,
                    "success_rate": round(r.success_rate, 4),
                    "failure_rate": round(r.failure_rate, 4),
                    "has_evolved": r.has_evolved,
                    "issues": r.issues,
                }
                for r in reports
            ]
        except Exception:
            logger.debug("SkillEffectivenessTracker failed", exc_info=True)
            return []

    def _get_evolution(self) -> list:
        if not self._skills_dir:
            return []
        try:
            tracker = SkillEvolutionTracker(
                db_path=self._db_path,
                skills_dir=self._skills_dir,
            )
            # Get most recent snapshot per skill
            rows = tracker._conn.execute(
                """
                SELECT skill_name, change_type, content_hash, snapshotted_at
                FROM skill_evolution_snapshots
                GROUP BY skill_name
                HAVING MAX(id)
                ORDER BY snapshotted_at DESC
                """
            ).fetchall()
            return [
                {
                    "skill_name": row["skill_name"],
                    "change_type": row["change_type"],
                    "content_hash": row["content_hash"][:8],  # short prefix
                    "snapshotted_at": row["snapshotted_at"],
                }
                for row in rows
            ]
        except Exception:
            logger.debug("SkillEvolutionTracker failed", exc_info=True)
            return []

    def _get_workflows(self) -> list:
        try:
            analyzer = SkillWorkflowAnalyzer(db_path=self._db_path)
            sequences = analyzer.get_common_pairs(min_sessions=2)
            return [
                {
                    "skills": seq.skills,
                    "session_count": seq.session_count,
                    "frequency": round(seq.frequency, 4),
                    "example_sessions": seq.example_sessions[:3],
                }
                for seq in sequences
            ]
        except Exception:
            logger.debug("SkillWorkflowAnalyzer failed", exc_info=True)
            return []

    def _get_antipatterns(self, min_co_occurrences: int) -> list:
        try:
            miner = SkillAntiPatternMiner(
                db_path=self._db_path,
                memory_dir=self._memory_dir,
            )
            reports = miner.analyze(min_co_occurrences=min_co_occurrences)
            return [
                {
                    "skill_name": r.skill_name,
                    "risk_level": r.risk_level,
                    "co_occurrence_count": r.co_occurrence_count,
                    "co_occurrence_rate": round(r.co_occurrence_rate, 4),
                    "sample_corrections": r.sample_corrections,
                }
                for r in reports
            ]
        except Exception:
            logger.debug("SkillAntiPatternMiner failed", exc_info=True)
            return []

    def _get_correction_velocity(self) -> dict:
        try:
            tracker = CorrectionVelocityTracker(memory_dir=self._memory_dir)
            snap = tracker.get_pipeline_snapshot()
            stuck = tracker.get_stuck_corrections(days=30)
            return {
                "total": snap.total,
                "graduated": snap.graduated,
                "pending": snap.pending,
                "new": snap.new,
                "graduation_rate": round(snap.graduation_rate, 4),
                "avg_days_to_graduate": (
                    round(snap.avg_days_to_graduate, 1)
                    if snap.avg_days_to_graduate is not None
                    else None
                ),
                "stuck_count": len(stuck),
            }
        except Exception:
            logger.debug("CorrectionVelocityTracker failed", exc_info=True)
            return {
                "total": 0, "graduated": 0, "pending": 0, "new": 0,
                "graduation_rate": 0.0, "avg_days_to_graduate": None,
                "stuck_count": 0,
            }

    # ── Summary ───────────────────────────────────────────────────────────

    def _build_summary(
        self,
        docs: list,
        effectiveness: list,
        antipatterns: list,
        correction_velocity: dict,
    ) -> dict:
        avg_health = 0.0
        if docs:
            avg_health = sum(d["health_score"] for d in docs) / len(docs)

        total_invocations = sum(e["invocation_count"] for e in effectiveness)

        # Skills flagged as medium or high risk
        at_risk = [
            a["skill_name"]
            for a in antipatterns
            if a["risk_level"] in ("medium", "high")
        ]

        return {
            "total_docs_scanned": len(docs),
            "avg_doc_health_score": round(avg_health, 4),
            "skills_at_risk": at_risk,
            "total_invocations": total_invocations,
            "graduation_rate": correction_velocity.get("graduation_rate", 0.0),
        }


# ── Module helpers ────────────────────────────────────────────────────────────

def _health_grade(score: float) -> str:
    if score >= 0.8:
        return "A"
    if score >= 0.6:
        return "B"
    if score >= 0.4:
        return "C"
    if score >= 0.2:
        return "D"
    return "F"


# ── Convenience function ──────────────────────────────────────────────────────

def build_skill_health_report(
    db_path: Optional[str] = None,
    memory_dir: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
    min_antipattern_co_occurrences: int = _DEFAULT_MIN_ANTIPATTERN,
) -> dict:
    """Return the skill health report as a plain dict (JSON-serializable)."""
    dashboard = SkillHealthDashboard(
        db_path=db_path,
        memory_dir=memory_dir,
        skills_dir=skills_dir,
    )
    return dashboard.build(
        min_antipattern_co_occurrences=min_antipattern_co_occurrences
    ).to_dict()
