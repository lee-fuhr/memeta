#!/usr/bin/env python3
"""
Migrate embeddings from SQLite to FAISS VectorStore.

Reads existing embeddings from intelligence.db and imports them
into the FAISS-backed VectorStore for fast similarity search.

Usage:
    python scripts/migrate_embeddings_to_faiss.py
    python scripts/migrate_embeddings_to_faiss.py --dry-run
    python scripts/migrate_embeddings_to_faiss.py --db-path /path/to/intelligence.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory_system.vector_store import VectorStore


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite embeddings to FAISS")
    parser.add_argument("--db-path", default=None,
                        help="Path to intelligence.db (default: auto-detect)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without doing it")
    args = parser.parse_args()

    # Find intelligence.db
    db_path = args.db_path
    if db_path is None:
        candidates = [
            Path(__file__).parent.parent / "intelligence.db",
            Path(__file__).parent.parent / "src" / "intelligence.db",
        ]
        for c in candidates:
            if c.exists():
                db_path = str(c)
                break

    if db_path is None or not Path(db_path).exists():
        print("No intelligence.db found. Nothing to migrate.")
        return

    # Check existing embeddings
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    except Exception:
        print("No embeddings table found. Nothing to migrate.")
        conn.close()
        return
    conn.close()

    print(f"Found {count} embeddings in {db_path}")

    if count == 0:
        print("Nothing to migrate.")
        return

    if args.dry_run:
        print(f"DRY RUN: Would import {count} embeddings to FAISS VectorStore")
        return

    # Perform migration
    store = VectorStore()
    existing = store.count()
    print(f"VectorStore currently has {existing} embeddings")

    imported = store.import_from_sqlite(db_path)
    print(f"Imported {imported} embeddings to FAISS VectorStore")
    print(f"VectorStore now has {store.count()} embeddings total")
    print("Migration complete.")


if __name__ == "__main__":
    main()
