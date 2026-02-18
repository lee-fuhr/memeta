"""
Intelligence orchestrator — the "memory brain stem"

Synthesizes signals from all wild/ features into 3-5 high-priority daily
signals. Each feature runs independently; the orchestrator reads their
outputs and produces a unified briefing.

Signal sources:
  - Dream synthesizer (cross-project insights)
  - Momentum tracker (session progress state)
  - Energy scheduler (optimal task timing)
  - Regret detector (decision patterns to avoid)
  - Frustration detector (emotional friction)

Usage:
    from memory_system.intelligence_orchestrator import IntelligenceOrchestrator

    orch = IntelligenceOrchestrator()
    text = orch.get_formatted_briefing()
    print(text)

CLI:
    python -m memory_system.intelligence_orchestrator
"""

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


INTELLIGENCE_DB = Path(__file__).parent.parent / "intelligence.db"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

class SignalType(Enum):
    """Categories of intelligence signals."""
    INSIGHT = "insight"        # Novel discovery, cross-project pattern
    WARNING = "warning"        # Regret pattern, risk signal
    STATUS = "status"          # Momentum, energy, trend
    SUGGESTION = "suggestion"  # Task timing, intervention
    ALERT = "alert"            # Frustration, stuck state


@dataclass
class Signal:
    """A single intelligence signal from a feature module."""
    signal_type: SignalType
    priority: str  # "high", "medium", "low"
    title: str
    detail: str
    source: str  # which module produced this

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type.value,
            "priority": self.priority,
            "title": self.title,
            "detail": self.detail,
            "source": self.source,
        }


@dataclass
class DailyBriefing:
    """Synthesized daily briefing from all signal sources."""
    signals: list[Signal]
    generated_at: datetime

    @property
    def is_empty(self) -> bool:
        return len(self.signals) == 0

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    def by_priority(self) -> dict[str, list[Signal]]:
        """Group signals by priority level."""
        result: dict[str, list[Signal]] = {"high": [], "medium": [], "low": []}
        for s in self.signals:
            result.setdefault(s.priority, []).append(s)
        return result

    def by_type(self) -> dict[SignalType, list[Signal]]:
        """Group signals by type."""
        result: dict[SignalType, list[Signal]] = {}
        for s in self.signals:
            result.setdefault(s.signal_type, []).append(s)
        return result


# ---------------------------------------------------------------------------
# Signal collectors — one per feature module
# ---------------------------------------------------------------------------

def _collect_dream_signals(db_path: Path) -> list[Signal]:
    """Collect signals from dream synthesizer."""
    try:
        from memory_system.wild.dream_synthesizer import DreamSynthesizer
        ds = DreamSynthesizer(db_path=str(db_path))
        syntheses = ds.get_morning_briefing(limit=3)
        signals = []
        for s in syntheses:
            signals.append(Signal(
                signal_type=SignalType.INSIGHT,
                priority="high" if s.novelty_score > 0.7 else "medium",
                title=s.title,
                detail=s.insight[:200],
                source="dream_synthesizer",
            ))
        return signals
    except Exception:
        return []


def _collect_momentum_signals(db_path: Path) -> list[Signal]:
    """Collect signals from momentum tracker."""
    try:
        from memory_system.wild.momentum_tracker import MomentumTracker
        mt = MomentumTracker(db_path=str(db_path))
        # Get recent session stats
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT session_id, momentum_score, state FROM momentum_tracking "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        except Exception:
            row = None
        finally:
            conn.close()

        if row:
            session_id, score, state = row
            if state in ("stuck", "spinning"):
                return [Signal(
                    signal_type=SignalType.ALERT,
                    priority="high",
                    title=f"Session momentum: {state}",
                    detail=f"Last session scored {score:.0f}/100 ({state}). Consider changing approach.",
                    source="momentum_tracker",
                )]
            elif state == "on_roll":
                return [Signal(
                    signal_type=SignalType.STATUS,
                    priority="low",
                    title="Strong momentum",
                    detail=f"Last session scored {score:.0f}/100. Keep the flow going.",
                    source="momentum_tracker",
                )]
        return []
    except Exception:
        return []


def _collect_energy_signals(db_path: Path) -> list[Signal]:
    """Collect signals from energy scheduler."""
    try:
        from memory_system.wild.energy_scheduler import EnergyScheduler
        es = EnergyScheduler(db_path=str(db_path))
        energy = es.get_current_energy_prediction()
        tasks = es.suggest_task_for_current_time()

        if energy and energy != "unknown" and tasks:
            return [Signal(
                signal_type=SignalType.SUGGESTION,
                priority="low",
                title=f"Energy: {energy}",
                detail=f"Good time for: {', '.join(tasks[:3])}",
                source="energy_scheduler",
            )]
        return []
    except Exception:
        return []


def _collect_regret_signals(db_path: Path) -> list[Signal]:
    """Collect signals from regret detector."""
    try:
        from memory_system.wild.regret_detector import RegretDetector
        rd = RegretDetector(db_path=str(db_path))
        stats = rd.get_regret_statistics()

        signals = []
        if stats.get("regret_rate", 0) > 0.3 and stats.get("total_decisions", 0) >= 3:
            signals.append(Signal(
                signal_type=SignalType.WARNING,
                priority="high",
                title="High regret rate",
                detail=f"{stats['regrets']}/{stats['total_decisions']} recent decisions regretted ({stats['regret_rate']:.0%}). Review patterns before next decision.",
                source="regret_detector",
            ))
        return signals
    except Exception:
        return []


def _collect_frustration_signals(db_path: Path) -> list[Signal]:
    """Collect signals from frustration detector."""
    try:
        from memory_system.wild.frustration_detector import FrustrationDetector
        fd = FrustrationDetector(db_path=str(db_path))
        trends = fd.get_recent_frustration_trends(days=7)

        if trends.get("average_frustration_score", 0) > 0.5:
            return [Signal(
                signal_type=SignalType.ALERT,
                priority="high",
                title="Elevated frustration",
                detail=f"7-day avg frustration: {trends['average_frustration_score']:.0%}. Top triggers: {', '.join(list(trends.get('signal_type_counts', {}).keys())[:3])}",
                source="frustration_detector",
            )]
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def collect_signals(db_path: Optional[Path] = None) -> list[Signal]:
    """Collect signals from all feature modules.

    Each collector runs independently and fails silently.
    Returns aggregated signal list.
    """
    db = db_path or INTELLIGENCE_DB
    collectors = [
        _collect_dream_signals,
        _collect_momentum_signals,
        _collect_energy_signals,
        _collect_regret_signals,
        _collect_frustration_signals,
    ]

    all_signals = []
    for collector in collectors:
        try:
            signals = collector(db)
            all_signals.extend(signals)
        except Exception:
            continue

    return all_signals


def synthesize_briefing(
    signals: list[Signal],
    max_signals: int = 10,
) -> DailyBriefing:
    """Synthesize collected signals into a prioritized daily briefing.

    Args:
        signals: Raw signals from all collectors
        max_signals: Maximum signals to include

    Returns:
        DailyBriefing sorted by priority (high → medium → low)
    """
    if not signals:
        return DailyBriefing(signals=[], generated_at=datetime.now(tz=timezone.utc))

    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_signals = sorted(
        signals,
        key=lambda s: priority_order.get(s.priority, 3),
    )

    return DailyBriefing(
        signals=sorted_signals[:max_signals],
        generated_at=datetime.now(tz=timezone.utc),
    )


def format_daily_briefing(briefing: DailyBriefing) -> str:
    """Format a DailyBriefing as human-readable text."""
    if briefing.is_empty:
        return "All quiet. No signals from intelligence modules."

    lines = [f"Intelligence briefing ({briefing.signal_count} signals):"]
    lines.append("")

    by_priority = briefing.by_priority()

    for priority in ("high", "medium", "low"):
        group = by_priority.get(priority, [])
        if not group:
            continue

        label = {"high": "Priority", "medium": "Notable", "low": "Info"}.get(priority, priority)
        lines.append(f"  [{label}]")
        for s in group:
            icon = {
                SignalType.INSIGHT: "💡",
                SignalType.WARNING: "⚠️",
                SignalType.STATUS: "📊",
                SignalType.SUGGESTION: "💬",
                SignalType.ALERT: "🚨",
            }.get(s.signal_type, "•")
            lines.append(f"    {icon} {s.title}")
            lines.append(f"      {s.detail}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class IntelligenceOrchestrator:
    """Central orchestrator for intelligence feature signals."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or INTELLIGENCE_DB
        self._init_db()

    def _init_db(self):
        """Create orchestrator tables if needed."""
        conn = sqlite3.connect(str(self.db_path))
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

    def generate_briefing(
        self,
        max_signals: int = 10,
        store: bool = False,
    ) -> DailyBriefing:
        """Generate daily briefing from all signal sources.

        Args:
            max_signals: Maximum signals to include
            store: Whether to persist to database

        Returns:
            DailyBriefing
        """
        signals = collect_signals(db_path=self.db_path)
        briefing = synthesize_briefing(signals, max_signals=max_signals)

        if store and not briefing.is_empty:
            self._store_briefing(briefing)

        return briefing

    def get_formatted_briefing(self, max_signals: int = 10) -> str:
        """Generate and format daily briefing."""
        briefing = self.generate_briefing(max_signals=max_signals)
        return format_daily_briefing(briefing)

    def _store_briefing(self, briefing: DailyBriefing) -> None:
        """Persist briefing to database."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            signals_json = json.dumps([s.to_dict() for s in briefing.signals])
            conn.execute(
                "INSERT INTO orchestrator_briefings (signals_json, generated_at) VALUES (?, ?)",
                (signals_json, int(briefing.generated_at.timestamp())),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Intelligence orchestrator")
    parser.add_argument("--store", action="store_true", help="Store briefing to database")
    parser.add_argument("--max", type=int, default=10, help="Max signals")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    orch = IntelligenceOrchestrator()
    briefing = orch.generate_briefing(max_signals=args.max, store=args.store)

    if args.json:
        print(json.dumps({
            "signals": [s.to_dict() for s in briefing.signals],
            "generated_at": briefing.generated_at.isoformat(),
            "signal_count": briefing.signal_count,
        }, indent=2))
    else:
        print(format_daily_briefing(briefing))


if __name__ == "__main__":
    main()
