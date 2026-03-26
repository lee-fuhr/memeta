#!/usr/bin/env python3
"""
Monthly memory quality sweep.

Samples memories, scores them with LLM, archives low-quality ones.
Batches 10 memories per LLM call for efficiency.

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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from memory_system.memory_ts_client import MemoryTSClient
from memory_system.memory_injector import build_search_index
from memory_system.llm_backend import run_llm_prompt, strip_code_fence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BATCH_SIZE = 10

BATCH_PROMPT = """Rate each memory on usefulness (1-5 scale).

Scoring:
1 = Garbage (conversation fragment, generic advice, no actionable info)
2 = Low value (vaguely useful but too generic or context-dependent)
3 = Decent (specific enough to be useful in the right context)
4 = Good (actionable, specific, would help in future sessions)
5 = Excellent (critical insight, would prevent mistakes or save significant time)

MEMORIES:
{memories_block}

Return ONLY a JSON array with one object per memory, in the same order:
[{{"id": 1, "score": N, "reason": "one sentence"}}, ...]"""


def score_batch(batch: list[tuple[int, str]]) -> list[dict | None]:
    """Score a batch of memories in one LLM call.

    Args:
        batch: List of (index, content) tuples

    Returns:
        List of {score, reason} dicts (None for failures), same order as input
    """
    memories_block = "\n".join(
        f"[{idx}] {content[:400]}" for idx, content in batch
    )
    prompt = BATCH_PROMPT.format(memories_block=memories_block)

    response = run_llm_prompt(prompt, timeout=60, retries=2)
    if not response:
        return [None] * len(batch)

    text = strip_code_fence(response)

    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON array from response
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                results = json.loads(match.group())
            except json.JSONDecodeError:
                return [None] * len(batch)
        else:
            return [None] * len(batch)

    if not isinstance(results, list):
        return [None] * len(batch)

    # Map results back by index
    result_map = {}
    for r in results:
        if isinstance(r, dict) and "id" in r and "score" in r:
            result_map[r["id"]] = r

    return [result_map.get(idx) for idx, _ in batch]


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

    # Process in batches
    for batch_start in range(0, len(sample), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(sample))
        batch_items = [(i + 1, sample[i].content) for i in range(batch_start, batch_end)]

        logger.info(f"  Batch {batch_start // BATCH_SIZE + 1}: scoring items {batch_start + 1}-{batch_end}...")
        results = score_batch(batch_items)

        for j, result in enumerate(results):
            idx = batch_start + j
            m = sample[idx]
            item_num = idx + 1

            if not result:
                errors += 1
                print(f"  [{item_num}/{len(sample)}] ERROR: {m.content[:60]}...", flush=True)
                continue

            score = result.get("score", 3)
            scores[score] = scores.get(score, 0) + 1

            if score <= 2:
                if not dry_run:
                    client.update(m.id, scope="archived")
                    archived += 1
                print(f"  [{item_num}/{len(sample)}] ARCHIVE ({score}/5): {m.content[:60]}...", flush=True)
            else:
                print(f"  [{item_num}/{len(sample)}] KEEP ({score}/5): {m.content[:60]}...", flush=True)

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
