#!/usr/bin/env python3
"""
Test pre-compaction flush on current session.

Usage: python test_pre_compaction.py <session_id>
"""

import sys

from memory_system.pre_compaction_flush import extract_before_compaction
from memory_system.memory_ts_client import MemoryTSClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_pre_compaction.py <session_id>")
        print("\nExample:")
        print("  python test_pre_compaction.py d1e810da-e0bb-4bfe-a454-6bfd84ec8b6b")
        sys.exit(1)

    session_id = sys.argv[1]

    # Find session file
    session_dir = Path.home() / ".claude" / "projects" / "-Users-lee--local-share-memory"
    session_file = session_dir / f"{session_id}.jsonl"

    if not session_file.exists():
        print(f"❌ Session file not found: {session_file}")
        sys.exit(1)

    print(f"Extracting durable facts from session {session_id}...")
    print()

    # Extract facts
    facts = extract_before_compaction(session_file, session_id, max_facts=5)

    if not facts:
        print("No durable facts extracted.")
        return

    print(f"Extracted {len(facts)} durable facts:\n")

    for i, fact in enumerate(facts, 1):
        print(f"{i}. {fact['content']}")
        print(f"   Importance: {fact['importance']:.2f}")
        print(f"   Category: {fact['category']}")
        print(f"   Tags: {', '.join(fact.get('tags', []))}")
        print()

    # Ask if should save
    response = input("Save these facts to memory-ts? [y/N]: ")

    if response.lower() == 'y':
        client = MemoryTSClient(project_id="LFI")

        for fact in facts:
            client.create(
                content=fact['content'],
                project_id="LFI",
                importance=fact['importance'],
                tags=fact.get('tags', []),
                session_id=fact.get('session_id'),
                scope="project"
            )

        print(f"✅ Saved {len(facts)} facts to memory-ts")


if __name__ == "__main__":
    main()
