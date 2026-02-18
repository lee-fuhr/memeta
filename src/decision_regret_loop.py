"""
Decision regret loop — real-time warning before repeating regretted decisions.

Builds on the existing RegretDetector (F58) which records decisions and outcomes
retrospectively. This module adds a proactive layer: check incoming decisions
against the regret database and warn before repeating mistakes.

Key features:
  - Fuzzy keyword matching against historical decisions
  - Decision categorization for broader pattern matching
  - Formatted warnings with regret rate, count, and alternatives
  - Summary statistics for dashboard display

Usage:
    from memory_system.decision_regret_loop import DecisionRegretLoop

    loop = DecisionRegretLoop()

    # Check before making a decision
    warning = loop.check_decision("Skip testing for speed")
    if warning:
        print(format_regret_warning(warning))

    # Get summary for dashboard
    summary = loop.get_summary()
"""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

INTELLIGENCE_DB = Path(__file__).parent.parent / "intelligence.db"


# ---------------------------------------------------------------------------
# Decision categories for fuzzy matching
# ---------------------------------------------------------------------------

@dataclass
class DecisionCategory:
    """A category of decisions for fuzzy pattern matching."""
    category: str
    keywords: list[str]

    def matches(self, text: str) -> bool:
        """Check if text matches any keyword in this category."""
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.keywords)


# Default categories for common business/dev decisions
DEFAULT_CATEGORIES = [
    DecisionCategory("tooling", ["framework", "library", "tool", "plugin", "package", "sdk", "react", "vue", "angular"]),
    DecisionCategory("process", ["review", "skip", "bypass", "shortcut", "workaround", "hack", "defer", "postpone"]),
    DecisionCategory("timeline", ["delay", "rush", "deadline", "launch", "ship", "push back", "extend"]),
    DecisionCategory("hiring", ["hire", "recruit", "candidate", "contractor", "freelancer", "team"]),
    DecisionCategory("pricing", ["price", "discount", "rate", "cost", "fee", "charge", "quote"]),
    DecisionCategory("scope", ["scope", "feature", "requirement", "add", "remove", "cut", "expand"]),
    DecisionCategory("communication", ["email", "call", "meeting", "message", "follow up", "respond"]),
    DecisionCategory("delegation", ["delegate", "assign", "outsource", "hand off", "take on"]),
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class RegretWarning:
    """Warning about a potentially regrettable decision."""
    decision: str
    total_occurrences: int
    regret_count: int
    regret_rate: float
    worst_outcome: Optional[str]
    alternative_suggested: Optional[str]

    @property
    def is_high_risk(self) -> bool:
        """True if regret rate >= 50%."""
        return self.regret_rate >= 0.5

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "total_occurrences": self.total_occurrences,
            "regret_count": self.regret_count,
            "regret_rate": self.regret_rate,
            "worst_outcome": self.worst_outcome,
            "alternative_suggested": self.alternative_suggested,
            "is_high_risk": self.is_high_risk,
        }


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def categorize_decision(
    text: str,
    categories: Optional[list[DecisionCategory]] = None,
) -> Optional[DecisionCategory]:
    """Categorize a decision by matching against known categories.

    Args:
        text: Decision text to categorize
        categories: Custom categories (defaults to DEFAULT_CATEGORIES)

    Returns:
        Matching DecisionCategory or None
    """
    cats = categories or DEFAULT_CATEGORIES
    for cat in cats:
        if cat.matches(text):
            return cat
    return None


def check_for_regret_patterns(
    decision_text: str,
    db_path: Optional[Path] = None,
    min_occurrences: int = 2,
    min_regret_rate: float = 0.5,
) -> Optional[RegretWarning]:
    """Check if a decision matches historical regret patterns.

    Uses keyword extraction for fuzzy matching: extracts significant words
    from the input and searches for decisions containing those words.

    Args:
        decision_text: The decision being considered
        db_path: Path to intelligence.db
        min_occurrences: Minimum past occurrences to trigger warning
        min_regret_rate: Minimum regret rate to trigger warning

    Returns:
        RegretWarning if pattern found, None otherwise
    """
    db = db_path or INTELLIGENCE_DB
    if not Path(db).exists():
        return None

    # Extract significant keywords from the decision
    keywords = _extract_keywords(decision_text)
    if not keywords:
        return None

    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row

        # Search for decisions matching any keyword
        placeholders = " OR ".join(
            ["decision_content LIKE ?"] * len(keywords)
        )
        params = [f"%{kw}%" for kw in keywords]

        rows = conn.execute(
            f"""
            SELECT decision_content, outcome, regret_detected, alternative
            FROM decision_outcomes
            WHERE {placeholders}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()

        conn.close()

        if len(rows) < min_occurrences:
            return None

        total = len(rows)
        regrets = sum(1 for r in rows if r["regret_detected"])
        regret_rate = regrets / total if total > 0 else 0.0

        if regret_rate < min_regret_rate:
            return None

        # Find the best alternative from history
        alternatives = [
            r["alternative"] for r in rows
            if r["alternative"] and r["regret_detected"]
        ]
        best_alternative = alternatives[0] if alternatives else None

        # Find worst outcome
        bad_outcomes = [
            r["decision_content"] for r in rows
            if r["outcome"] == "bad"
        ]
        worst = bad_outcomes[0] if bad_outcomes else None

        return RegretWarning(
            decision=decision_text,
            total_occurrences=total,
            regret_count=regrets,
            regret_rate=round(regret_rate, 2),
            worst_outcome=worst,
            alternative_suggested=best_alternative,
        )
    except Exception:
        return None


def format_regret_warning(warning: Optional[RegretWarning]) -> str:
    """Format a RegretWarning as human-readable text.

    Args:
        warning: The warning to format (or None)

    Returns:
        Formatted warning string, or empty string if None
    """
    if warning is None:
        return ""

    lines = []
    pct = f"{warning.regret_rate:.0%}"
    lines.append(
        f"Regret warning: You've made this call {warning.total_occurrences} times. "
        f"{warning.regret_count} times you regretted it ({pct} regret rate)."
    )

    if warning.alternative_suggested:
        lines.append(f"  Consider instead: {warning.alternative_suggested}")

    if warning.worst_outcome:
        lines.append(f"  Previous bad outcome: {warning.worst_outcome}")

    return "\n".join(lines)


def get_regret_summary(db_path: Optional[Path] = None) -> dict:
    """Get summary statistics about decision regrets.

    Args:
        db_path: Path to intelligence.db

    Returns:
        Dict with total_decisions, total_regrets, regret_rate, top_regretted
    """
    db = db_path or INTELLIGENCE_DB
    if not Path(db).exists():
        return {
            "total_decisions": 0,
            "total_regrets": 0,
            "regret_rate": 0.0,
            "top_regretted": [],
        }

    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN regret_detected THEN 1 ELSE 0 END) as regrets
            FROM decision_outcomes
            """
        ).fetchone()

        total = row["total"]
        regrets = row["regrets"] or 0

        # Get top regretted decision patterns
        top = conn.execute(
            """
            SELECT decision_content, COUNT(*) as count
            FROM decision_outcomes
            WHERE regret_detected = TRUE
            GROUP BY decision_content
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        conn.close()

        return {
            "total_decisions": total,
            "total_regrets": regrets,
            "regret_rate": round(regrets / total, 2) if total > 0 else 0.0,
            "top_regretted": [
                {"decision": r["decision_content"], "count": r["count"]}
                for r in top
            ],
        }
    except Exception:
        return {
            "total_decisions": 0,
            "total_regrets": 0,
            "regret_rate": 0.0,
            "top_regretted": [],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common stop words to filter out during keyword extraction
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "through", "after", "before", "between", "out", "up", "down", "if",
    "or", "and", "but", "not", "no", "so", "than", "too", "very", "just",
    "that", "this", "it", "its", "my", "we", "our", "let", "us", "me",
    "i", "you", "he", "she", "they", "them", "what", "which", "who",
    "when", "where", "how", "all", "each", "every", "both", "few", "more",
    "some", "any", "most", "other", "new", "old", "also", "s", "t",
}


def _extract_keywords(text: str) -> list[str]:
    """Extract significant keywords from decision text.

    Filters out stop words and short words, returns keywords
    that are useful for fuzzy matching against historical decisions.
    """
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    keywords = [
        w for w in words
        if w not in _STOP_WORDS and len(w) >= 3
    ]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:5]  # Limit to 5 most significant


# ---------------------------------------------------------------------------
# Main interface class
# ---------------------------------------------------------------------------

class DecisionRegretLoop:
    """Main interface for real-time decision regret warnings."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or INTELLIGENCE_DB

    def check_decision(self, decision_text: str) -> Optional[RegretWarning]:
        """Check a decision against historical regret patterns.

        Args:
            decision_text: The decision being considered

        Returns:
            RegretWarning if pattern found, None if safe
        """
        return check_for_regret_patterns(decision_text, db_path=self.db_path)

    def get_formatted_warning(self, decision_text: str) -> str:
        """Get a formatted warning for a decision.

        Args:
            decision_text: The decision being considered

        Returns:
            Warning text or empty string if no pattern found
        """
        warning = self.check_decision(decision_text)
        return format_regret_warning(warning)

    def get_summary(self) -> dict:
        """Get regret summary statistics."""
        return get_regret_summary(db_path=self.db_path)
