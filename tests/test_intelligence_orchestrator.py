"""
Tests for intelligence orchestrator — synthesizes signals from all wild features.
"""

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory_system.intelligence_orchestrator import (
    IntelligenceOrchestrator,
    Signal,
    DailyBriefing,
    SignalType,
    collect_signals,
    synthesize_briefing,
    format_daily_briefing,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create temp intelligence.db with required tables."""
    db = tmp_path / "intelligence.db"
    conn = sqlite3.connect(str(db))
    # Create tables needed by orchestrator
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orchestrator_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_type TEXT NOT NULL,
            priority TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orchestrator_briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signals_json TEXT NOT NULL,
            generated_at INTEGER NOT NULL,
            dismissed INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

class TestSignal:
    def test_creation(self):
        s = Signal(
            signal_type=SignalType.INSIGHT,
            priority="high",
            title="Cross-project pattern",
            detail="Found connection between client X and Y",
            source="dream_synthesizer",
        )
        assert s.signal_type == SignalType.INSIGHT
        assert s.priority == "high"

    def test_to_dict(self):
        s = Signal(
            signal_type=SignalType.WARNING,
            priority="medium",
            title="Regret pattern",
            detail="You've regretted this 3 times",
            source="regret_detector",
        )
        d = s.to_dict()
        assert d["signal_type"] == "warning"
        assert d["source"] == "regret_detector"

    def test_all_signal_types(self):
        for st in SignalType:
            s = Signal(signal_type=st, priority="low", title="t", detail="d", source="test")
            assert s.signal_type == st


# ---------------------------------------------------------------------------
# DailyBriefing
# ---------------------------------------------------------------------------

class TestDailyBriefing:
    def test_empty_briefing(self):
        b = DailyBriefing(signals=[], generated_at=datetime.now(tz=timezone.utc))
        assert b.is_empty
        assert b.signal_count == 0

    def test_non_empty(self):
        s = Signal(SignalType.INSIGHT, "high", "Title", "Detail", "src")
        b = DailyBriefing(signals=[s], generated_at=datetime.now(tz=timezone.utc))
        assert not b.is_empty
        assert b.signal_count == 1

    def test_by_priority(self):
        signals = [
            Signal(SignalType.INSIGHT, "low", "Low", "d", "src"),
            Signal(SignalType.WARNING, "high", "High", "d", "src"),
            Signal(SignalType.STATUS, "medium", "Med", "d", "src"),
        ]
        b = DailyBriefing(signals=signals, generated_at=datetime.now(tz=timezone.utc))
        by_priority = b.by_priority()
        assert by_priority["high"][0].title == "High"
        assert by_priority["medium"][0].title == "Med"
        assert by_priority["low"][0].title == "Low"

    def test_by_type(self):
        signals = [
            Signal(SignalType.INSIGHT, "high", "Insight", "d", "src"),
            Signal(SignalType.WARNING, "high", "Warning", "d", "src"),
            Signal(SignalType.INSIGHT, "low", "Insight2", "d", "src"),
        ]
        b = DailyBriefing(signals=signals, generated_at=datetime.now(tz=timezone.utc))
        by_type = b.by_type()
        assert len(by_type[SignalType.INSIGHT]) == 2
        assert len(by_type[SignalType.WARNING]) == 1


# ---------------------------------------------------------------------------
# collect_signals
# ---------------------------------------------------------------------------

class TestCollectSignals:
    @patch("memory_system.intelligence_orchestrator._collect_dream_signals")
    @patch("memory_system.intelligence_orchestrator._collect_momentum_signals")
    @patch("memory_system.intelligence_orchestrator._collect_energy_signals")
    @patch("memory_system.intelligence_orchestrator._collect_regret_signals")
    @patch("memory_system.intelligence_orchestrator._collect_frustration_signals")
    def test_aggregates_signals(self, frust, regret, energy, momentum, dream, db_path):
        dream.return_value = [Signal(SignalType.INSIGHT, "high", "Dream", "d", "dream")]
        momentum.return_value = [Signal(SignalType.STATUS, "medium", "Momentum", "d", "momentum")]
        energy.return_value = []
        regret.return_value = [Signal(SignalType.WARNING, "high", "Regret", "d", "regret")]
        frust.return_value = []

        signals = collect_signals(db_path=db_path)
        assert len(signals) == 3

    @patch("memory_system.intelligence_orchestrator._collect_dream_signals")
    @patch("memory_system.intelligence_orchestrator._collect_momentum_signals")
    @patch("memory_system.intelligence_orchestrator._collect_energy_signals")
    @patch("memory_system.intelligence_orchestrator._collect_regret_signals")
    @patch("memory_system.intelligence_orchestrator._collect_frustration_signals")
    def test_handles_collector_errors(self, frust, regret, energy, momentum, dream, db_path):
        dream.side_effect = Exception("broken")
        momentum.return_value = [Signal(SignalType.STATUS, "low", "OK", "d", "momentum")]
        energy.return_value = []
        regret.return_value = []
        frust.return_value = []

        signals = collect_signals(db_path=db_path)
        assert len(signals) == 1  # Only momentum, dream failed gracefully

    @patch("memory_system.intelligence_orchestrator._collect_dream_signals")
    @patch("memory_system.intelligence_orchestrator._collect_momentum_signals")
    @patch("memory_system.intelligence_orchestrator._collect_energy_signals")
    @patch("memory_system.intelligence_orchestrator._collect_regret_signals")
    @patch("memory_system.intelligence_orchestrator._collect_frustration_signals")
    def test_empty_when_all_fail(self, frust, regret, energy, momentum, dream, db_path):
        for mock in [dream, momentum, energy, regret, frust]:
            mock.side_effect = Exception("broken")

        signals = collect_signals(db_path=db_path)
        assert signals == []


# ---------------------------------------------------------------------------
# synthesize_briefing
# ---------------------------------------------------------------------------

class TestSynthesizeBriefing:
    def test_empty_signals(self):
        briefing = synthesize_briefing([])
        assert briefing.is_empty

    def test_sorts_by_priority(self):
        signals = [
            Signal(SignalType.INSIGHT, "low", "Low", "d", "src"),
            Signal(SignalType.WARNING, "high", "High", "d", "src"),
            Signal(SignalType.STATUS, "medium", "Med", "d", "src"),
        ]
        briefing = synthesize_briefing(signals)
        assert briefing.signals[0].priority == "high"
        assert briefing.signals[1].priority == "medium"
        assert briefing.signals[2].priority == "low"

    def test_limits_signals(self):
        signals = [Signal(SignalType.INSIGHT, "low", f"S{i}", "d", "src") for i in range(20)]
        briefing = synthesize_briefing(signals, max_signals=5)
        assert len(briefing.signals) == 5


# ---------------------------------------------------------------------------
# format_daily_briefing
# ---------------------------------------------------------------------------

class TestFormatDailyBriefing:
    def test_empty(self):
        b = DailyBriefing(signals=[], generated_at=datetime.now(tz=timezone.utc))
        text = format_daily_briefing(b)
        assert "quiet" in text.lower() or "nothing" in text.lower() or "no signals" in text.lower()

    def test_includes_signals(self):
        signals = [
            Signal(SignalType.INSIGHT, "high", "Cross-project insight", "Found pattern X", "dream"),
            Signal(SignalType.WARNING, "medium", "Regret pattern", "Avoid Y", "regret"),
        ]
        b = DailyBriefing(signals=signals, generated_at=datetime.now(tz=timezone.utc))
        text = format_daily_briefing(b)
        assert "Cross-project insight" in text
        assert "Regret pattern" in text

    def test_groups_by_priority(self):
        signals = [
            Signal(SignalType.INSIGHT, "high", "Important", "d", "src"),
            Signal(SignalType.STATUS, "low", "Minor", "d", "src"),
        ]
        b = DailyBriefing(signals=signals, generated_at=datetime.now(tz=timezone.utc))
        text = format_daily_briefing(b)
        # High should come before low in the output
        assert text.index("Important") < text.index("Minor")


# ---------------------------------------------------------------------------
# IntelligenceOrchestrator (main class)
# ---------------------------------------------------------------------------

class TestIntelligenceOrchestrator:
    def test_init(self, db_path):
        orch = IntelligenceOrchestrator(db_path=db_path)
        assert orch is not None

    @patch("memory_system.intelligence_orchestrator.collect_signals")
    def test_generate_briefing(self, mock_collect, db_path):
        mock_collect.return_value = [
            Signal(SignalType.INSIGHT, "high", "Test insight", "Detail", "dream"),
        ]
        orch = IntelligenceOrchestrator(db_path=db_path)
        briefing = orch.generate_briefing()
        assert not briefing.is_empty

    @patch("memory_system.intelligence_orchestrator.collect_signals")
    def test_get_formatted_briefing(self, mock_collect, db_path):
        mock_collect.return_value = [
            Signal(SignalType.WARNING, "high", "Watch out", "Details", "regret"),
        ]
        orch = IntelligenceOrchestrator(db_path=db_path)
        text = orch.get_formatted_briefing()
        assert "Watch out" in text

    @patch("memory_system.intelligence_orchestrator.collect_signals")
    def test_stores_briefing(self, mock_collect, db_path):
        mock_collect.return_value = [
            Signal(SignalType.STATUS, "low", "Status", "Detail", "momentum"),
        ]
        orch = IntelligenceOrchestrator(db_path=db_path)
        orch.generate_briefing(store=True)

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM orchestrator_briefings").fetchone()[0]
        conn.close()
        assert count == 1
