"""
Confidence persistence - Persist confirmation/contradiction counts to memory files.

Bridges confidence_scoring (pure math) with memory_ts_client (file I/O).
ConfidenceManager increments counts, recalculates scores, and persists to disk.
"""

from typing import Dict

from .memory_ts_client import MemoryTSClient, Memory
from .confidence_scoring import calculate_confidence, get_confidence_stats


class ConfidenceManager:
    """
    Manages confidence score persistence for memories.

    Wraps MemoryTSClient to provide confirm/contradict operations
    that update counts, recalculate scores, and persist to disk.
    """

    def __init__(self, client: MemoryTSClient):
        self.client = client

    def confirm(self, memory_id: str) -> Memory:
        """
        Increment confirmations count and recalculate confidence_score.
        Persists the updated values to the memory file.

        Args:
            memory_id: ID of the memory to confirm

        Returns:
            The updated Memory object (re-read from disk)
        """
        mem = self.client.get(memory_id)
        confirmations = mem.confirmations + 1
        contradictions = mem.contradictions
        new_score = calculate_confidence(confirmations, contradictions)
        self.client.update(
            memory_id,
            confirmations=confirmations,
            confidence_score=new_score,
        )
        return self.client.get(memory_id)

    def contradict(self, memory_id: str) -> Memory:
        """
        Increment contradictions count and recalculate confidence_score.
        Persists the updated values to the memory file.

        Args:
            memory_id: ID of the memory to contradict

        Returns:
            The updated Memory object (re-read from disk)
        """
        mem = self.client.get(memory_id)
        confirmations = mem.confirmations
        contradictions = mem.contradictions + 1
        new_score = calculate_confidence(confirmations, contradictions)
        self.client.update(
            memory_id,
            contradictions=contradictions,
            confidence_score=new_score,
        )
        return self.client.get(memory_id)

    def get_summary(self) -> Dict:
        """
        Get confidence distribution across all active memories.

        Uses get_confidence_stats() from confidence_scoring.py.

        Returns:
            Dict with total, avg_confidence, by_level, low_confidence_count
        """
        memories = self.client.list()
        memory_dicts = [
            {
                'confidence_score': m.confidence_score,
                'confirmations': m.confirmations,
                'contradictions': m.contradictions,
            }
            for m in memories
        ]
        return get_confidence_stats(memory_dicts)
