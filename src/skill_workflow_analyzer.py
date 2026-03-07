"""Skill workflow analyzer — detects common multi-skill sequences from provenance data.

Mines the skill_provenance table for skills that consistently co-occur in the
same session, surfaces them as suggested workflow shortcuts, and identifies
pairs that are effectively inseparable (always used together).

Usage:
    from memory_system.skill_workflow_analyzer import SkillWorkflowAnalyzer

    analyzer = SkillWorkflowAnalyzer()
    for seq in analyzer.get_suggested_workflows(min_sessions=3):
        print(seq.skills, "→", seq.session_count, "sessions")
"""

import itertools
import logging
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from memory_system.config import cfg
from memory_system.skill_provenance import SkillProvenanceTracker

logger = logging.getLogger(__name__)

_DEFAULT_MIN_SESSIONS = 2
_MAX_EXAMPLE_SESSIONS = 5


@dataclass
class SkillSequence:
    """A set of skills that co-occur frequently across sessions."""

    skills: list[str]
    session_count: int
    frequency: float           # fraction of all sessions containing these skills together
    example_sessions: list[str] = field(default_factory=list)


class SkillWorkflowAnalyzer:
    """Detect common multi-skill workflows from provenance data.

    Reads from the skill_provenance SQLite table. Works with any DB that
    already contains skill provenance records.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        # Ensure the skill_provenance table exists.
        self._provenance = SkillProvenanceTracker(db_path=self._db_path)
        self._conn = self._provenance._conn

    # ── Public API ────────────────────────────────────────────────────────

    def get_common_pairs(self, min_sessions: int = _DEFAULT_MIN_SESSIONS) -> list[SkillSequence]:
        """Return pairs of skills that co-occur in at least min_sessions sessions.

        Ordered by session_count descending.
        """
        return self._get_common_combos(size=2, min_sessions=min_sessions)

    def get_common_triples(self, min_sessions: int = _DEFAULT_MIN_SESSIONS) -> list[SkillSequence]:
        """Return triples of skills that co-occur in at least min_sessions sessions."""
        return self._get_common_combos(size=3, min_sessions=min_sessions)

    def get_suggested_workflows(
        self, min_sessions: int = _DEFAULT_MIN_SESSIONS
    ) -> list[SkillSequence]:
        """Return all common pairs and triples, ordered by session_count descending."""
        pairs = self.get_common_pairs(min_sessions=min_sessions)
        triples = self.get_common_triples(min_sessions=min_sessions)
        combined = pairs + triples
        return sorted(combined, key=lambda s: s.session_count, reverse=True)

    def get_skills_always_together(
        self, min_sessions: int = _DEFAULT_MIN_SESSIONS
    ) -> dict[str, list[str]]:
        """Return a mapping of skill → [skills always co-used with it].

        A skill B is "always together" with skill A if every session that
        contains A also contains B (and there are at least min_sessions sessions
        with A).
        """
        session_skills = self._load_session_skills()
        if not session_skills:
            return {}

        # Build inverted index: skill → set of sessions
        skill_sessions: dict[str, set[str]] = defaultdict(set)
        for session_id, skills in session_skills.items():
            for skill in skills:
                skill_sessions[skill].add(session_id)

        result: dict[str, list[str]] = {}
        for skill_a, sessions_a in skill_sessions.items():
            if len(sessions_a) < min_sessions:
                continue
            always_with = []
            for skill_b, sessions_b in skill_sessions.items():
                if skill_b == skill_a:
                    continue
                # B is always with A if sessions_a ⊆ sessions_b
                if sessions_a.issubset(sessions_b):
                    always_with.append(skill_b)
            if always_with:
                result[skill_a] = sorted(always_with)

        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _load_session_skills(self) -> dict[str, list[str]]:
        """Load all sessions as {session_id: [skill_name, ...]}."""
        rows = self._conn.execute(
            "SELECT session_id, skill_name FROM skill_provenance"
        ).fetchall()
        session_skills: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            skill = row["skill_name"]
            sid = row["session_id"]
            if skill not in session_skills[sid]:
                session_skills[sid].append(skill)
        return dict(session_skills)

    def _get_common_combos(self, size: int, min_sessions: int) -> list[SkillSequence]:
        """Find all skill combinations of `size` that appear in >= min_sessions sessions."""
        session_skills = self._load_session_skills()
        if not session_skills:
            return []

        total_sessions = len(session_skills)
        combo_sessions: dict[frozenset, list[str]] = defaultdict(list)

        for session_id, skills in session_skills.items():
            if len(skills) < size:
                continue
            for combo in itertools.combinations(sorted(skills), size):
                combo_sessions[frozenset(combo)].append(session_id)

        sequences = []
        for combo_set, session_ids in combo_sessions.items():
            count = len(session_ids)
            if count < min_sessions:
                continue
            sequences.append(
                SkillSequence(
                    skills=sorted(combo_set),
                    session_count=count,
                    frequency=round(count / total_sessions, 4),
                    example_sessions=session_ids[:_MAX_EXAMPLE_SESSIONS],
                )
            )

        return sorted(sequences, key=lambda s: s.session_count, reverse=True)
