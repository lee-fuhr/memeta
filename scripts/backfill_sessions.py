#!/usr/bin/env python3
"""
Backfill all session files through the consolidation pipeline.

Processes sessions chronologically (oldest first) so contradiction
detection and deduplication produce correct results — newer truths
overwrite older ones, not the reverse.

Uses Haiku LLM extraction (subscription-included, no API cost)
combined with regex pattern extraction for maximum coverage.

Usage:
    # Full backfill (all sessions)
    python3 scripts/backfill_sessions.py

    # Dry run (first 3 sessions only)
    python3 scripts/backfill_sessions.py --dry-run

    # Limit to N sessions
    python3 scripts/backfill_sessions.py --limit 50

    # Skip LLM extraction (regex only, much faster)
    python3 scripts/backfill_sessions.py --no-llm
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_system.session_consolidator import SessionConsolidator
from memory_system.pattern_detector import PatternDetector
from memory_system.fsrs_scheduler import FSRSScheduler
from memory_system.memory_injector import build_search_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SESSION_DIR = Path.home() / ".claude/projects/-Users-lee-CC"


def get_sessions_chronological() -> list[Path]:
    """Get all session JSONL files sorted by modification time (oldest first)."""
    sessions = list(SESSION_DIR.glob("*.jsonl"))
    sessions.sort(key=lambda p: p.stat().st_mtime)
    return sessions


def run_backfill(limit: int | None = None, use_llm: bool = True, dry_run: bool = False):
    """Process all sessions through the consolidation pipeline."""
    sessions = get_sessions_chronological()
    total = len(sessions)

    if limit:
        sessions = sessions[:limit]

    if dry_run:
        sessions = sessions[:3]
        logger.info(f"DRY RUN: processing 3 of {total} sessions")
    else:
        logger.info(f"Backfilling {len(sessions)} of {total} sessions (use_llm={use_llm})")

    consolidator = SessionConsolidator(project_id="default")
    detector = PatternDetector(scheduler=FSRSScheduler())

    succeeded = 0
    failed = 0
    total_memories = 0
    total_reinforcements = 0
    start_time = time.time()

    for i, session_file in enumerate(sessions):
        session_id = session_file.stem

        try:
            result = consolidator.consolidate_session(
                session_file=session_file,
                use_llm=use_llm,
            )

            total_memories += result.memories_saved

            # FSRS reinforcement
            if result.saved_memories:
                try:
                    memory_dicts = [
                        {'content': m.content, 'project_id': m.project_id, 'importance': m.importance}
                        for m in result.saved_memories
                    ]
                    signals = detector.detect_reinforcements(
                        new_memories=memory_dicts,
                        session_id=session_id,
                    )
                    total_reinforcements += len(signals)
                except Exception:
                    pass

            succeeded += 1

        except Exception as e:
            failed += 1
            logger.error(f"  FAILED {session_id[:8]}: {e}")

        # Progress every 10 sessions
        if (i + 1) % 10 == 0 or i == len(sessions) - 1:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(sessions) - i - 1) / rate if rate > 0 else 0
            logger.info(
                f"  [{i + 1}/{len(sessions)}] "
                f"{succeeded} ok, {failed} err, "
                f"{total_memories} memories, {total_reinforcements} reinforcements | "
                f"{elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining"
            )

    # Rebuild search index once at the end
    if succeeded > 0:
        logger.info("Rebuilding BM25 search index...")
        try:
            indexed = build_search_index()
            logger.info(f"Search index rebuilt: {indexed} memories indexed")
        except Exception as e:
            logger.error(f"Index rebuild failed: {e}")

    elapsed = time.time() - start_time
    logger.info(
        f"\nDone. {succeeded}/{len(sessions)} sessions processed in {elapsed:.0f}s. "
        f"{total_memories} memories saved, {total_reinforcements} FSRS reinforcements."
    )

    if failed > 0:
        logger.warning(f"{failed} sessions failed — check errors above")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill session memories")
    parser.add_argument("--limit", type=int, help="Process only first N sessions")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM extraction (regex only)")
    parser.add_argument("--dry-run", action="store_true", help="Process only 3 sessions")
    args = parser.parse_args()

    run_backfill(
        limit=args.limit,
        use_llm=not args.no_llm,
        dry_run=args.dry_run,
    )
