"""Skill anti-pattern miner — detects skills correlated with corrections.

When a correction appears in a session that also invoked a specific skill,
it's a signal the skill may have led the user astray. Enough co-occurrences
and the skill gets flagged as a potential anti-pattern contributor.

This closes the loop between the correction pipeline and the skill roster:
skills that reliably precede corrections can be reviewed or retired.

Usage:
    from memory_system.skill_antipattern_miner import SkillAntiPatternMiner

    miner = SkillAntiPatternMiner()
    for report in miner.analyze(min_co_occurrences=2):
        print(f"{report.skill_name}: {report.risk_level} risk "
              f"({report.co_occurrence_count} co-occurrences)")

    flagged = miner.get_flagged_skills()
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.memory_ts_client import Memory, MemoryTSClient
from memory_system.skill_provenance import SkillProvenanceTracker

logger = logging.getLogger(__name__)

_DEFAULT_MIN_CO_OCCURRENCES = 2
_MAX_SAMPLE_CORRECTIONS = 3

# Risk thresholds (co_occurrence_rate)
_HIGH_RISK_RATE = 0.6
_MEDIUM_RISK_RATE = 0.3


@dataclass
class AntiPatternReport:
    """Anti-pattern signal for a single skill."""

    skill_name: str
    co_occurrence_count: int          # sessions with both this skill and a correction
    total_sessions: int               # total sessions where this skill was invoked
    co_occurrence_rate: float         # co_occurrence_count / total_sessions
    sample_corrections: list[str]     # up to 3 correction contents
    risk_level: str                   # "none", "low", "medium", "high"


class SkillAntiPatternMiner:
    """Correlate skill invocations with corrections in the same session.

    Joins:
        skill_provenance (session_id → skill) with
        correction memories (source_session_id → correction text)

    Skills that frequently appear in sessions where corrections occur
    are surfaced with a risk_level rating.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        memory_dir: Optional[Path] = None,
        memory_client: Optional[MemoryTSClient] = None,
    ) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._provenance = SkillProvenanceTracker(db_path=self._db_path)

        if memory_client is not None:
            self._memory_client = memory_client
        else:
            self._memory_client = MemoryTSClient(
                memory_dir=memory_dir or cfg.project_memory_dir
            )

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(
        self, min_co_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES
    ) -> list[AntiPatternReport]:
        """Return AntiPatternReports for skills with frequent correction co-occurrences.

        Args:
            min_co_occurrences: Minimum number of sessions where both the skill
                and a correction appear before the skill is reported.

        Returns:
            List of AntiPatternReport, sorted by co_occurrence_count descending.
        """
        corrections_by_session = self._load_corrections_by_session()
        if not corrections_by_session:
            return []

        # Build: skill → {session_id: [correction_contents]}
        skill_co_data: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        all_sessions_per_skill: dict[str, set[str]] = defaultdict(set)

        rows = self._provenance._conn.execute(
            "SELECT skill_name, session_id FROM skill_provenance"
        ).fetchall()

        for row in rows:
            skill = row["skill_name"]
            sid = row["session_id"]
            all_sessions_per_skill[skill].add(sid)
            if sid in corrections_by_session:
                for correction in corrections_by_session[sid]:
                    skill_co_data[skill][sid].append(correction)

        reports = []
        for skill, session_corrections in skill_co_data.items():
            co_count = len(session_corrections)
            if co_count < min_co_occurrences:
                continue

            total = len(all_sessions_per_skill[skill])
            rate = co_count / total if total > 0 else 0.0

            # Collect unique sample corrections (up to max)
            samples: list[str] = []
            seen: set[str] = set()
            for corrections in session_corrections.values():
                for c in corrections:
                    if c not in seen:
                        seen.add(c)
                        samples.append(c)
                    if len(samples) >= _MAX_SAMPLE_CORRECTIONS:
                        break
                if len(samples) >= _MAX_SAMPLE_CORRECTIONS:
                    break

            reports.append(
                AntiPatternReport(
                    skill_name=skill,
                    co_occurrence_count=co_count,
                    total_sessions=total,
                    co_occurrence_rate=round(rate, 4),
                    sample_corrections=samples,
                    risk_level=_risk_level(rate),
                )
            )

        return sorted(reports, key=lambda r: r.co_occurrence_count, reverse=True)

    def get_flagged_skills(
        self, min_co_occurrences: int = _DEFAULT_MIN_CO_OCCURRENCES
    ) -> list[str]:
        """Return just the skill names from analyze(), in the same order."""
        return [r.skill_name for r in self.analyze(min_co_occurrences=min_co_occurrences)]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _load_corrections_by_session(self) -> dict[str, list[str]]:
        """Return {session_id: [correction_content, ...]} from memory files."""
        result: dict[str, list[str]] = defaultdict(list)
        try:
            memories = self._memory_client.list()
        except Exception:
            logger.debug("Failed to load memories", exc_info=True)
            return {}
        for mem in memories:
            if mem.context_type != "correction":
                continue
            sid = mem.source_session_id
            if sid:
                result[sid].append(mem.content)
        return dict(result)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _risk_level(rate: float) -> str:
    if rate >= _HIGH_RISK_RATE:
        return "high"
    if rate >= _MEDIUM_RISK_RATE:
        return "medium"
    if rate > 0.0:
        return "low"
    return "none"
