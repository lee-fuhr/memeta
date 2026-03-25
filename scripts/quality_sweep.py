#!/usr/bin/env python3
"""
Monthly memory quality sweep.

Samples memories, scores them with Haiku, archives low-quality ones.
Run monthly via LaunchAgent or manually.

Usage:
    # Score and archive (default: 30 random memories)
    python3 scripts/quality_sweep.py

    # Dry run (score but don't archive)
    python3 scripts/quality_sweep.py --dry-run

    # Custom sample size
    python3 scripts/quality_sweep.py --sample 50
"""

import argparse
import json
import logging
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_system.memory_ts_client import MemoryTSClient
from memory_system.memory_injector import build_search_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

SCORE_PROMPT = """Rate this memory on usefulness (1-5 scale):

MEMORY:
{content}

Scoring:
1 = Garbage (conversation fragment, generic advice, no actionable info)
2 = Low value (vaguely useful but too generic or context-dependent)
3 = Decent (specific enough to be useful in the right context)
4 = Good (actionable, specific, would help in future sessions)
5 = Excellent (critical insight, would prevent mistakes or save significant time)

Return ONLY a JSON object: {{"score": N, "reason": "one sentence why"}}"""


def score_memory(content: str) -> dict | None:
    """Score a memory using Haiku. Returns {score, reason} or None on failure."""
    prompt = SCORE_PROMPT.format(content=content[:500])
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return None

        text = result.stdout.strip()
        if text.startswith("```"):
            import re
            text = re.sub(r'^```(?:json)?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)

        return json.loads(text)
    except Exception:
        return None


def run_sweep(sample_size: int = 30, dry_run: bool = False):
    """Score random memories and archive low-quality ones."""
    client = MemoryTSClient()
    memories = client.search(project_id="default")
    active = [m for m in memories if getattr(m, 'scope', 'project') != 'archived']

    if len(active) < sample_size:
        sample = active
    else:
        sample = random.sample(active, sample_size)

    logger.info(f"Scoring {len(sample)} of {len(active)} active memories (dry_run={dry_run})")

    scores = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    archived = 0
    errors = 0

    for i, m in enumerate(sample):
        result = score_memory(m.content)
        if not result:
            errors += 1
            continue

        score = result.get("score", 3)
        reason = result.get("reason", "")
        scores[score] = scores.get(score, 0) + 1

        if score <= 2:
            if not dry_run:
                client.update(m.id, scope="archived")
                archived += 1
            logger.info(f"  [{score}/5] ARCHIVE: {m.content[:80]}... ({reason})")
        elif score >= 4:
            logger.info(f"  [{score}/5] KEEP: {m.content[:80]}...")

        if (i + 1) % 10 == 0:
            logger.info(f"  Progress: {i+1}/{len(sample)}")

    # Rebuild index if we archived anything
    if archived > 0:
        indexed = build_search_index()
        logger.info(f"Index rebuilt: {indexed} memories")

    logger.info(f"\nDone. Distribution: {dict(scores)}")
    logger.info(f"Archived: {archived}, errors: {errors}")
    avg = sum(k * v for k, v in scores.items()) / max(sum(scores.values()), 1)
    logger.info(f"Average quality score: {avg:.1f}/5")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly memory quality sweep")
    parser.add_argument("--sample", type=int, default=30, help="Number of memories to score")
    parser.add_argument("--dry-run", action="store_true", help="Score but don't archive")
    args = parser.parse_args()

    run_sweep(sample_size=args.sample, dry_run=args.dry_run)
