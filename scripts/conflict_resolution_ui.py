#!/usr/bin/env python3
"""
Memory conflict resolution UI - Manual review of contradictions.

Feature 19: Interactive CLI for reviewing detected contradictions
before auto-resolving them.

Usage: python conflict_resolution_ui.py
"""

from memory_system.memory_ts_client import MemoryTSClient
from memory_system.contradiction_detector import check_contradictions


def review_conflicts(project_id: str = "LFI"):
    """
    Interactive conflict review.

    Shows potential contradictions and asks user what to do.
    """
    client = MemoryTSClient(project_id=project_id)

    # Get all memories
    all_memories = client.list()

    print(f"Reviewing {len(all_memories)} memories for conflicts...\n")

    conflicts_found = 0

    for mem in all_memories:
        # Check this memory against all others
        existing = [
            {'id': m.id, 'content': m.content}
            for m in all_memories
            if m.id != mem.id
        ]

        result = check_contradictions(mem.content, existing)

        if result.contradicts:
            conflicts_found += 1

            print(f"{'='*60}")
            print(f"CONFLICT DETECTED #{conflicts_found}\n")
            print(f"New memory: {mem.content}")
            print(f"  (ID: {mem.id}, Importance: {mem.importance:.2f})\n")
            print(f"Conflicts with: {result.contradicted_memory['content']}")
            print(f"  (ID: {result.contradicted_memory['id']})\n")

            print("What should I do?")
            print("  1. Keep new, archive old (auto-resolve)")
            print("  2. Keep old, archive new")
            print("  3. Keep both (not a real conflict)")
            print("  4. Skip (decide later)")

            choice = input("\nChoice [1-4]: ").strip()

            if choice == '1':
                # Archive old, keep new
                client.update(result.contradicted_memory['id'], scope="archived")
                print("✅ Archived old memory, kept new\n")

            elif choice == '2':
                # Archive new, keep old
                client.update(mem.id, scope="archived")
                print("✅ Archived new memory, kept old\n")

            elif choice == '3':
                # Keep both - tag as reviewed
                print("✅ Kept both memories\n")

            elif choice == '4':
                print("⏭️  Skipped\n")

            else:
                print("Invalid choice, skipping\n")

    print(f"\n{'='*60}")
    print(f"Review complete. Found {conflicts_found} conflicts.")


if __name__ == "__main__":
    try:
        review_conflicts()
    except KeyboardInterrupt:
        print("\n\nReview cancelled.")
        sys.exit(0)
