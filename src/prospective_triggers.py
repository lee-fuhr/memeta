"""
Prospective memory triggers — event/topic/time-based memory surfacing.

Based on Einstein & McDaniel (1990) prospective memory research: remembering
to perform actions in the future, triggered by events or time.

Memories can carry "trigger conditions" — future events or contexts that
should cause the memory to surface:
- **Event-based:** "Surface this when user starts a session involving [project X]"
- **Topic-based:** "Remind about this when [topic Y] comes up in conversation"
- **Time-based:** "Flag this after [date Z]"

Triggers are extracted from conversation content via regex patterns that detect
intent phrases like "next time", "remember to", "don't forget", "when we get to".
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProspectiveTrigger:
    """A single prospective memory trigger attached to a memory."""

    trigger_id: int
    memory_id: str
    trigger_type: str       # 'event', 'topic', 'time'
    condition: dict         # e.g. {"project": "X"}, {"keywords": [...]}, {"after_date": "..."}
    status: str             # 'pending', 'fired', 'expired', 'dismissed'
    created_at: str
    fired_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Stopwords for keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "and", "or",
    "but", "is", "it", "be", "do", "we", "i", "you", "he", "she", "they",
    "this", "that", "with", "from", "as", "by", "not", "if", "so", "up",
    "out", "my", "our", "your", "its", "was", "are", "has", "had", "have",
    "will", "can", "should", "would", "could", "also", "just", "about",
    "me", "us", "them", "been", "did", "does", "done", "get", "got",
    "make", "than", "then", "when", "what", "which", "who", "how",
    "all", "each", "no", "any", "some", "more", "most", "very",
})


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ProspectiveTriggerManager:
    """
    Manages prospective memory triggers — extraction, storage, matching,
    and lifecycle (fire, dismiss, expire).
    """

    # Regex patterns that signal prospective intent in conversation text.
    TRIGGER_PATTERNS = [
        r"next time (?:we |I |you )?(.+?)(?:\.|$)",
        r"remember to (.+?)(?:\.|$)",
        r"don'?t forget (?:to )?(.+?)(?:\.|$)",
        r"when we (?:get to|start|work on) (.+?)(?:\.|$)",
        r"note for (?:when|next|future) (.+?)(?:\.|$)",
        r"TODO:? (.+?)(?:\.|$)",
    ]

    # Time-related keywords used by classify_trigger_type.
    _TIME_KEYWORDS = [
        "tomorrow", "next week", "next month", "next year",
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]

    # Pattern for explicit dates like "March 1st", "2026-03-15", etc.
    _DATE_PATTERN = re.compile(
        r"(?:after |by |before |on )?"
        r"(?:"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+\d{1,2}(?:st|nd|rd|th)?"
        r"|"
        r"\d{4}-\d{2}-\d{2}"
        r")",
        re.IGNORECASE,
    )

    # Month name → number mapping for date parsing.
    _MONTH_MAP = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the triggers table and indexes if they don't exist."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prospective_triggers (
                    trigger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    fired_at TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_triggers_status "
                "ON prospective_triggers(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_triggers_memory "
                "ON prospective_triggers(memory_id)"
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _row_to_trigger(self, row: tuple) -> ProspectiveTrigger:
        """Convert a database row to a ProspectiveTrigger."""
        return ProspectiveTrigger(
            trigger_id=row[0],
            memory_id=row[1],
            trigger_type=row[2],
            condition=json.loads(row[3]),
            status=row[4],
            created_at=row[5],
            fired_at=row[6],
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords from text, filtering stopwords."""
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", text.lower())
        return [w for w in words if w not in _STOPWORDS and len(w) > 1]

    def _parse_relative_date(self, text: str) -> Optional[str]:
        """
        Try to parse a relative or named date from text.
        Returns ISO date string or None.
        """
        text_lower = text.lower()
        now = datetime.now(timezone.utc)

        if "tomorrow" in text_lower:
            target = now + timedelta(days=1)
            return target.strftime("%Y-%m-%d")

        if "next week" in text_lower:
            target = now + timedelta(days=7)
            return target.strftime("%Y-%m-%d")

        if "next month" in text_lower:
            # Approximate: 30 days
            target = now + timedelta(days=30)
            return target.strftime("%Y-%m-%d")

        if "next year" in text_lower:
            target = now + timedelta(days=365)
            return target.strftime("%Y-%m-%d")

        # Try "Month Day" pattern (e.g., "March 1st")
        month_day = re.search(
            r"(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+(\d{1,2})",
            text_lower,
        )
        if month_day:
            month_name = month_day.group(1)
            day = int(month_day.group(2))
            month = self._MONTH_MAP[month_name]
            year = now.year
            # If the date has passed this year, use next year
            try:
                target = datetime(year, month, day, tzinfo=timezone.utc)
                if target < now:
                    target = datetime(year + 1, month, day, tzinfo=timezone.utc)
                return target.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Try ISO date (YYYY-MM-DD)
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if iso_match:
            return iso_match.group(1)

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_trigger_type(self, text: str) -> tuple[str, dict]:
        """
        Classify extracted text into a trigger_type and condition dict.

        Returns:
            (trigger_type, condition) where trigger_type is 'event', 'topic',
            or 'time', and condition contains the matching criteria.
        """
        text_lower = text.lower()

        # 1. Check for time-based triggers first
        parsed_date = self._parse_relative_date(text)
        if parsed_date:
            return "time", {"after_date": parsed_date}

        # Check for time keywords even without a parseable date
        for kw in self._TIME_KEYWORDS:
            if kw in text_lower:
                # Disambiguate "may" — only match as month name, not modal verb
                if kw == "may":
                    if not re.search(
                        r'(?:in|by|before|until|after)\s+may\b|\bmay\s+\d{1,2}\b',
                        text_lower,
                    ):
                        continue
                parsed = self._parse_relative_date(text)
                if parsed:
                    return "time", {"after_date": parsed}
                # Has time keyword but can't parse — still mark as time
                # with a best-effort date (7 days from now)
                fallback = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
                return "time", {"after_date": fallback}

        # 2. Check for event-based triggers (project references)
        project_match = re.search(
            r"(?:project|repo|repository|codebase|app|application)\s+(\S+)",
            text_lower,
        )
        if project_match:
            keywords = self._extract_keywords(text)
            return "event", {"keywords": keywords}

        # 3. Default: topic-based with keyword extraction
        keywords = self._extract_keywords(text)
        return "topic", {"keywords": keywords}

    def extract_triggers(self, text: str, memory_id: str) -> list[ProspectiveTrigger]:
        """
        Extract prospective triggers from text content using regex patterns.

        Scans text for intent phrases and creates triggers in the database.

        Args:
            text: Conversation text to scan.
            memory_id: The memory ID to associate triggers with.

        Returns:
            List of created ProspectiveTrigger objects.
        """
        created: list[ProspectiveTrigger] = []
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self._db_path)
        try:
            for pattern in self.TRIGGER_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    captured = match.group(1).strip()
                    if not captured:
                        continue

                    trigger_type, condition = self.classify_trigger_type(captured)

                    # Skip if no meaningful keywords extracted
                    if trigger_type in ("topic", "event") and not condition.get("keywords"):
                        continue

                    cursor = conn.execute(
                        "INSERT INTO prospective_triggers "
                        "(memory_id, trigger_type, condition, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (memory_id, trigger_type, json.dumps(condition), "pending", now),
                    )
                    conn.commit()
                    trigger_id = cursor.lastrowid

                    created.append(ProspectiveTrigger(
                        trigger_id=trigger_id,
                        memory_id=memory_id,
                        trigger_type=trigger_type,
                        condition=condition,
                        status="pending",
                        created_at=now,
                    ))
        finally:
            conn.close()

        return created

    def check_triggers(self, context: dict) -> list[ProspectiveTrigger]:
        """
        Check pending triggers against current session context.

        Args:
            context: Dict with optional keys:
                - project: Current project name
                - keywords: List of keywords from current session
                - current_date: Today's date as YYYY-MM-DD string

        Returns:
            List of matching triggers that should fire.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT trigger_id, memory_id, trigger_type, condition, "
                "status, created_at, fired_at "
                "FROM prospective_triggers WHERE status = 'pending'"
            ).fetchall()
        finally:
            conn.close()

        matched: list[ProspectiveTrigger] = []

        for row in rows:
            trigger = self._row_to_trigger(row)
            if self._trigger_matches(trigger, context):
                matched.append(trigger)

        return matched

    def _trigger_matches(self, trigger: ProspectiveTrigger, context: dict) -> bool:
        """Check if a single trigger matches the given context."""
        condition = trigger.condition

        if trigger.trigger_type == "time":
            after_date = condition.get("after_date")
            current_date = context.get("current_date")
            if after_date and current_date:
                return current_date >= after_date
            return False

        if trigger.trigger_type == "event":
            # Match by project name
            ctx_project = context.get("project", "")
            cond_project = condition.get("project", "")
            if cond_project and ctx_project:
                if ctx_project.lower() == cond_project.lower():
                    return True

            # Also match by keyword overlap
            return self._keywords_overlap(condition, context)

        if trigger.trigger_type == "topic":
            return self._keywords_overlap(condition, context)

        return False

    @staticmethod
    def _keywords_overlap(condition: dict, context: dict) -> bool:
        """Check if trigger keywords overlap with context keywords."""
        cond_kws = set(k.lower() for k in condition.get("keywords", []))
        ctx_kws = set(k.lower() for k in context.get("keywords", []))
        if not cond_kws or not ctx_kws:
            return False
        # Require at least one keyword match
        return bool(cond_kws & ctx_kws)

    def fire_trigger(self, trigger_id: int) -> None:
        """Mark a trigger as fired with current timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "UPDATE prospective_triggers SET status = 'fired', fired_at = ? "
                "WHERE trigger_id = ?",
                (now, trigger_id),
            )
            conn.commit()
        finally:
            conn.close()

    def dismiss_trigger(self, trigger_id: int) -> None:
        """Mark a trigger as dismissed by user."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "UPDATE prospective_triggers SET status = 'dismissed' "
                "WHERE trigger_id = ?",
                (trigger_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_triggers(self, limit: int = 20) -> list[ProspectiveTrigger]:
        """
        Return all pending triggers, ordered by creation time.

        Args:
            limit: Maximum number of triggers to return.

        Returns:
            List of pending ProspectiveTrigger objects.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT trigger_id, memory_id, trigger_type, condition, "
                "status, created_at, fired_at "
                "FROM prospective_triggers WHERE status = 'pending' "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        return [self._row_to_trigger(row) for row in rows]

    def expire_old_triggers(self, max_age_days: int = 90) -> int:
        """
        Expire pending triggers older than max_age_days.

        Only affects triggers with status='pending'. Already fired or
        dismissed triggers are left untouched.

        Args:
            max_age_days: Maximum age in days before expiration.

        Returns:
            Number of triggers expired.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.execute(
                "UPDATE prospective_triggers SET status = 'expired' "
                "WHERE status = 'pending' AND created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
