#!/usr/bin/env python3
"""
Search memories by session ID.

Enables queries like: "What did we learn in session abc123?"
"""

import sys

from memory_system.memory_ts_client import MemoryTSClient


def search_by_session(session_id: str, project_id: str = "LFI"):
    """
    Find all memories from a specific session.

    Args:
        session_id: Session ID to search for
        project_id: Project identifier
    """
    client = MemoryTSClient(project_id=project_id)

    # Search for memories with this session_id
    # Note: memory-ts doesn't have direct session_id filtering yet,
    # so we'll need to search all and filter
    all_memories = client.list()

    session_memories = [
        m for m in all_memories
        if getattr(m, 'session_id', None) == session_id
    ]

    if not session_memories:
        print(f"No memories found from session {session_id}")
        return

    print(f"Found {len(session_memories)} memories from session {session_id}:\n")

    for i, mem in enumerate(session_memories, 1):
        print(f"{i}. {mem.content}")
        print(f"   Importance: {mem.importance:.2f}")
        print(f"   Tags: {', '.join(mem.tags)}")
        print(f"   Scope: {mem.scope}")
        print()


def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print("Usage: python search_by_session.py <session_id>")
        print("\nExample:")
        print("  python search_by_session.py f9f9aa4a")
        sys.exit(1)

    session_id = sys.argv[1]
    search_by_session(session_id)


if __name__ == "__main__":
    main()
