#!/usr/bin/env python3
"""
Consolidation Background Worker

Processes async consolidation queue continuously.

Can run as:
1. Launchd daemon (runs continuously)
2. Cron job (runs every 5-15 minutes)
3. Manual run (process queue once)

Usage:
    # Process queue once
    python3 consolidation_worker.py

    # Run continuously (daemon mode)
    python3 consolidation_worker.py --daemon

    # Process and exit
    python3 consolidation_worker.py --once
"""

import time
import argparse
from datetime import datetime

from memory_system.async_consolidation import process_consolidation_queue, ConsolidationQueue


def worker_loop(sleep_seconds: int = 60, max_per_run: int = 10):
    """
    Run worker in continuous loop.

    Args:
        sleep_seconds: Seconds to sleep between checks
        max_per_run: Max sessions to process per iteration
    """
    print(f"🔄 Consolidation worker started (checking every {sleep_seconds}s)")

    while True:
        try:
            queue = ConsolidationQueue()
            stats = queue.get_stats()

            if stats['pending'] > 0 or stats['failed'] > 0:
                print(f"\n{'='*60}")
                print(f"📊 Queue Stats: {stats['pending']} pending, {stats['failed']} failed")
                print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}\n")

                processed = process_consolidation_queue(
                    max_sessions=max_per_run,
                    timeout_per_session=300
                )

                print(f"\n✅ Processed {processed} sessions")

                # Cleanup old entries
                if datetime.now().hour == 3:  # At 3am
                    deleted = queue.cleanup_old(days=7)
                    if deleted > 0:
                        print(f"🗑️  Cleaned up {deleted} old entries")

            else:
                # Queue empty - just show status occasionally
                if int(time.time()) % 300 == 0:  # Every 5 minutes
                    print(f"ℹ️  [{datetime.now().strftime('%H:%M:%S')}] Queue empty, waiting...")

        except KeyboardInterrupt:
            print("\n⏹️  Worker stopped by user")
            break
        except Exception as e:
            print(f"❌ Worker error: {e}")
            print("   Continuing after error...")

        time.sleep(sleep_seconds)


def worker_once(max_sessions: int = 50):
    """Process queue once and exit"""
    print(f"🔄 Processing consolidation queue (max {max_sessions} sessions)...\n")

    queue = ConsolidationQueue()

    print("📊 Initial Queue Stats:")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print(f"\n{'='*60}")
    print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    processed = process_consolidation_queue(
        max_sessions=max_sessions,
        timeout_per_session=300
    )

    print(f"\n📊 Final Queue Stats:")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print(f"\n✅ Processed {processed} sessions")
    print(f"⏰ Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Consolidation background worker")
    parser.add_argument(
        '--daemon',
        action='store_true',
        help="Run continuously (daemon mode)"
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help="Process queue once and exit"
    )
    parser.add_argument(
        '--sleep',
        type=int,
        default=60,
        help="Sleep seconds between checks (daemon mode)"
    )
    parser.add_argument(
        '--max-per-run',
        type=int,
        default=10,
        help="Max sessions per iteration"
    )

    args = parser.parse_args()

    if args.daemon:
        worker_loop(
            sleep_seconds=args.sleep,
            max_per_run=args.max_per_run
        )
    else:
        # Default: process once
        worker_once(max_sessions=args.max_per_run if args.once else 50)


if __name__ == "__main__":
    main()
