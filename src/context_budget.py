"""
Context budget optimizer for memory retrieval.

Scores memories by a weighted composite of importance, recency,
access frequency, and confidence, then greedily packs the highest-
value memories into a fixed token budget.

No LLM calls. No external dependencies beyond the standard library.
"""

import math
from datetime import datetime
from typing import Any, Dict, List


# Composite score weights — must sum to 1.0
SCORE_WEIGHTS: Dict[str, float] = {
    "importance": 0.4,
    "recency": 0.3,
    "access_frequency": 0.2,
    "confidence": 0.1,
}

# Recency window: memories older than this many days score 0 for recency.
_RECENCY_WINDOW_DAYS = 90


def _parse_datetime(value: Any) -> datetime | None:
    """Best-effort ISO datetime parse. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


class ContextBudgetOptimizer:
    """Pack the most valuable memories into a token budget."""

    def __init__(self) -> None:
        self._stats = {
            "optimizations": 0,
            "total_selected": 0,
            "total_excluded": 0,
        }

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count from text.

        Heuristic: ceil(word_count * 1.3).
        Returns 0 for empty / whitespace-only input.
        """
        if not text or not text.strip():
            return 0
        word_count = len(text.split())
        return math.ceil(word_count * 1.3)

    # ------------------------------------------------------------------
    # Memory scoring
    # ------------------------------------------------------------------

    def score_memory(self, memory: Dict[str, Any]) -> float:
        """Return a composite score in [0, 1] for *memory*.

        Fields consulted (all optional, default 0.5 when missing):

        * ``importance`` or ``importance_score``  — expected 0-1
        * ``created`` or ``updated``              — recency (1.0 = today,
          linear decay to 0.0 at ``_RECENCY_WINDOW_DAYS``)
        * ``access_count``                        — normalised as
          min(count / 10, 1.0)
        * ``confidence`` or ``confidence_score``  — expected 0-1
        """
        importance = self._extract_importance(memory)
        recency = self._extract_recency(memory)
        access_freq = self._extract_access_frequency(memory)
        confidence = self._extract_confidence(memory)

        score = (
            SCORE_WEIGHTS["importance"] * importance
            + SCORE_WEIGHTS["recency"] * recency
            + SCORE_WEIGHTS["access_frequency"] * access_freq
            + SCORE_WEIGHTS["confidence"] * confidence
        )
        return score

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------

    def optimize(
        self, memories: List[Dict[str, Any]], budget_tokens: int
    ) -> Dict[str, Any]:
        """Greedy-pack *memories* into *budget_tokens*.

        Returns a dict with:
        * ``selected``         — memories that fit (score & tokens added)
        * ``excluded``         — memories that did not fit
        * ``total_tokens``     — tokens consumed by selected memories
        * ``budget_used_pct``  — 0-100 float
        * ``explanation``      — human-readable summary
        """
        # Edge: empty list
        if not memories:
            self._stats["optimizations"] += 1
            return {
                "selected": [],
                "excluded": [],
                "total_tokens": 0,
                "budget_used_pct": 0.0,
                "explanation": "No memories provided.",
            }

        # Edge: zero budget
        if budget_tokens <= 0:
            self._stats["optimizations"] += 1
            self._stats["total_excluded"] += len(memories)
            excluded = []
            for mem in memories:
                entry = dict(mem)
                entry["score"] = self.score_memory(mem)
                entry["tokens"] = self.estimate_tokens(
                    mem.get("content", "")
                )
                excluded.append(entry)
            return {
                "selected": [],
                "excluded": excluded,
                "total_tokens": 0,
                "budget_used_pct": 0.0,
                "explanation": "Budget is zero; all memories excluded.",
            }

        # Score and estimate tokens for every memory
        scored: List[Dict[str, Any]] = []
        for mem in memories:
            entry = dict(mem)
            entry["score"] = self.score_memory(mem)
            entry["tokens"] = self.estimate_tokens(mem.get("content", ""))
            scored.append(entry)

        # Sort descending by score
        scored.sort(key=lambda m: m["score"], reverse=True)

        selected: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []
        total_tokens = 0

        for entry in scored:
            if total_tokens + entry["tokens"] <= budget_tokens:
                selected.append(entry)
                total_tokens += entry["tokens"]
            else:
                excluded.append(entry)

        # Update cumulative stats
        self._stats["optimizations"] += 1
        self._stats["total_selected"] += len(selected)
        self._stats["total_excluded"] += len(excluded)

        budget_used_pct = (
            (total_tokens / budget_tokens) * 100.0 if budget_tokens > 0 else 0.0
        )

        explanation = (
            f"Selected {len(selected)} of {len(memories)} memories "
            f"({total_tokens} tokens, {budget_used_pct:.1f}% of budget)."
        )

        return {
            "selected": selected,
            "excluded": excluded,
            "total_tokens": total_tokens,
            "budget_used_pct": budget_used_pct,
            "explanation": explanation,
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, int]:
        """Return cumulative optimisation statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_importance(memory: Dict[str, Any]) -> float:
        val = memory.get("importance", memory.get("importance_score"))
        if val is None:
            return 0.5
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.5

    @staticmethod
    def _extract_recency(memory: Dict[str, Any]) -> float:
        """Linear decay: 1.0 today, 0.0 at 90 days ago."""
        dt = _parse_datetime(
            memory.get("updated", memory.get("created"))
        )
        if dt is None:
            return 0.5

        now = datetime.now()
        days_ago = (now - dt).total_seconds() / 86400.0
        if days_ago < 0:
            days_ago = 0.0

        recency = max(0.0, 1.0 - days_ago / _RECENCY_WINDOW_DAYS)
        return recency

    @staticmethod
    def _extract_access_frequency(memory: Dict[str, Any]) -> float:
        val = memory.get("access_count")
        if val is None:
            return 0.5
        try:
            count = float(val)
        except (ValueError, TypeError):
            return 0.5
        return min(count / 10.0, 1.0)

    @staticmethod
    def _extract_confidence(memory: Dict[str, Any]) -> float:
        val = memory.get("confidence", memory.get("confidence_score"))
        if val is None:
            return 0.5
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.5
