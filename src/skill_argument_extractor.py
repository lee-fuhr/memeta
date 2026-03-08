"""Skill argument pattern extractor — mines session transcripts for recurring argument structures.

Scans user/assistant turn pairs to detect: counterpoints, objections, plan changes,
and agreements. Stores extracted patterns in a standalone SQLite table so they
accumulate across sessions.

Recurring patterns (same argument type across multiple sessions) indicate
structural friction the system keeps hitting. High plan-change rates indicate
productive back-and-forth. High collapse rates (short chains, quick concession)
may indicate the assistant was wrong and corrected.

Usage:
    from memory_system.skill_argument_extractor import ArgumentExtractor

    extractor = ArgumentExtractor()
    result = extractor.extract_and_store(transcript, session_id="abc123")

    for pattern in extractor.get_recurring_patterns(min_occurrences=3):
        print(f"{pattern['argument_type']}: {pattern['count']} times")
"""

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from memory_system.config import cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Argument type classification
# ---------------------------------------------------------------------------

_COUNTERPOINT_TRIGGERS = (
    "no, actually", "no,", "actually,", "not quite", "i disagree",
    "that's not right", "that's incorrect", "you're wrong",
)

_OBJECTION_TRIGGERS = (
    "wait,", "hold on", "but wait", "premature", "too early", "not yet",
    "i don't think", "i'm not sure", "are you sure", "why not",
)

_PLAN_CHANGE_TRIGGERS = (
    "revised plan", "let's change", "actually let's", "new plan",
    "instead,", "on second thought", "forget the", "scratch that",
    "let's start with just", "can we", "too much scope",
)

_AGREEMENT_TRIGGERS = (
    "agreed", "sounds good", "that works", "perfect,", "great idea",
    "you're right", "fair point", "good call", "good point",
)

_COLLAPSE_MAX_CHAIN = 2  # chains <= this are "collapsed quickly"


class ArgumentType(str, Enum):
    COUNTERPOINT = "counterpoint"
    OBJECTION = "objection"
    PLAN_CHANGE = "plan_change"
    AGREEMENT = "agreement"
    OTHER = "other"


@dataclass
class ArgumentPattern:
    """A single argument event extracted from a transcript."""

    pattern_id: str          # sha256[:16] of (session_id + trigger + position)
    argument_type: ArgumentType
    trigger_phrase: str      # phrase that matched the classification
    resolution: str          # "concede" | "escalate" | "defer" | "unknown"
    chain_length: int        # number of turns in the debate thread
    led_to_plan_change: bool
    session_id: str


@dataclass
class ExtractionResult:
    """Output of a single extract() call."""

    session_id: str
    patterns_found: int
    patterns: list = field(default_factory=list)
    plan_changes: int = 0


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class ArgumentExtractor:
    """Extract and store argument patterns from session transcripts.

    Each transcript is a list of dicts: {"role": "user"|"assistant", "content": str}.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ── Public API ────────────────────────────────────────────────────────

    def extract(
        self, transcript: list[dict], session_id: str
    ) -> ExtractionResult:
        """Extract argument patterns from a transcript without storing them."""
        if not transcript:
            return ExtractionResult(session_id=session_id, patterns_found=0)

        patterns = _extract_patterns(transcript, session_id)
        # Count plan changes from full transcript, not just classified patterns
        plan_changes = _count_plan_changes(transcript)

        return ExtractionResult(
            session_id=session_id,
            patterns_found=len(patterns),
            patterns=patterns,
            plan_changes=plan_changes,
        )

    def extract_and_store(
        self, transcript: list[dict], session_id: str
    ) -> ExtractionResult:
        """Extract patterns and persist to the database.

        Idempotent: clears existing rows for this session before inserting.
        """
        result = self.extract(transcript, session_id)

        # Remove old rows for this session, then insert fresh
        self._conn.execute(
            "DELETE FROM argument_patterns WHERE session_id = ?", (session_id,)
        )
        for p in result.patterns:
            self._conn.execute(
                """
                INSERT INTO argument_patterns
                    (pattern_id, session_id, argument_type, trigger_phrase,
                     resolution, chain_length, led_to_plan_change)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.pattern_id,
                    p.session_id,
                    p.argument_type.value,
                    p.trigger_phrase,
                    p.resolution,
                    p.chain_length,
                    1 if p.led_to_plan_change else 0,
                ),
            )
        self._conn.commit()
        return result

    def get_recurring_patterns(
        self, min_occurrences: int = 2
    ) -> list[dict]:
        """Return argument types that appear across multiple sessions.

        Returns list of dicts: {"argument_type", "count", "plan_change_count",
        "avg_chain_length"}, sorted by count descending.
        """
        rows = self._conn.execute(
            """
            SELECT
                argument_type,
                COUNT(*) AS count,
                SUM(led_to_plan_change) AS plan_change_count,
                ROUND(AVG(chain_length), 2) AS avg_chain_length
            FROM argument_patterns
            GROUP BY argument_type
            HAVING count >= ?
            ORDER BY count DESC
            """,
            (min_occurrences,),
        ).fetchall()

        return [
            {
                "argument_type": row["argument_type"],
                "count": row["count"],
                "plan_change_count": row["plan_change_count"] or 0,
                "avg_chain_length": row["avg_chain_length"] or 0.0,
            }
            for row in rows
        ]

    def get_plan_change_rate(self) -> float:
        """Fraction of stored patterns that led to a plan change."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, SUM(led_to_plan_change) AS changes FROM argument_patterns"
        ).fetchone()
        total = row["total"] or 0
        changes = row["changes"] or 0
        if total == 0:
            return 0.0
        return round(changes / total, 4)

    def get_collapse_rate(self) -> float:
        """Fraction of patterns with a short chain (quick collapse/concession)."""
        row = self._conn.execute(
            f"""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN chain_length <= {_COLLAPSE_MAX_CHAIN} THEN 1 ELSE 0 END) AS collapsed
            FROM argument_patterns
            """
        ).fetchone()
        total = row["total"] or 0
        collapsed = row["collapsed"] or 0
        if total == 0:
            return 0.0
        return round(collapsed / total, 4)

    # ── Internal ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS argument_patterns (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id        TEXT NOT NULL,
                session_id        TEXT NOT NULL,
                argument_type     TEXT NOT NULL,
                trigger_phrase    TEXT NOT NULL,
                resolution        TEXT NOT NULL,
                chain_length      INTEGER NOT NULL DEFAULT 1,
                led_to_plan_change INTEGER NOT NULL DEFAULT 0,
                extracted_at      TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ap_session ON argument_patterns(session_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ap_type ON argument_patterns(argument_type)"
        )
        self._conn.commit()


# ---------------------------------------------------------------------------
# Heuristic extraction logic
# ---------------------------------------------------------------------------

def _extract_patterns(
    transcript: list[dict], session_id: str
) -> list[ArgumentPattern]:
    """Scan transcript turns for argument markers and classify them."""
    patterns: list[ArgumentPattern] = []

    turns = [
        t for t in transcript
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
        and isinstance(t.get("content"), str)
    ]

    # Detect plan changes from the full transcript
    plan_change_positions: set[int] = set()
    for i, turn in enumerate(turns):
        text = turn["content"].lower()
        if _matches_any(text, _PLAN_CHANGE_TRIGGERS):
            plan_change_positions.add(i)

    # Scan for argument markers in user turns
    for i, turn in enumerate(turns):
        if turn["role"] != "user":
            continue

        text = turn["content"].lower()
        arg_type, trigger = _classify_turn(text)
        if arg_type == ArgumentType.OTHER:
            continue

        # Chain length: count subsequent turns until the thread resolves or runs out
        chain_length = _measure_chain(turns, i)

        # Resolution: look at the next assistant turn
        resolution = _classify_resolution(turns, i)

        # Did a plan change occur in the next 2 turns?
        nearby = {i, i + 1, i + 2}
        led_to_plan_change = bool(nearby & plan_change_positions)

        pattern_id = _make_id(session_id, trigger, i)

        patterns.append(
            ArgumentPattern(
                pattern_id=pattern_id,
                argument_type=arg_type,
                trigger_phrase=trigger,
                resolution=resolution,
                chain_length=chain_length,
                led_to_plan_change=led_to_plan_change,
                session_id=session_id,
            )
        )

    return patterns


def _classify_turn(text: str) -> tuple[ArgumentType, str]:
    """Return (ArgumentType, matched_trigger) for a turn's text."""
    for trigger in _COUNTERPOINT_TRIGGERS:
        if trigger in text:
            return ArgumentType.COUNTERPOINT, trigger
    for trigger in _OBJECTION_TRIGGERS:
        if trigger in text:
            return ArgumentType.OBJECTION, trigger
    for trigger in _AGREEMENT_TRIGGERS:
        if trigger in text:
            return ArgumentType.AGREEMENT, trigger
    return ArgumentType.OTHER, ""


def _measure_chain(turns: list[dict], start: int) -> int:
    """Count turns from start until role switches back to the starting role."""
    if start >= len(turns):
        return 1
    starting_role = turns[start]["role"]
    count = 1
    for turn in turns[start + 1:]:
        if turn["role"] == starting_role:
            break
        count += 1
    return max(1, count)


def _classify_resolution(turns: list[dict], trigger_idx: int) -> str:
    """Classify the resolution from the next assistant turn after the trigger."""
    for turn in turns[trigger_idx + 1:]:
        if turn["role"] == "assistant":
            text = turn["content"].lower()
            if _matches_any(text, ("you're right", "fair point", "good call",
                                   "good point", "okay,", "agreed")):
                return "concede"
            if _matches_any(text, ("but", "however", "disagree", "still think")):
                return "escalate"
            if _matches_any(text, ("let's defer", "for now", "later")):
                return "defer"
            return "unknown"
    return "unknown"


def _matches_any(text: str, triggers: tuple) -> bool:
    return any(t in text for t in triggers)


def _count_plan_changes(transcript: list[dict]) -> int:
    """Count turns that contain plan-change language."""
    count = 0
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        text = (turn.get("content") or "").lower()
        if _matches_any(text, _PLAN_CHANGE_TRIGGERS):
            count += 1
    return count


def _make_id(session_id: str, trigger: str, position: int) -> str:
    raw = f"{session_id}:{trigger}:{position}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
