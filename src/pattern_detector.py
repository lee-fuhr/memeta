"""
Pattern detector - cross-session reinforcement detection

Compares new session memories against existing memories in memory-ts.
When overlap >= 50% (configurable), that's a "reinforcement" signal.
Logs reinforcements to FSRS scheduler for promotion tracking.

Reinforcement grading:
- Same insight from same project → GOOD (3)
- Same insight from different project → EASY (4) (stronger signal)
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional

from .fsrs_scheduler import FSRSScheduler, ReviewGrade
from .memory_ts_client import MemoryTSClient, Memory


DEFAULT_SIMILARITY_THRESHOLD = 0.35


def normalize_text(text: str) -> set:
    """
    Normalize text for comparison - strip punctuation, lowercase, return word set.

    Args:
        text: Raw text string

    Returns:
        Set of normalized words
    """
    text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in text_clean.split() if w]
    return set(words)


def word_overlap_score(text_a: str, text_b: str) -> float:
    """
    Calculate bidirectional word overlap similarity between two texts.

    Returns the maximum of (overlap/len_a, overlap/len_b) to catch
    cases where one text is a subset of the other.

    Args:
        text_a: First text
        text_b: Second text

    Returns:
        Similarity score 0.0-1.0
    """
    words_a = normalize_text(text_a)
    words_b = normalize_text(text_b)

    if not words_a or not words_b:
        return 0.0

    overlap = len(words_a & words_b)
    score_a = overlap / len(words_a)
    score_b = overlap / len(words_b)

    return max(score_a, score_b)


@dataclass
class ReinforcementSignal:
    """A detected reinforcement between a new memory and an existing one"""
    memory_id: str              # Existing memory that was reinforced
    matched_memory_id: str      # The new memory that triggered reinforcement
    similarity_score: float     # How similar (0.0-1.0)
    grade: ReviewGrade          # GOOD (same project) or EASY (cross-project)
    project_id: str             # Project of the new memory
    session_id: str             # Session that triggered the reinforcement


class PatternDetector:
    """
    Detects cross-session reinforcement patterns.

    Compares new session memories against existing memory-ts memories.
    When similarity exceeds threshold, logs a reinforcement to FSRS.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        scheduler: Optional[FSRSScheduler] = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """
        Initialize pattern detector.

        Args:
            memory_dir: Path to memory-ts memories directory
            scheduler: FSRS scheduler instance
            similarity_threshold: Minimum overlap to count as reinforcement (0.0-1.0)
        """
        self.memory_client = MemoryTSClient(memory_dir=memory_dir)
        self.scheduler = scheduler or FSRSScheduler()
        self.similarity_threshold = similarity_threshold

    def detect_reinforcements(
        self,
        new_memories: List[Dict[str, Any]],
        session_id: str,
    ) -> List[ReinforcementSignal]:
        """
        Detect reinforcements between new session memories and existing memories.

        For each new memory, finds the best-matching existing memory above
        the similarity threshold. Grades as GOOD (same project) or EASY
        (cross-project). Registers and records review in FSRS.

        Args:
            new_memories: List of dicts with 'content', 'project_id', 'importance'
            session_id: Session that produced these memories

        Returns:
            List of ReinforcementSignal objects
        """
        if not new_memories:
            return []

        # Load all existing memories
        existing_memories = self.memory_client.search()
        if not existing_memories:
            return []

        # Batch-load promoted IDs to avoid O(n*m) SQLite queries
        promoted_ids = self.scheduler.get_promoted_ids()

        signals = []

        for new_mem in new_memories:
            new_content = new_mem.get("content", "")
            new_project = new_mem.get("project_id", "LFI")

            if not new_content:
                continue

            # Find best match among existing memories
            best_match: Optional[Memory] = None
            best_score: float = 0.0

            for existing in existing_memories:
                # Skip already-promoted memories (batch lookup, no DB query)
                if existing.id in promoted_ids:
                    continue

                # Skip self-match (memory just saved to store this session)
                new_id = new_mem.get("id")
                if new_id and new_id == existing.id:
                    continue

                score = word_overlap_score(new_content, existing.content)

                if score >= self.similarity_threshold and score > best_score:
                    best_score = score
                    best_match = existing

            if best_match is None:
                continue

            # Determine grade: same project = GOOD, different project = EASY
            if new_project == best_match.project_id:
                grade = ReviewGrade.GOOD
            else:
                grade = ReviewGrade.EASY

            # Register memory in FSRS if not already tracked
            self.scheduler.register_memory(
                best_match.id,
                project_id=best_match.project_id,
            )

            # Record the review event
            self.scheduler.record_review(
                memory_id=best_match.id,
                grade=grade,
                project_id=new_project,
                session_id=session_id,
            )

            signals.append(ReinforcementSignal(
                memory_id=best_match.id,
                matched_memory_id=new_mem.get("id", ""),
                similarity_score=best_score,
                grade=grade,
                project_id=new_project,
                session_id=session_id,
            ))

        return signals
