"""FSRS context-relevance weighting.

Combines two independent signals when recalling memories:
1. FSRS score — time-based review urgency (is this memory due?)
2. Context relevance score — content-based match (is it relevant now?)

Default weights: 40% FSRS + 60% context.
This lets a highly relevant memory that isn't quite due yet beat
an irrelevant memory that's technically overdue for review.

Usage:
    from memory_system.fsrs_context_weighting import FsrsContextWeighter

    weighter = FsrsContextWeighter()
    ranked = weighter.weight_memories(
        memories=[{"id": "m1", "content": "..."}],
        query="debug auth module",
        states={"m1": fsrs_state},
        top_k=5,
    )
    for wm in ranked:
        print(f"{wm.memory_id}: {wm.combined_score:.2f}")
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS = (0.4, 0.6)  # (fsrs_weight, context_weight)
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "with", "by", "from", "this", "that", "it", "be", "are",
    "was", "were", "has", "have", "had", "not", "as", "if", "so", "do",
    "does", "can", "will", "would", "should", "may", "might",
})
_NEUTRAL_FSRS_SCORE = 0.5  # Used when no FSRS state is available


@dataclass
class WeightedMemory:
    memory_id: str
    fsrs_score: float
    context_score: float
    combined_score: float
    memory: dict = field(default_factory=dict)


class FsrsContextWeighter:
    """Combines FSRS due-score and context-relevance score for memory ranking."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        # db_path kept for API consistency; not currently used by this module
        self._db_path = Path(db_path) if db_path else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def weight_memories(
        self,
        memories: list[dict],
        query: str,
        states: dict[str, dict],
        weights: tuple[float, float] = _DEFAULT_WEIGHTS,
        top_k: Optional[int] = None,
    ) -> list[WeightedMemory]:
        """Rank memories by combined FSRS + context score.

        Args:
            memories: List of memory dicts with keys "id" and "content".
            query: Current context / task description.
            states: {memory_id: state_dict} from FSRS scheduler. Missing IDs
                    get a neutral FSRS score.
            weights: (fsrs_weight, context_weight) — must sum > 0.
            top_k: Optional limit on returned results.

        Returns:
            WeightedMemory objects sorted by combined_score descending.
        """
        if not memories:
            return []

        fsrs_w, ctx_w = weights
        total_w = fsrs_w + ctx_w
        if total_w == 0:
            total_w = 1.0  # safety

        results: list[WeightedMemory] = []
        for mem in memories:
            memory_id = mem.get("id", "")
            content = mem.get("content", "")
            state = states.get(memory_id)

            fsrs_score = self.compute_fsrs_score(state) if state else _NEUTRAL_FSRS_SCORE
            ctx_score = self.compute_context_score(content, query)
            combined = (fsrs_w * fsrs_score + ctx_w * ctx_score) / total_w

            results.append(WeightedMemory(
                memory_id=memory_id,
                fsrs_score=fsrs_score,
                context_score=ctx_score,
                combined_score=combined,
                memory=mem,
            ))

        results.sort(key=lambda wm: wm.combined_score, reverse=True)
        if top_k is not None:
            results = results[:top_k]
        return results

    def compute_fsrs_score(self, state: dict) -> float:
        """Convert FSRS state into a 0.0–1.0 urgency score.

        Logic:
        - Overdue memories (due_date in the past) score higher.
        - Urgency decays with stability — high-stability memories
          that aren't due score near 0; low-stability overdue memories score near 1.
        """
        due_date_str = state.get("due_date")
        stability = float(state.get("stability", 1.0))

        if due_date_str is None:
            return _NEUTRAL_FSRS_SCORE

        try:
            due_dt = datetime.fromisoformat(due_date_str)
            # Make both timezone-naive for comparison
            now = datetime.utcnow()
            if due_dt.tzinfo is not None:
                now = datetime.now(timezone.utc)
            days_overdue = (now - due_dt).total_seconds() / 86_400
        except (ValueError, TypeError):
            return _NEUTRAL_FSRS_SCORE

        # Sigmoid-like: overdue → approaches 1.0; future → approaches 0.0
        # Normalize by stability so high-stability memories decay urgency slower
        stability_factor = max(stability, 0.1)
        urgency = days_overdue / stability_factor

        # Clamp to [0, 1] via tanh-inspired formula
        if urgency >= 0:
            score = min(1.0, urgency / (urgency + 1))
        else:
            score = max(0.0, 1.0 + urgency / (abs(urgency) + 1))
        return float(score)

    def compute_context_score(self, content: str, query: str) -> float:
        """Jaccard similarity between content and query token sets.

        Returns 0.0–1.0. Returns 0.0 if either is empty.
        """
        if not content or not query:
            return 0.0
        tokens_c = _tokenize(content)
        tokens_q = _tokenize(query)
        if not tokens_c or not tokens_q:
            return 0.0
        intersection = tokens_c & tokens_q
        union = tokens_c | tokens_q
        return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Tokenize, removing stop words and tokens shorter than 3 chars."""
    return {
        w for w in text.lower().split()
        if w not in _STOP_WORDS and len(w) > 2
    }
