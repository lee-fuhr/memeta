"""Pull-based skill recommendation engine.

On-demand skill suggestions based on current task description.
Distinct from the push-based hooks (which fire automatically on triggers):
this is queried explicitly by the user or conductor.

Two signal sources, additively combined:
1. Keyword matching — skill name + SKILL.md "when to use" section
2. Usage history — past successful invocations with overlapping context

Usage:
    from memory_system.skill_recommender import SkillRecommender

    rec = SkillRecommender()
    results = rec.recommend("fix a bug in the auth module", top_k=5)
    print(rec.format_recommendations(results))
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

_SKILL_WHEN_TO_USE_MARKER = "## when to use"
_HISTORY_WINDOW = 90  # days of history to scan
_SUCCESS_OUTCOMES = frozenset({"success"})


@dataclass
class Recommendation:
    skill_name: str
    score: float
    reason: str


class SkillRecommender:
    """Pull-based skill recommendation engine.

    Combines keyword overlap (skill name + SKILL.md content) with
    usage history (past successful invocations in similar contexts).
    """

    def __init__(
        self,
        db_path: Union[str, Path] | None = None,
        skills_dir: Union[str, Path] | None = None,
    ):
        if db_path is None:
            from memory_system.config import MemorySystemConfig
            db_path = MemorySystemConfig().intelligence_db
        if skills_dir is None:
            from memory_system.config import cfg
            skills_dir = cfg.skills_dir
        self._db_path = Path(db_path)
        self._skills_dir = Path(skills_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(self, query: str, top_k: int = 5) -> list[Recommendation]:
        """Return top-k skill recommendations for the given task description.

        Args:
            query: Natural-language task description.
            top_k: Maximum results to return.

        Returns:
            list of Recommendation objects sorted by score descending.
            Empty list if query is blank or no skills directory.
        """
        query = query.strip()
        if not query:
            return []
        if not self._skills_dir.exists():
            return []

        # Filter stop words (len <= 2) to prevent spurious matches
        query_words = {w for w in query.lower().split() if len(w) > 2}
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}

        # Signal 1: keyword matching
        keyword_hits = self._keyword_scores(query_words)
        for skill_name, score in keyword_hits.items():
            scores[skill_name] = scores.get(skill_name, 0.0) + score
            reasons.setdefault(skill_name, []).append(f"keyword match: {query[:40]}")

        # Signal 2: usage history boost
        history_hits = self._history_scores(query_words)
        for skill_name, score in history_hits.items():
            scores[skill_name] = scores.get(skill_name, 0.0) + score
            reasons.setdefault(skill_name, []).append("past success")

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result = []
        for skill_name, score in ranked[:top_k]:
            reason = "; ".join(reasons.get(skill_name, []))
            result.append(Recommendation(skill_name=skill_name, score=score, reason=reason))
        return result

    def format_recommendations(self, recommendations: list[Recommendation]) -> str:
        """Format recommendations as a markdown list."""
        if not recommendations:
            return ""
        lines = ["**Recommended skills:**"]
        for rec in recommendations:
            lines.append(f"- **{rec.skill_name}** — {rec.reason} (score: {rec.score:.1f})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Signal sources
    # ------------------------------------------------------------------

    def _keyword_scores(self, query_words: set[str]) -> dict[str, float]:
        """Score each skill by keyword overlap with query."""
        scores: dict[str, float] = {}

        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_name = skill_dir.name

            # Name overlap (weight 1.0 per word)
            name_words = set(
                skill_name.lower().replace("-", " ").replace("_", " ").split()
            )
            score = float(len(query_words & name_words))

            # SKILL.md when-to-use section overlap (weight 0.5 per word)
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                try:
                    raw = skill_md.read_text(errors="ignore").lower()
                    when_idx = raw.find(_SKILL_WHEN_TO_USE_MARKER)
                    if when_idx >= 0:
                        section = raw[when_idx: when_idx + 600]
                    else:
                        section = raw[:600]
                    section_words = {w for w in section.split() if len(w) > 2}
                    score += len(query_words & section_words) * 0.5
                except OSError:
                    pass

            if score > 0:
                scores[skill_name] = score

        return scores

    def _history_scores(self, query_words: set[str]) -> dict[str, float]:
        """Score each skill by past successful invocations with context overlap.

        Returns empty dict if provenance table doesn't exist.
        """
        if not self._db_path.exists():
            return {}
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    f"""
                    SELECT skill_name, outcome, context_snippet
                    FROM skill_provenance
                    WHERE outcome IN ({','.join('?' * len(_SUCCESS_OUTCOMES))})
                      AND invoked_at >= datetime('now', '-{_HISTORY_WINDOW} days')
                    """,
                    list(_SUCCESS_OUTCOMES),
                ).fetchall()
            except sqlite3.OperationalError:
                # Table doesn't exist yet
                return {}
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Provenance score computation failed: %s", exc)
            return {}

        scores: dict[str, float] = {}
        for row in rows:
            context_words = set(str(row["context_snippet"]).lower().split())
            overlap = len(query_words & context_words)
            if overlap > 0:
                skill_name = row["skill_name"]
                scores[skill_name] = scores.get(skill_name, 0.0) + overlap * 0.3

        return scores
