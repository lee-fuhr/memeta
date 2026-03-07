#!/usr/bin/env python3
"""Nightly skill evolution snapshot script.

Runs SkillEvolutionTracker.snapshot_all() to capture a point-in-time
snapshot of every SKILL.md file. Snapshots are stored in intelligence.db
and used by the skill health dashboard and evolution trend queries.

Intended to run via the com.memeta.skill-evolution-snapshot LaunchAgent
at 2am daily. Safe to run manually at any time.

Usage:
    ~/.local/venvs/memory-system/bin/python3 scripts/skill-evolution-snapshot.py
    ~/.local/venvs/memory-system/bin/python3 scripts/skill-evolution-snapshot.py --skills-dir /path/to/skills
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Allow running from any directory
_ms_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ms_root / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly skill evolution snapshot")
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="Path to the skills directory. Defaults to cfg.skills_dir.",
    )
    args = parser.parse_args()

    try:
        from memory_system.skill_evolution import SkillEvolutionTracker
    except ImportError as e:
        logger.error("Failed to import memory_system: %s", e)
        return 1

    try:
        tracker = SkillEvolutionTracker(skills_dir=args.skills_dir) if args.skills_dir else SkillEvolutionTracker()
        snapshots = tracker.snapshot_all()

        if not snapshots:
            logger.info("No skills found — nothing to snapshot")
            return 0

        counts: dict[str, int] = {}
        for snap in snapshots:
            counts[snap.change_type] = counts.get(snap.change_type, 0) + 1

        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        logger.info("Snapshotted %d skills: %s", len(snapshots), summary)
        return 0

    except Exception as e:
        logger.error("Snapshot failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
