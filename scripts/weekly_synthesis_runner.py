#!/usr/bin/env python3
"""
Weekly synthesis runner - executed by LaunchAgent Friday 5pm

Collects promoted memories, generates synthesis draft,
sends Pushover notification to Lee.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.weekly_synthesis import WeeklySynthesis
from src.fsrs_scheduler import FSRSScheduler
from src.memory_ts_client import MemoryTSClient


def main():
    memory_dir = Path.home() / ".local/share/memory/LFI/memories"
    fsrs_db = project_root / "fsrs.db"
    cluster_db = project_root / "clusters.db"
    output_dir = project_root / "synthesis"

    synthesis = WeeklySynthesis(
        memory_dir=memory_dir,
        fsrs_db_path=fsrs_db,
        cluster_db_path=cluster_db,
        output_dir=output_dir,
    )

    report = synthesis.generate()

    if report.promoted_count > 0:
        print(f"Promoted {report.promoted_count} memories")
        print(f"Draft written to: {report.output_path}")
        synthesis.notify(report)
    else:
        print("No new promotions this week")


if __name__ == "__main__":
    main()
