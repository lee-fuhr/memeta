"""
Promotion executor - promotes validated memories from project → global scope

When a memory meets all promotion criteria (stability, review count,
cross-project validation), this executor:
1. Updates memory-ts: scope project → global
2. Adds #promoted tag
3. Marks promoted in FSRS scheduler
4. Returns promotion results for logging/synthesis
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .fsrs_scheduler import FSRSScheduler
from .memory_ts_client import MemoryTSClient


@dataclass
class PromotionResult:
    """Result of promoting a single memory"""
    memory_id: str
    old_scope: str
    new_scope: str
    stability: float
    review_count: int
    projects_validated: List[str]
    promoted_date: str = field(default_factory=lambda: datetime.now().isoformat())


class PromotionExecutor:
    """
    Executes memory promotions from project → global scope.

    Checks FSRS scheduler for promotion candidates, updates memory-ts
    files, and marks promotions in FSRS.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        scheduler: Optional[FSRSScheduler] = None,
        memory_client: Optional[MemoryTSClient] = None,
    ):
        """
        Initialize promotion executor.

        Args:
            memory_dir: Path to memory-ts memories directory
            scheduler: FSRS scheduler instance
            memory_client: Memory-ts client instance
        """
        self.memory_client = memory_client or MemoryTSClient(memory_dir=memory_dir)
        self.scheduler = scheduler or FSRSScheduler()

    def execute_promotions(self) -> List[PromotionResult]:
        """
        Find and promote all eligible memories.

        Queries FSRS for promotion candidates, updates each memory's
        scope and tags, marks as promoted in FSRS.

        Returns:
            List of PromotionResult for each promoted memory
        """
        candidates = self.scheduler.get_promotion_candidates()
        results = []

        for candidate in candidates:
            result = self._promote_memory(candidate.memory_id, candidate)
            if result:
                results.append(result)

        return results

    def promote_single(self, memory_id: str) -> Optional[PromotionResult]:
        """
        Promote a specific memory if it meets criteria.

        Args:
            memory_id: Memory to promote

        Returns:
            PromotionResult or None if not eligible
        """
        if not self.scheduler.is_promotion_ready(memory_id):
            return None

        state = self.scheduler.get_state(memory_id)
        if state is None:
            return None

        return self._promote_memory(memory_id, state)

    def _promote_memory(self, memory_id, fsrs_state) -> Optional[PromotionResult]:
        """
        Execute promotion for a single memory.

        Args:
            memory_id: Memory identifier
            fsrs_state: Current FSRS state

        Returns:
            PromotionResult or None on failure
        """
        try:
            memory = self.memory_client.get(memory_id)
        except Exception:
            return None

        old_scope = memory.scope

        # Update scope to global
        new_tags = list(memory.tags)
        if "#promoted" not in new_tags:
            new_tags.append("#promoted")

        self.memory_client.update(
            memory_id=memory_id,
            scope="global",
            tags=new_tags,
        )

        # Mark promoted in FSRS
        self.scheduler.mark_promoted(memory_id)

        projects = json.loads(fsrs_state.projects_validated)

        return PromotionResult(
            memory_id=memory_id,
            old_scope=old_scope,
            new_scope="global",
            stability=fsrs_state.stability,
            review_count=fsrs_state.review_count,
            projects_validated=projects,
        )
