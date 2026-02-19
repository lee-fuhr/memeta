"""Energy-aware memory loading.

Loads memories appropriate for the current time of day, prioritizing
different tag categories based on time windows (morning = strategy,
afternoon = tasks, evening = learning, night = unfiltered).

Usage:
    from memory_system.energy_aware_loading import EnergyAwareLoader

    loader = EnergyAwareLoader()
    memories = loader.load_context()
    print(loader.explain_loading())
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .memory_ts_client import MemoryTSClient, Memory


@dataclass
class TimeWindow:
    """Defines a time-of-day window with associated memory priorities."""
    name: str           # 'morning', 'afternoon', 'evening', 'night'
    start_hour: int     # inclusive
    end_hour: int       # exclusive
    priority_tags: List[str]
    sort_key: str       # 'importance' or 'created'
    sort_reverse: bool  # True = descending


class EnergyAwareLoader:
    """Loads memories filtered and ranked by time-of-day windows."""

    TIME_WINDOWS = [
        TimeWindow('morning', 6, 12,
                   ['#strategy', '#decision', '#framework', '#positioning', '#architecture'],
                   'importance', True),
        TimeWindow('afternoon', 12, 18,
                   ['#task', '#commitment', '#logistics', '#operational', '#admin'],
                   'created', True),
        TimeWindow('evening', 18, 24,
                   ['#learning', '#pattern', '#reflection', '#insight', '#mistake'],
                   'importance', True),
        TimeWindow('night', 0, 6,
                   [],  # No filtering -- maintenance window
                   'created', True),
    ]

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        override_hour: Optional[int] = None,
        max_memories: int = 20,
    ):
        """Initialize the energy-aware loader.

        Args:
            memory_dir: Path to memory storage directory.
                        Passed through to MemoryTSClient.
            override_hour: Force a specific hour (0-23) instead of
                           using the real clock. Useful for testing.
            max_memories: Maximum number of memories to return from
                          load_context().
        """
        self.client = MemoryTSClient(memory_dir=memory_dir)
        self.override_hour = override_hour
        self.max_memories = max_memories
        self._last_load_result: Optional[List[Dict]] = None
        self._last_window: Optional[TimeWindow] = None

    def _current_hour(self) -> int:
        """Return the hour to use for window selection."""
        if self.override_hour is not None:
            return self.override_hour
        return datetime.now().hour

    def get_current_window(self) -> TimeWindow:
        """Return the TimeWindow for the current hour (or override_hour)."""
        hour = self._current_hour()
        for window in self.TIME_WINDOWS:
            if window.start_hour <= hour < window.end_hour:
                return window
        # Fallback (should not happen with full 0-24 coverage)
        return self.TIME_WINDOWS[3]  # night

    def load_context(self) -> List[Dict]:
        """Load memories appropriate for the current time window.

        Logic:
        1. Get all active memories.
        2. Determine current time window.
        3. If night window: return all memories sorted by created desc,
           capped at max_memories.
        4. Otherwise:
           a. Score each memory: +2 if it has a priority tag, +importance
           b. Sort by score descending
           c. Return top max_memories

        Returns:
            List of memory dicts (not Memory objects).
        """
        memories = self.client.list()
        window = self.get_current_window()
        self._last_window = window

        if not memories:
            self._last_load_result = []
            return []

        if window.name == 'night':
            # Night: no filtering, sort by created descending
            sorted_mems = sorted(
                memories,
                key=lambda m: m.created,
                reverse=True,
            )
            result = [self._memory_to_dict(m) for m in sorted_mems[:self.max_memories]]
            self._last_load_result = result
            return result

        # Score each memory
        scored: List[tuple] = []  # (score, memory)
        for mem in memories:
            score = float(mem.importance)
            # Check if any of the memory's tags match priority tags
            if any(tag in window.priority_tags for tag in mem.tags):
                score += 2.0
            scored.append((score, mem))

        # Sort by score descending
        scored.sort(key=lambda pair: pair[0], reverse=True)

        result = [self._memory_to_dict(m) for _, m in scored[:self.max_memories]]
        self._last_load_result = result
        return result

    def explain_loading(self) -> str:
        """Return human-readable explanation of what was loaded and why."""
        window = self._last_window or self.get_current_window()
        loaded = self._last_load_result

        if loaded is None:
            # load_context hasn't been called yet, call it
            loaded = self.load_context()
            window = self._last_window

        lines = [
            f"Time window: {window.name} ({window.start_hour}:00-{window.end_hour}:00)",
        ]

        if window.priority_tags:
            lines.append(f"Priority tags: {', '.join(window.priority_tags)}")
        else:
            lines.append("Priority tags: none (unfiltered maintenance window)")

        lines.append(f"Memories loaded: {len(loaded)} (max {self.max_memories})")

        if loaded:
            priority_count = 0
            if window.priority_tags:
                for mem_dict in loaded:
                    if any(tag in window.priority_tags for tag in mem_dict.get('tags', [])):
                        priority_count += 1
                lines.append(f"With priority tags: {priority_count}")
                lines.append(f"Without priority tags: {len(loaded) - priority_count}")

        return "\n".join(lines)

    @staticmethod
    def _memory_to_dict(mem: Memory) -> Dict:
        """Convert a Memory dataclass to a plain dict."""
        return {
            'id': mem.id,
            'content': mem.content,
            'importance': mem.importance,
            'tags': mem.tags,
            'project_id': mem.project_id,
            'scope': mem.scope,
            'created': mem.created,
            'updated': mem.updated,
            'status': mem.status,
        }
