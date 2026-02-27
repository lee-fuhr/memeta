"""Skill action tracker — tracks recurring action patterns and skill usage events.

Manages a JSON state file tracking action patterns (recurring user behaviors)
and logs skill usage events to the SQLite intelligence database.

Usage:
    from memory_system.wild.skill_action_tracker import SkillActionTracker

    tracker = SkillActionTracker()

    # Record an action occurrence
    pattern = tracker.record_action("create google doc with formatting", session_id="abc123")

    # Log skill usage
    tracker.record_skill_usage("google-docs-editor", session_id="abc123")

    # Get high-frequency patterns
    patterns = tracker.get_patterns(min_frequency=5)

    # Compute similarity between prompts
    sim = tracker.compute_prompt_similarity("create a doc", "create a page")
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.wild.intelligence_db import IntelligenceDB

STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "this", "that", "which", "who", "what", "where", "when", "how",
})


@dataclass
class ActionPattern:
    """A single tracked action pattern."""
    id: str
    action_signature: str
    canonical_form: str
    first_seen: str
    last_seen: str
    frequency: int
    daily_occurrences: dict[str, int]
    session_ids: list[str]
    mapped_skill: Optional[str] = None
    proposed_skill: Optional[str] = None


class SkillActionTracker:
    """Tracks recurring action patterns and logs skill usage events."""

    def __init__(
        self,
        state_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        self.state_path = Path(state_path) if state_path else cfg.skill_lifecycle_state_path
        self.db = IntelligenceDB(db_path)
        # Ensure state file exists with defaults
        self._load_state()

    def record_action(
        self,
        action_signature: str,
        session_id: str,
        canonical_form: Optional[str] = None,
    ) -> ActionPattern:
        """Record an action occurrence. Creates or updates pattern."""
        state = self._load_state()
        pattern_hash = self._generate_pattern_hash(action_signature)
        now_iso = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")

        if pattern_hash in state["action_patterns"]:
            entry = state["action_patterns"][pattern_hash]
            entry["frequency"] += 1
            entry["last_seen"] = now_iso
            entry["daily_occurrences"][today] = entry["daily_occurrences"].get(today, 0) + 1
            session_set = set(entry["session_ids"])
            session_set.add(session_id)
            entry["session_ids"] = sorted(session_set)
        else:
            canon = canonical_form or self._generate_canonical_form(action_signature)
            entry = {
                "id": pattern_hash,
                "action_signature": action_signature,
                "canonical_form": canon,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "frequency": 1,
                "daily_occurrences": {today: 1},
                "session_ids": [session_id],
                "mapped_skill": None,
                "proposed_skill": None,
            }
            if canonical_form:
                entry["canonical_form"] = canonical_form
            state["action_patterns"][pattern_hash] = entry

        self._save_state(state)
        return self._entry_to_pattern(entry)

    def record_skill_usage(
        self,
        skill_name: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Log a skill usage event to the skill_usage_events table."""
        self.db.conn.execute(
            "INSERT INTO skill_usage_events (skill_name, session_id, used_at) VALUES (?, ?, ?)",
            (skill_name, session_id, datetime.now().isoformat()),
        )
        self.db.conn.commit()

    def get_patterns(self, min_frequency: int = 1) -> list[ActionPattern]:
        """Get all patterns, optionally filtered by minimum frequency."""
        state = self._load_state()
        return [
            self._entry_to_pattern(entry)
            for entry in state["action_patterns"].values()
            if entry["frequency"] >= min_frequency
        ]

    def get_pattern(self, pattern_id: str) -> Optional[ActionPattern]:
        """Get a single pattern by ID."""
        state = self._load_state()
        entry = state["action_patterns"].get(pattern_id)
        if entry is None:
            return None
        return self._entry_to_pattern(entry)

    def extract_skill_invocations(self, session_messages: list[dict]) -> list[str]:
        """Extract skill names from session message data (looks for Skill tool use)."""
        skills: list[str] = []
        for msg in session_messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Skill"
                ):
                    skill_name = block.get("input", {}).get("skill")
                    if skill_name and skill_name not in skills:
                        skills.append(skill_name)
        return skills

    def compute_prompt_similarity(self, prompt_a: str, prompt_b: str) -> float:
        """Jaccard similarity on word tokens between two prompts."""
        tokens_a = set(prompt_a.lower().split())
        tokens_b = set(prompt_b.lower().split())
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def _generate_pattern_hash(self, action_signature: str) -> str:
        """Generate a deterministic hash for an action signature."""
        normalized = action_signature.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()

    def _generate_canonical_form(self, action_signature: str) -> str:
        """Generate a canonical form from an action signature.

        Lowercases, removes stop words, replaces spaces with underscores.
        """
        words = action_signature.lower().split()
        filtered = [w for w in words if w not in STOP_WORDS]
        canonical = "_".join(filtered)
        # Remove non-alphanumeric characters except underscores
        canonical = re.sub(r"[^a-z0-9_]", "", canonical)
        return canonical

    def _load_state(self) -> dict:
        """Load state from JSON file, creating default if missing."""
        if self.state_path.exists():
            with open(self.state_path) as f:
                return json.load(f)

        default_state = {
            "version": 1,
            "action_patterns": {},
            "processed_sessions": {},
        }
        self._save_state(default_state)
        return default_state

    def _save_state(self, state: dict) -> None:
        """Save state to JSON file with self-cleaning of entries older than 90 days."""
        state = self._self_clean(state)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _self_clean(self, state: dict, max_age_days: int = 90) -> dict:
        """Remove entries older than max_age_days based on last_seen."""
        cutoff = datetime.now() - timedelta(days=max_age_days)
        to_remove = []
        for pattern_id, entry in state.get("action_patterns", {}).items():
            try:
                last_seen = datetime.fromisoformat(entry["last_seen"])
                if last_seen < cutoff:
                    to_remove.append(pattern_id)
            except (KeyError, ValueError):
                continue
        for pid in to_remove:
            del state["action_patterns"][pid]
        return state

    @staticmethod
    def _entry_to_pattern(entry: dict) -> ActionPattern:
        """Convert a state dict entry to an ActionPattern dataclass."""
        return ActionPattern(
            id=entry["id"],
            action_signature=entry["action_signature"],
            canonical_form=entry["canonical_form"],
            first_seen=entry["first_seen"],
            last_seen=entry["last_seen"],
            frequency=entry["frequency"],
            daily_occurrences=entry["daily_occurrences"],
            session_ids=entry["session_ids"],
            mapped_skill=entry.get("mapped_skill"),
            proposed_skill=entry.get("proposed_skill"),
        )
