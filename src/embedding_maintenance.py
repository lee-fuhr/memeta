"""
Embedding maintenance - Pre-compute embeddings for memories missing them.

Runs daily at 4 AM via LaunchAgent:
- Scans all active memories via MemoryTSClient.list()
- Checks which memories are missing embeddings in the DB
- Computes embeddings for missing memories via EmbeddingManager
- Reports stats: computed, skipped, errors, total, duration_ms

Complements daily_memory_maintenance.py (which handles decay + archival).
"""

import sqlite3
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from .memory_ts_client import MemoryTSClient
from .embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)


class EmbeddingMaintenanceRunner:
    """
    Pre-compute embeddings for all memories that don't have one yet.

    Uses MemoryTSClient to list memories and EmbeddingManager to
    check/compute embeddings. Designed for nightly maintenance runs.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        db_path: Optional[str] = None,
    ):
        """
        Initialize runner.

        Args:
            memory_dir: Directory for memory-ts storage (passed to MemoryTSClient)
            db_path: Path to intelligence.db (passed to EmbeddingManager)
        """
        self.client = MemoryTSClient(memory_dir=memory_dir)
        self.manager = EmbeddingManager(db_path=db_path)

    def run(self) -> Dict[str, Any]:
        """
        Pre-compute embeddings for all memories that don't have one yet.

        Returns:
            Dict with keys: computed, skipped, errors, total, duration_ms
        """
        start = time.time()

        computed = 0
        skipped = 0
        errors = 0

        # 1. List all active memories
        try:
            memories = self.client.list()
        except Exception as exc:
            logger.error("Failed to list memories: %s", exc)
            duration_ms = (time.time() - start) * 1000
            return {
                "computed": 0,
                "skipped": 0,
                "errors": 1,
                "total": 0,
                "duration_ms": round(duration_ms, 2),
            }

        total = len(memories)

        for memory in memories:
            content = memory.content
            if not content or not content.strip():
                skipped += 1
                continue

            try:
                # 2. Check if embedding already exists via content hash
                content_hash = self.manager._hash_content(content)

                with sqlite3.connect(self.manager.db_path) as conn:
                    row = conn.execute(
                        "SELECT 1 FROM embeddings WHERE content_hash = ?",
                        (content_hash,),
                    ).fetchone()

                if row:
                    skipped += 1
                    continue

                # 3. Compute embedding (stores it in DB automatically)
                self.manager.get_embedding(content)
                computed += 1

            except Exception as exc:
                logger.warning(
                    "Error computing embedding for memory %s: %s",
                    memory.id,
                    exc,
                )
                errors += 1

        duration_ms = (time.time() - start) * 1000

        result = {
            "computed": computed,
            "skipped": skipped,
            "errors": errors,
            "total": total,
            "duration_ms": round(duration_ms, 2),
        }

        logger.info(
            "Embedding maintenance complete: %d computed, %d skipped, %d errors (%.0fms)",
            computed,
            skipped,
            errors,
            duration_ms,
        )

        return result

    def check_freshness(self) -> bool:
        """
        Returns True if embeddings are stale (newest memory newer than newest embedding).

        A stale state means there are memories without corresponding embeddings.
        Returns True (stale) if there are no embeddings at all but memories exist.
        Returns False (fresh) if there are no memories.
        """
        memories = self.client.list()
        if not memories:
            return False  # No memories = nothing to embed = fresh

        # Find newest memory timestamp
        newest_memory_time = None
        for memory in memories:
            try:
                mem_time = datetime.fromisoformat(memory.created)
                if newest_memory_time is None or mem_time > newest_memory_time:
                    newest_memory_time = mem_time
            except (ValueError, TypeError):
                continue

        if newest_memory_time is None:
            return False

        # Find newest embedding timestamp
        stats = self.manager.get_stats()
        newest_embedding = stats.get("newest")

        if newest_embedding is None:
            return True  # Memories exist but no embeddings = stale

        try:
            newest_embedding_time = datetime.fromisoformat(newest_embedding)
        except (ValueError, TypeError):
            return True  # Can't parse = assume stale

        return newest_memory_time > newest_embedding_time

    def run_if_stale(self) -> Optional[Dict[str, Any]]:
        """
        Only runs pre-computation if freshness check fails.

        Returns:
            None if already fresh, result dict otherwise.
        """
        if not self.check_freshness():
            return None
        return self.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    runner = EmbeddingMaintenanceRunner()
    result = runner.run()

    print(f"\nEmbedding maintenance results:")
    for key, value in result.items():
        print(f"  {key}: {value}")
