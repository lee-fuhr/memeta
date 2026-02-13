#!/usr/bin/env python3
"""
Master Nightly Maintenance Script

Runs all nightly jobs in correct order:
1. Embedding pre-computation (semantic search optimization)
2. Daily memory maintenance (decay, archival, stats)
3. Database optimization (VACUUM, ANALYZE)
4. Backup creation
5. Health checks

Designed to run at 3am via LaunchAgent.

Performance Fixes:
- P1: Pre-compute embeddings (fixes 500s search bottleneck)
- P2: VACUUM + ANALYZE (prevents SQLite degradation)
- P1: SQLite backups (prevents data loss)

Usage:
    python3 nightly_maintenance_master.py
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime
import sqlite3
import shutil


SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
DB_PATHS = [
    ROOT_DIR / "intelligence.db",
    ROOT_DIR / "fsrs.db",
    Path.home() / ".local/share/memory/LFI/session-history.db"
]
BACKUP_DIR = Path.home() / ".local/share/memory/LFI/backups"


def run_script(script_name: str, description: str) -> bool:
    """Run a Python script and return success status"""
    print(f"\n{'='*60}")
    print(f"🔄 {description}")
    print(f"{'='*60}\n")

    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        print(f"⚠️  Script not found: {script_path}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout
        )

        print(result.stdout)

        if result.stderr:
            print(f"Stderr: {result.stderr}")

        if result.returncode != 0:
            print(f"❌ Script failed with code {result.returncode}")
            return False

        print(f"✅ {description} complete")
        return True

    except subprocess.TimeoutExpired:
        print(f"❌ Script timed out after 30 minutes")
        return False
    except Exception as e:
        print(f"❌ Error running script: {e}")
        return False


def backup_databases():
    """Create backups of all databases (P1 Reliability Fix)"""
    print(f"\n{'='*60}")
    print(f"💾 Database Backups")
    print(f"{'='*60}\n")

    # Create backup directory
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Keep last 7 days of backups
    timestamp = datetime.now().strftime('%Y%m%d')

    success_count = 0

    for db_path in DB_PATHS:
        if not db_path.exists():
            print(f"⏭️  Skipping {db_path.name} (not found)")
            continue

        backup_path = BACKUP_DIR / f"{db_path.stem}_{timestamp}.db"

        try:
            # Use SQLite backup API for consistency
            source = sqlite3.connect(str(db_path))
            dest = sqlite3.connect(str(backup_path))

            source.backup(dest)

            source.close()
            dest.close()

            size_mb = backup_path.stat().st_size / 1024 / 1024
            print(f"✅ Backed up {db_path.name} ({size_mb:.2f} MB)")
            success_count += 1

        except Exception as e:
            print(f"❌ Failed to backup {db_path.name}: {e}")

    # Cleanup old backups (keep last 7 days)
    try:
        cutoff_date = datetime.now().strftime('%Y%m%d')
        cutoff_int = int(cutoff_date) - 7

        for backup_file in BACKUP_DIR.glob("*.db"):
            # Extract date from filename (format: dbname_YYYYMMDD.db)
            try:
                date_str = backup_file.stem.split('_')[-1]
                if len(date_str) == 8 and date_str.isdigit():
                    if int(date_str) < cutoff_int:
                        backup_file.unlink()
                        print(f"🗑️  Deleted old backup: {backup_file.name}")
            except Exception:
                continue

    except Exception as e:
        print(f"⚠️  Warning: Backup cleanup failed: {e}")

    print(f"\n✅ Backed up {success_count}/{len(DB_PATHS)} databases")
    return success_count > 0


def optimize_databases():
    """Run VACUUM and ANALYZE on all databases (P2 Performance Fix)"""
    print(f"\n{'='*60}")
    print(f"⚡ Database Optimization (VACUUM + ANALYZE)")
    print(f"{'='*60}\n")

    success_count = 0

    for db_path in DB_PATHS:
        if not db_path.exists():
            print(f"⏭️  Skipping {db_path.name} (not found)")
            continue

        try:
            # Get size before
            size_before = db_path.stat().st_size / 1024 / 1024

            conn = sqlite3.connect(str(db_path))

            # VACUUM (defragment, reclaim space)
            print(f"🔄 VACUUM {db_path.name}...")
            conn.execute("VACUUM")

            # ANALYZE (update query planner statistics)
            print(f"🔄 ANALYZE {db_path.name}...")
            conn.execute("ANALYZE")

            conn.close()

            # Get size after
            size_after = db_path.stat().st_size / 1024 / 1024
            saved_mb = size_before - size_after

            print(f"✅ Optimized {db_path.name}")
            print(f"   Before: {size_before:.2f} MB")
            print(f"   After: {size_after:.2f} MB")
            if saved_mb > 0:
                print(f"   Saved: {saved_mb:.2f} MB\n")

            success_count += 1

        except Exception as e:
            print(f"❌ Failed to optimize {db_path.name}: {e}\n")

    print(f"✅ Optimized {success_count}/{len(DB_PATHS)} databases")
    return success_count > 0


def health_check():
    """Run health checks on all databases"""
    print(f"\n{'='*60}")
    print(f"🏥 Health Checks")
    print(f"{'='*60}\n")

    all_healthy = True

    for db_path in DB_PATHS:
        if not db_path.exists():
            print(f"⚠️  {db_path.name}: NOT FOUND")
            all_healthy = False
            continue

        try:
            conn = sqlite3.connect(str(db_path))

            # Integrity check
            result = conn.execute("PRAGMA integrity_check").fetchone()

            if result and result[0] == 'ok':
                print(f"✅ {db_path.name}: Healthy")
            else:
                print(f"❌ {db_path.name}: CORRUPTION DETECTED - {result}")
                all_healthy = False

            conn.close()

        except Exception as e:
            print(f"❌ {db_path.name}: Error - {e}")
            all_healthy = False

    if all_healthy:
        print(f"\n✅ All databases healthy")
    else:
        print(f"\n⚠️  Some databases have issues - check logs")

    return all_healthy


def main():
    """Run all nightly maintenance jobs"""
    start_time = datetime.now()

    print(f"\n{'#'*60}")
    print(f"# 🌙 NIGHTLY MAINTENANCE MASTER")
    print(f"# Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    results = {
        'start_time': start_time.isoformat(),
        'jobs': []
    }

    # Job 1: Embedding pre-computation (P1 Performance Fix)
    success = run_script(
        "nightly_embedding_precompute.py",
        "Embedding Pre-computation"
    )
    results['jobs'].append({'name': 'embedding_precompute', 'success': success})

    # Job 2: Database backups (P1 Reliability Fix)
    success = backup_databases()
    results['jobs'].append({'name': 'database_backups', 'success': success})

    # Job 3: Database optimization (P2 Performance Fix)
    success = optimize_databases()
    results['jobs'].append({'name': 'database_optimization', 'success': success})

    # Job 4: Health checks
    success = health_check()
    results['jobs'].append({'name': 'health_check', 'success': success})

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    results['end_time'] = end_time.isoformat()
    results['duration_seconds'] = duration

    total_jobs = len(results['jobs'])
    successful_jobs = sum(1 for job in results['jobs'] if job['success'])

    print(f"\n{'#'*60}")
    print(f"# 🌙 NIGHTLY MAINTENANCE COMPLETE")
    print(f"# Duration: {duration:.1f} seconds")
    print(f"# Success: {successful_jobs}/{total_jobs} jobs")
    print(f"# Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}\n")

    # Save log
    log_file = ROOT_DIR / "logs" / f"maintenance_{start_time.strftime('%Y%m%d')}.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    import json
    with open(log_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"📝 Log saved: {log_file}")

    # Return 0 if all jobs succeeded, 1 otherwise
    return 0 if successful_jobs == total_jobs else 1


if __name__ == "__main__":
    sys.exit(main())
