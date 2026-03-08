"""Skill documentation health system — detects stale and incomplete SKILL.md files.

Scans the skills directory, checks each SKILL.md for required sections and
freshness, and reports health scores and actionable issues. Prevents skill
rot from accumulating silently as the roster grows.

Required sections (checked case-insensitively):
- ## When to use
- ## Examples
- ## Limitations

Health score:
- 0.0 if SKILL.md is missing entirely
- Deduct 0.2 per missing required section (max -0.6)
- Deduct 0.2 if stale (not updated in STALE_DAYS days)
- Clamp to [0.0, 1.0]

Usage:
    from memory_system.skill_doc_health import SkillDocHealth

    health = SkillDocHealth()
    for report in health.get_incomplete_skills():
        print(f"{report.skill_name}: {report.missing_sections}")

    print(health.summary())
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from memory_system.config import cfg

logger = logging.getLogger(__name__)

# Required sections (stored lowercase for comparison)
REQUIRED_SECTIONS: list[str] = [
    "## when to use",
    "## examples",
    "## limitations",
]

STALE_DAYS: int = 30
_SECTION_DEDUCTION: float = 0.2
_STALE_DEDUCTION: float = 0.2
_HEALTHY_THRESHOLD: float = 0.8


@dataclass
class SkillHealthReport:
    """Health report for a single skill."""

    skill_name: str
    has_skill_md: bool
    last_modified: datetime | None
    days_since_update: int | None
    is_stale: bool
    missing_sections: list[str]
    is_complete: bool
    health_score: float        # 0.0–1.0
    issues: list[str] = field(default_factory=list)


class SkillDocHealth:
    """Detects stale and incomplete SKILL.md files across the skills directory.

    Each skill is a subdirectory under skills_dir containing a SKILL.md file.
    Skills without a SKILL.md score 0.0. Skills with all required sections
    and a recent update score 1.0.
    """

    def __init__(self, skills_dir=None, stale_days: int = STALE_DAYS):
        self.skills_dir = Path(skills_dir) if skills_dir else cfg.skills_dir
        self.stale_days = stale_days

    # ── Public API ────────────────────────────────────────────────────────

    def scan_all(self) -> list[SkillHealthReport]:
        """Scan all skill subdirectories and return health reports.

        Returns empty list if skills directory does not exist.
        """
        if not self.skills_dir.exists():
            return []

        reports = []
        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                reports.append(self.check_skill(entry.name))
            except Exception:
                logger.debug("Failed to check skill %s", entry.name, exc_info=True)
        return reports

    def check_skill(self, skill_name: str) -> SkillHealthReport:
        """Check a single skill by name. Returns a SkillHealthReport."""
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            return SkillHealthReport(
                skill_name=skill_name,
                has_skill_md=False,
                last_modified=None,
                days_since_update=None,
                is_stale=False,
                missing_sections=list(REQUIRED_SECTIONS),
                is_complete=False,
                health_score=0.0,
                issues=[f"SKILL.md missing — create {skill_md.name} with required sections"],
            )

        # Parse file
        content = skill_md.read_text(errors="ignore")
        content_lower = content.lower()

        # Check sections
        missing = [
            section for section in REQUIRED_SECTIONS
            if not _section_present(content_lower, section)
        ]

        # Check staleness
        mtime = skill_md.stat().st_mtime
        last_modified = datetime.fromtimestamp(mtime)
        days_since = (datetime.now() - last_modified).days
        is_stale = days_since >= self.stale_days

        # Health score
        score = 1.0
        score -= len(missing) * _SECTION_DEDUCTION
        if is_stale:
            score -= _STALE_DEDUCTION
        score = round(max(0.0, min(1.0, score)), 4)

        # Issues
        issues: list[str] = []
        for section in missing:
            issues.append(f"Missing required section: {section}")
        if is_stale:
            issues.append(f"Stale: not updated in {days_since} day(s) (threshold: {self.stale_days})")

        return SkillHealthReport(
            skill_name=skill_name,
            has_skill_md=True,
            last_modified=last_modified,
            days_since_update=days_since,
            is_stale=is_stale,
            missing_sections=missing,
            is_complete=len(missing) == 0,
            health_score=score,
            issues=issues,
        )

    def get_stale_skills(self, days: int | None = None) -> list[SkillHealthReport]:
        """Return reports for skills not updated within the threshold.

        Args:
            days: Staleness threshold in days. Defaults to self.stale_days.
        """
        threshold = days if days is not None else self.stale_days
        original = self.stale_days
        self.stale_days = threshold
        try:
            reports = self.scan_all()
        finally:
            self.stale_days = original
        return [r for r in reports if r.is_stale]

    def get_incomplete_skills(self) -> list[SkillHealthReport]:
        """Return reports for skills with missing required sections."""
        return [r for r in self.scan_all() if not r.is_complete]

    def get_missing_skills(self) -> list[SkillHealthReport]:
        """Return reports for skill directories that have no SKILL.md."""
        return [r for r in self.scan_all() if not r.has_skill_md]

    def summary(self) -> dict:
        """Return aggregate health statistics across all skills.

        Keys:
            total: Total skill directories scanned.
            stale: Count of stale skills.
            incomplete: Count of skills missing required sections.
            missing_skill_md: Count of skill dirs without SKILL.md.
            avg_health_score: Mean health score (0.0 if no skills).
            healthy: Count of skills with health_score >= 0.8.
        """
        reports = self.scan_all()
        if not reports:
            return {
                "total": 0,
                "stale": 0,
                "incomplete": 0,
                "missing_skill_md": 0,
                "avg_health_score": 0.0,
                "healthy": 0,
            }

        total = len(reports)
        stale = sum(1 for r in reports if r.is_stale)
        incomplete = sum(1 for r in reports if not r.is_complete)
        missing_md = sum(1 for r in reports if not r.has_skill_md)
        avg_score = round(sum(r.health_score for r in reports) / total, 4)
        healthy = sum(1 for r in reports if r.health_score >= _HEALTHY_THRESHOLD)

        return {
            "total": total,
            "stale": stale,
            "incomplete": incomplete,
            "missing_skill_md": missing_md,
            "avg_health_score": avg_score,
            "healthy": healthy,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _section_present(content_lower: str, section: str) -> bool:
    """True if the section heading is present in the lowercased content.

    Matches the heading at the start of a line, with optional trailing
    whitespace. Case-insensitive (both sides already lowercased).
    """
    target = section.lower()
    for line in content_lower.splitlines():
        stripped = line.strip()
        if stripped == target or stripped.startswith(target + " ") or stripped.startswith(target + "\t"):
            return True
    return False
