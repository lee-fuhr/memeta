"""
Tests for decision regret loop — real-time warning before repeating
regretted decisions.
"""

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory_system.decision_regret_loop import (
    DecisionRegretLoop,
    RegretWarning,
    DecisionCategory,
    categorize_decision,
    check_for_regret_patterns,
    format_regret_warning,
    get_regret_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create a temp intelligence.db with decision_outcomes table."""
    db = tmp_path / "intelligence.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE decision_outcomes (
            id TEXT PRIMARY KEY,
            decision_content TEXT NOT NULL,
            alternative TEXT,
            outcome TEXT CHECK(outcome IN ('good', 'bad', 'neutral')),
            regret_detected BOOLEAN DEFAULT FALSE,
            created_at INTEGER NOT NULL,
            corrected_at INTEGER
        )
    """)
    conn.execute("CREATE INDEX idx_decision_content ON decision_outcomes(decision_content)")
    conn.execute("CREATE INDEX idx_decision_regret ON decision_outcomes(regret_detected)")
    conn.commit()
    conn.close()
    return db


def _seed_decisions(db_path, decisions):
    """Seed decision_outcomes table.

    decisions: list of (content, outcome, regret_detected, alternative)
    """
    conn = sqlite3.connect(str(db_path))
    now = int(time.time())
    for content, outcome, regret, alt in decisions:
        did = str(uuid.uuid4())
        corrected = now if regret else None
        conn.execute(
            "INSERT INTO decision_outcomes (id, decision_content, alternative, outcome, regret_detected, created_at, corrected_at) VALUES (?,?,?,?,?,?,?)",
            (did, content, alt, outcome, regret, now - 86400, corrected),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DecisionCategory
# ---------------------------------------------------------------------------

class TestDecisionCategory:
    def test_creation(self):
        cat = DecisionCategory(
            category="tooling",
            keywords=["framework", "library", "tool"],
        )
        assert cat.category == "tooling"
        assert len(cat.keywords) == 3

    def test_matches_keyword(self):
        cat = DecisionCategory(
            category="hiring",
            keywords=["hire", "recruit", "candidate"],
        )
        assert cat.matches("Should we hire a contractor?")
        assert not cat.matches("Let's review the pipeline")


# ---------------------------------------------------------------------------
# RegretWarning
# ---------------------------------------------------------------------------

class TestRegretWarning:
    def test_creation(self):
        w = RegretWarning(
            decision="Use framework X",
            total_occurrences=5,
            regret_count=3,
            regret_rate=0.6,
            worst_outcome="Wasted 2 weeks on migration",
            alternative_suggested="Use framework Y",
        )
        assert w.regret_rate == 0.6
        assert w.is_high_risk

    def test_high_risk_threshold(self):
        w = RegretWarning("d", 4, 3, 0.75, None, None)
        assert w.is_high_risk  # >= 0.5

        w2 = RegretWarning("d", 10, 2, 0.2, None, None)
        assert not w2.is_high_risk  # < 0.5

    def test_to_dict(self):
        w = RegretWarning("d", 3, 2, 0.67, "bad", "alt")
        d = w.to_dict()
        assert d["decision"] == "d"
        assert d["regret_rate"] == 0.67
        assert "is_high_risk" in d


# ---------------------------------------------------------------------------
# categorize_decision
# ---------------------------------------------------------------------------

class TestCategorizeDecision:
    def test_categorizes_tooling(self):
        cat = categorize_decision("Let's use React for the frontend")
        assert cat is not None
        # Should match tooling or technology category

    def test_categorizes_process(self):
        cat = categorize_decision("Skip the code review for this PR")
        assert cat is not None

    def test_unknown_category(self):
        cat = categorize_decision("xyzzy plugh")
        # May return None or a general category
        # The point is it doesn't crash


# ---------------------------------------------------------------------------
# check_for_regret_patterns
# ---------------------------------------------------------------------------

class TestCheckForRegretPatterns:
    def test_no_decisions_returns_none(self, db_path):
        result = check_for_regret_patterns("Use framework X", db_path=db_path)
        assert result is None

    def test_detects_regret_pattern(self, db_path):
        _seed_decisions(db_path, [
            ("Use framework X for the project", "bad", True, "Use framework Y"),
            ("Use framework X again", "bad", True, "Use framework Y"),
            ("Use framework X once more", "neutral", False, None),
        ])
        result = check_for_regret_patterns("framework X", db_path=db_path)
        assert result is not None
        assert result.regret_count >= 2
        assert result.regret_rate > 0.5

    def test_no_regret_pattern_for_good_decisions(self, db_path):
        _seed_decisions(db_path, [
            ("Use framework Y", "good", False, None),
            ("Use framework Y again", "good", False, None),
        ])
        result = check_for_regret_patterns("framework Y", db_path=db_path)
        assert result is None

    def test_returns_alternative_from_history(self, db_path):
        _seed_decisions(db_path, [
            ("Skip testing", "bad", True, "Write tests first"),
            ("Skip testing this time", "bad", True, "Write tests first"),
        ])
        result = check_for_regret_patterns("Skip testing", db_path=db_path)
        assert result is not None
        assert result.alternative_suggested is not None

    def test_fuzzy_matching(self, db_path):
        _seed_decisions(db_path, [
            ("Delay the launch by a week", "bad", True, "Ship on time"),
            ("Push back the launch date", "bad", True, "Ship on time"),
        ])
        # Should match on "launch" keyword
        result = check_for_regret_patterns("delay the launch", db_path=db_path)
        assert result is not None


# ---------------------------------------------------------------------------
# format_regret_warning
# ---------------------------------------------------------------------------

class TestFormatRegretWarning:
    def test_formats_warning(self):
        w = RegretWarning(
            decision="Skip code review",
            total_occurrences=4,
            regret_count=3,
            regret_rate=0.75,
            worst_outcome="Shipped a critical bug",
            alternative_suggested="Always do code review",
        )
        text = format_regret_warning(w)
        assert "Skip code review" in text or "code review" in text.lower()
        assert "3" in text or "75%" in text
        assert len(text) > 20

    def test_formats_without_alternative(self):
        w = RegretWarning("decision", 3, 2, 0.67, None, None)
        text = format_regret_warning(w)
        assert len(text) > 0

    def test_none_returns_empty(self):
        text = format_regret_warning(None)
        assert text == ""


# ---------------------------------------------------------------------------
# get_regret_summary
# ---------------------------------------------------------------------------

class TestGetRegretSummary:
    def test_empty_db(self, db_path):
        summary = get_regret_summary(db_path=db_path)
        assert summary["total_decisions"] == 0
        assert summary["total_regrets"] == 0

    def test_with_data(self, db_path):
        _seed_decisions(db_path, [
            ("Decision A", "good", False, None),
            ("Decision B", "bad", True, "Alt B"),
            ("Decision C", "neutral", False, None),
        ])
        summary = get_regret_summary(db_path=db_path)
        assert summary["total_decisions"] == 3
        assert summary["total_regrets"] == 1

    def test_includes_top_regretted(self, db_path):
        _seed_decisions(db_path, [
            ("Skip testing", "bad", True, "Write tests"),
            ("Skip testing again", "bad", True, "Write tests"),
            ("Good decision", "good", False, None),
        ])
        summary = get_regret_summary(db_path=db_path)
        assert "top_regretted" in summary


# ---------------------------------------------------------------------------
# DecisionRegretLoop (main interface)
# ---------------------------------------------------------------------------

class TestDecisionRegretLoop:
    def test_init(self, db_path):
        loop = DecisionRegretLoop(db_path=db_path)
        assert loop is not None

    def test_check_decision_no_history(self, db_path):
        loop = DecisionRegretLoop(db_path=db_path)
        warning = loop.check_decision("Random new decision")
        assert warning is None

    def test_check_decision_with_regret(self, db_path):
        _seed_decisions(db_path, [
            ("Use quick hack instead of proper fix", "bad", True, "Do it properly"),
            ("Quick hack for the deadline", "bad", True, "Take time to do it right"),
        ])
        loop = DecisionRegretLoop(db_path=db_path)
        warning = loop.check_decision("quick hack")
        assert warning is not None
        assert warning.regret_count >= 1

    def test_get_formatted_warning(self, db_path):
        _seed_decisions(db_path, [
            ("Postpone the meeting", "bad", True, "Keep the meeting"),
            ("Delay the meeting again", "bad", True, "Keep the meeting"),
        ])
        loop = DecisionRegretLoop(db_path=db_path)
        text = loop.get_formatted_warning("postpone meeting")
        assert isinstance(text, str)

    def test_get_summary(self, db_path):
        _seed_decisions(db_path, [
            ("Decision X", "good", False, None),
        ])
        loop = DecisionRegretLoop(db_path=db_path)
        summary = loop.get_summary()
        assert summary["total_decisions"] >= 1
