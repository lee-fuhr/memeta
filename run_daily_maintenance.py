#!/usr/bin/env python3
"""
Daily maintenance runner - Wrapper script for cron/LaunchAgent execution

This script can be run directly:
  python3 run_daily_maintenance.py
  python3 run_daily_maintenance.py --dry-run
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.daily_memory_maintenance import run_daily_maintenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Daily memory maintenance - decay, archival, stats, health checks"
    )
    parser.add_argument(
        "--memory-dir",
        type=str,
        help="Memory storage directory (default: ~/.local/share/memory/LFI/memories)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without applying changes"
    )

    args = parser.parse_args()

    memory_dir = Path(args.memory_dir) if args.memory_dir else None

    print(f"Running daily maintenance (dry_run={args.dry_run})...")
    result = run_daily_maintenance(memory_dir=memory_dir, dry_run=args.dry_run)

    print(f"\nMaintenance complete:")
    print(f"  - Decayed: {result['decay_count']} memories")
    print(f"  - Archived: {result['archived_count']} memories")
    print(f"  - Total: {result['stats']['total_memories']} memories")
    print(f"  - High importance: {result['stats']['high_importance_count']} memories")
    print(f"  - Health: {'OK' if result['health']['memory_ts_accessible'] else 'ERROR'}")
    print(f"  - Duration: {result['duration_ms']:.1f}ms")

    if result['health']['corrupted_files'] > 0:
        print(f"\n⚠️  WARNING: {result['health']['corrupted_files']} corrupted files detected")
