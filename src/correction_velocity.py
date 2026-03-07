"""Correction velocity metric — tracks how quickly corrections graduate to CLAUDE.md rules.

Measures pipeline health: how many corrections are stuck at low confirmation
counts, what fraction have graduated, and how long graduation takes on average.

Pipeline stages:
    new      — 0 confirmations, just detected
    pending  — 1 to (graduation_threshold - 1) confirmations, building evidence
    graduated — at or above graduation_threshold AND tagged #graduated

Usage:
    from memory_system.correction_velocity import CorrectionVelocityTracker

    tracker = CorrectionVelocityTracker()
    snap = tracker.get_snapshot()
    print(f"Graduation rate: {snap.graduation_rate:.0%}")
    print(f"Avg days to graduate: {snap.avg_days_to_graduate}")
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.memory_ts_client import Memory, MemoryTSClient

logger = logging.getLogger(__name__)

_DEFAULT_GRADUATION_THRESHOLD = 3
_DEFAULT_STUCK_DAYS = 30


@dataclass
class PipelineSnapshot:
    """Point-in-time view of the correction pipeline."""

    total: int
    graduated: int
    pending: int               # 1 to (threshold - 1) confirmations
    new: int                   # 0 confirmations
    graduation_rate: float     # graduated / total, or 0.0 if total == 0
    avg_days_to_graduate: Optional[float]  # mean(updated - created) for graduated mems


class CorrectionVelocityTracker:
    """Track how quickly corrections move from detection to CLAUDE.md graduation.

    Reads from the memory files used by MemoryTSClient — no extra database.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        memory_client: Optional[MemoryTSClient] = None,
        graduation_threshold: int = _DEFAULT_GRADUATION_THRESHOLD,
    ) -> None:
        if memory_client is not None:
            self._client = memory_client
        else:
            self._client = MemoryTSClient(
                memory_dir=memory_dir or cfg.project_memory_dir
            )
        self.graduation_threshold = graduation_threshold

    # ── Public API ────────────────────────────────────────────────────────

    def get_snapshot(self) -> PipelineSnapshot:
        """Return a point-in-time PipelineSnapshot of the correction pipeline."""
        corrections = self._get_corrections()
        total = len(corrections)

        if total == 0:
            return PipelineSnapshot(
                total=0,
                graduated=0,
                pending=0,
                new=0,
                graduation_rate=0.0,
                avg_days_to_graduate=None,
            )

        graduated_mems = [m for m in corrections if self._is_graduated(m)]
        pending_mems = [
            m for m in corrections
            if not self._is_graduated(m) and 0 < m.confirmations < self.graduation_threshold
        ]
        new_mems = [
            m for m in corrections
            if not self._is_graduated(m) and m.confirmations == 0
        ]

        graduation_rate = len(graduated_mems) / total
        avg_days = _avg_days_to_graduate(graduated_mems)

        return PipelineSnapshot(
            total=total,
            graduated=len(graduated_mems),
            pending=len(pending_mems),
            new=len(new_mems),
            graduation_rate=round(graduation_rate, 4),
            avg_days_to_graduate=avg_days,
        )

    def get_stuck_corrections(self, days: int = _DEFAULT_STUCK_DAYS) -> list[Memory]:
        """Return non-graduated corrections not updated within the past `days` days.

        Graduated corrections are never considered stuck.
        """
        cutoff = datetime.now() - timedelta(days=days)
        stuck = []
        for mem in self._get_corrections():
            if self._is_graduated(mem):
                continue
            updated = _parse_dt(mem.updated)
            if updated is None or updated < cutoff:
                stuck.append(mem)
        return stuck

    def graduation_rate(self) -> float:
        """Return the fraction of corrections that have graduated (0.0–1.0)."""
        corrections = self._get_corrections()
        if not corrections:
            return 0.0
        graduated = sum(1 for m in corrections if self._is_graduated(m))
        return round(graduated / len(corrections), 4)

    def stage_distribution(self) -> dict:
        """Return a dict mapping stage name → count.

        Keys: "new", "pending", "graduated". Returns {} if no corrections.
        """
        corrections = self._get_corrections()
        if not corrections:
            return {}

        dist = {"new": 0, "pending": 0, "graduated": 0}
        for mem in corrections:
            if self._is_graduated(mem):
                dist["graduated"] += 1
            elif mem.confirmations == 0:
                dist["new"] += 1
            else:
                dist["pending"] += 1
        return dist

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_corrections(self) -> list[Memory]:
        try:
            return [m for m in self._client.list() if m.context_type == "correction"]
        except Exception:
            logger.debug("Failed to load correction memories", exc_info=True)
            return []

    def _is_graduated(self, mem: Memory) -> bool:
        return "#graduated" in mem.tags


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_dt(value: str) -> Optional[datetime]:
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _avg_days_to_graduate(graduated: list[Memory]) -> Optional[float]:
    """Compute mean days from created to updated for graduated corrections."""
    if not graduated:
        return None
    deltas = []
    for mem in graduated:
        created = _parse_dt(mem.created)
        updated = _parse_dt(mem.updated)
        if created and updated:
            deltas.append((updated - created).total_seconds() / 86400)
    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 2)
