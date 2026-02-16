#!/usr/bin/env python3
"""
Weekly synthesis runner - executed by LaunchAgent Friday 5pm

Collects promoted memories, generates synthesis draft,
sends Pushover notification to Lee.
"""

from pathlib import Path

from memory_system.weekly_synthesis import WeeklySynthesis
from memory_system.fsrs_scheduler import FSRSScheduler
from memory_system.memory_ts_client import MemoryTSClient
from memory_system.promotion_executor import PromotionExecutor


def main():
    memory_dir = Path.home() / ".local/share/memory/LFI/memories"
    fsrs_db = project_root / "fsrs.db"
    cluster_db = project_root / "clusters.db"
    output_dir = project_root / "synthesis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run promotions before synthesis
    scheduler = FSRSScheduler(db_path=fsrs_db)
    memory_client = MemoryTSClient(memory_dir=memory_dir)
    executor = PromotionExecutor(
        scheduler=scheduler,
        memory_client=memory_client,
    )
    promotions = executor.execute_promotions()
    if promotions:
        print(f"Promoted {len(promotions)} memories to global scope")

    synthesis = WeeklySynthesis(
        memory_dir=memory_dir,
        fsrs_db_path=fsrs_db,
        cluster_db_path=cluster_db,
        output_dir=output_dir,
        scheduler=scheduler,
        memory_client=memory_client,
    )

    report = synthesis.generate()

    if report.promoted_count > 0:
        print(f"{report.promoted_count} promoted memories in synthesis")
        print(f"Draft written to: {report.output_path}")
        synthesis.notify(report)
    else:
        print("No new promotions this week")


if __name__ == "__main__":
    main()
