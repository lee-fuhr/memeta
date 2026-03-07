"""Session-start briefing — unified context card injected at session start.

Combines top memories, active corrections, open commitments, and skill
recommendations into a single markdown block: "where was I and what
should I be thinking about."

Usage:
    from memory_system.session_briefing import SessionBriefing

    briefing = SessionBriefing()
    brief = briefing.generate(topic="debugging the memory injector")
    if brief:
        print(brief)
"""

import logging
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.memory_injector import load_search_index, search_memories
from memory_system.skill_antipattern_miner import SkillAntiPatternMiner

logger = logging.getLogger(__name__)

_SKILL_WHEN_TO_USE_MARKER = "## when to use"
_MAX_CONTENT_LEN = 200


class SessionBriefing:
    """Unified session-start context card.

    Combines:
    - Top relevant memories (BM25 search against topic)
    - Active corrections (sorted by importance)
    - Open commitments (from ProspectiveTriggerManager)
    - Skill recommendations (keyword overlap with topic)
    """

    def __init__(
        self,
        db_path=None,
        index_path=None,
        skills_dir=None,
    ):
        self.db_path = str(db_path or cfg.intelligence_db_path)
        self.index_path = Path(index_path) if index_path else None
        self.skills_dir = Path(skills_dir) if skills_dir else cfg.skills_dir

    # ── Public API ────────────────────────────────────────────────────────

    def generate(
        self,
        topic: str = "",
        context: Optional[dict] = None,
        max_memories: int = 3,
        max_corrections: int = 3,
        max_commitments: int = 3,
        max_skills: int = 3,
        max_antipatterns: int = 3,
        min_antipattern_risk: str = "medium",
    ) -> str:
        """Generate a session-start briefing block.

        Args:
            topic: Current session topic or task description.
            context: Context dict for commitment scoring. Recognized keys:
                current_date (str YYYY-MM-DD), keywords (list[str]),
                importance_map (dict mapping memory_id to float).
            max_memories: Max relevant memories to include.
            max_corrections: Max active corrections to include.
            max_commitments: Max open commitments to include.
            max_skills: Max skill recommendations to include.
            max_antipatterns: Max anti-pattern alerts to include.
            min_antipattern_risk: Minimum risk level to surface ("low", "medium", "high").

        Returns:
            Formatted markdown briefing string, or empty string if nothing to show.
        """
        context = context or {}
        memories = self.get_top_memories(topic, max_memories)
        corrections = self.get_active_corrections(max_corrections)
        commitments = self.get_open_commitments(context, max_commitments)
        skills = self.get_skill_recommendations(topic, max_skills)
        antipatterns = self.get_antipattern_alerts(max_antipatterns, min_antipattern_risk)
        return self.format_brief(memories, corrections, commitments, skills, antipatterns)

    # ── Sources ───────────────────────────────────────────────────────────

    def get_antipattern_alerts(
        self,
        top_k: int = 3,
        min_risk: str = "medium",
    ) -> list[dict]:
        """Return high-risk anti-pattern alerts for session-start awareness.

        Args:
            top_k:    Maximum number of alerts to return.
            min_risk: Minimum risk level to include ("low", "medium", "high").

        Returns:
            List of dicts with keys: skill_name, risk_level, co_occurrence_rate,
            co_occurrence_count, sample_corrections.
        """
        _RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
        min_level = _RISK_ORDER.get(min_risk, 2)

        try:
            miner = SkillAntiPatternMiner(db_path=self.db_path)
            reports = miner.analyze()
            alerts = [
                {
                    "skill_name": r.skill_name,
                    "risk_level": r.risk_level,
                    "co_occurrence_rate": r.co_occurrence_rate,
                    "co_occurrence_count": r.co_occurrence_count,
                    "sample_corrections": r.sample_corrections,
                }
                for r in reports
                if _RISK_ORDER.get(r.risk_level, 0) >= min_level
            ]
            return alerts[:top_k]
        except Exception:
            logger.debug("session_briefing: anti-pattern fetch failed", exc_info=True)
            return []

    def get_top_memories(self, topic: str, top_k: int = 3) -> list[dict]:
        """Return top-k topic-relevant memories (corrections excluded).

        Returns empty list if topic is blank or no index exists.
        """
        if not topic or not topic.strip():
            return []

        all_memories = load_search_index(self.index_path)
        non_corrections = [
            m for m in all_memories if m.get("context_type") != "correction"
        ]
        if not non_corrections:
            return []

        return search_memories(
            query=topic,
            memories=non_corrections,
            top_k=top_k,
            index_path=self.index_path,
        )

    def get_active_corrections(self, limit: int = 3) -> list[dict]:
        """Return most important active corrections from the memory index.

        Sorted by importance descending. Returns empty list if index missing.
        """
        all_memories = load_search_index(self.index_path)
        corrections = [
            m for m in all_memories if m.get("context_type") == "correction"
        ]
        corrections.sort(key=lambda m: m.get("importance", 0.5), reverse=True)
        return corrections[:limit]

    def get_open_commitments(self, context: dict, limit: int = 3) -> list[dict]:
        """Return top-N pending commitments scored by urgency.

        Returns empty list on any error (missing DB, bad schema, etc.).
        """
        try:
            from memory_system.commitment_nudger import get_top_commitments
            return get_top_commitments(self.db_path, context, limit=limit)
        except Exception:
            logger.debug(
                "Commitment retrieval failed — returning empty list",
                exc_info=True,
            )
            return []

    def get_skill_recommendations(self, topic: str, top_k: int = 3) -> list[str]:
        """Return skill names that match the topic by keyword overlap.

        Scores each skill on:
        - Name word overlap with topic (weight 1.0 per word)
        - When-to-use section overlap (weight 0.1 per word)

        Returns empty list if topic is blank or skills directory is missing.
        """
        if not topic or not topic.strip():
            return []
        if not self.skills_dir.exists():
            return []

        topic_words = set(topic.lower().split())
        matches: list[tuple[str, float]] = []

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_name = skill_dir.name
            name_words = set(
                skill_name.lower().replace("-", " ").replace("_", " ").split()
            )
            score = float(len(topic_words & name_words))

            # Boost from SKILL.md when-to-use section
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                try:
                    raw = skill_md.read_text(errors="ignore").lower()
                    when_idx = raw.find(_SKILL_WHEN_TO_USE_MARKER)
                    if when_idx >= 0:
                        when_section = raw[when_idx: when_idx + 500]
                    else:
                        when_section = raw[:500]
                    when_words = set(when_section.split())
                    score += len(topic_words & when_words) * 0.1
                except OSError:
                    pass

            if score > 0:
                matches.append((skill_name, score))

        matches.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in matches[:top_k]]

    # ── Formatting ────────────────────────────────────────────────────────

    def format_brief(
        self,
        memories: list[dict],
        corrections: list[dict],
        commitments: list[dict],
        skills: list[str],
        antipatterns: Optional[list[dict]] = None,
    ) -> str:
        """Format all components into a single markdown briefing block.

        Section order: corrections → commitments → anti-pattern alerts → memories → skills.
        Sections are omitted if they have no renderable content.
        Returns empty string if all sections are empty.
        """
        antipatterns = antipatterns or []
        sections: list[str] = []

        # Corrections first — behavioral, highest priority
        corr_lines = self._format_corrections_section(corrections)
        if corr_lines:
            sections.append(corr_lines)

        # Commitments second — time-sensitive
        comm_lines = self._format_commitments_section(commitments)
        if comm_lines:
            sections.append(comm_lines)

        # Anti-pattern alerts third — skill risk signals
        ap_lines = self._format_antipatterns_section(antipatterns)
        if ap_lines:
            sections.append(ap_lines)

        # Relevant memories fourth
        mem_lines = self._format_memories_section(memories)
        if mem_lines:
            sections.append(mem_lines)

        # Skills last — advisory
        skill_lines = self._format_skills_section(skills)
        if skill_lines:
            sections.append(skill_lines)

        if not sections:
            return ""
        return "# Session brief\n\n" + "\n\n".join(sections)

    def is_empty(self, brief: str) -> bool:
        """True if the brief has no actual content."""
        return not brief or not brief.strip()

    # ── Private formatters ────────────────────────────────────────────────

    def _format_corrections_section(self, corrections: list[dict]) -> str:
        lines = ["## Active corrections"]
        for c in corrections:
            content = c.get("content", "").strip()
            if content:
                lines.append(f"- {content[:_MAX_CONTENT_LEN]}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_commitments_section(self, commitments: list[dict]) -> str:
        lines = ["## Open commitments"]
        for item in commitments:
            trigger = item.get("trigger")
            reason = item.get("reason", "")
            if trigger is not None:
                summary = _summarize_trigger(trigger)
                line = f"- {summary}"
                if reason:
                    line += f" ({reason})"
                lines.append(line)
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_memories_section(self, memories: list[dict]) -> str:
        lines = ["## Relevant memories"]
        for m in memories:
            content = m.get("content", "").strip()
            if content:
                lines.append(f"> {content[:_MAX_CONTENT_LEN]}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _format_antipatterns_section(self, antipatterns: list[dict]) -> str:
        if not antipatterns:
            return ""
        lines = ["## Skill risk alerts"]
        for ap in antipatterns:
            skill = ap.get("skill_name", "")
            risk = ap.get("risk_level", "")
            rate = ap.get("co_occurrence_rate", 0.0)
            pct = int(rate * 100)
            lines.append(f"- **{skill}** [{risk} risk] — corrections in {pct}% of sessions")
        return "\n".join(lines)

    def _format_skills_section(self, skills: list[str]) -> str:
        if not skills:
            return ""
        lines = ["## Recommended skills"]
        for s in skills:
            lines.append(f"- /{s}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _summarize_trigger(trigger) -> str:
    """One-line summary of a ProspectiveTrigger's condition."""
    if hasattr(trigger, "trigger_type") and hasattr(trigger, "condition"):
        if trigger.trigger_type == "time":
            date = trigger.condition.get("after_date", "?")
            return f"time trigger (after {date})"
        keywords = trigger.condition.get("keywords", [])
        if keywords:
            return ", ".join(str(k) for k in keywords[:5])
        return f"{trigger.trigger_type} trigger"
    return str(trigger)
