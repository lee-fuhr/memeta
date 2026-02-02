#!/usr/bin/env python3
"""
Test script for session consolidation

Usage: python3 test_consolidation.py <session_file.jsonl> [--yes]
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.session_consolidator import SessionConsolidator


def test_consolidation(session_file_path: str, auto_save: bool = False):
    """Test consolidation on a specific session"""
    session_file = Path(session_file_path)

    if not session_file.exists():
        print(f"Error: Session file not found: {session_file}")
        sys.exit(1)

    print(f"Testing consolidation on: {session_file.name}")
    print("="*70)

    # Initialize consolidator
    consolidator = SessionConsolidator(project_id="LFI")

    # Read session
    try:
        messages = consolidator.read_session(session_file)
        print(f"✓ Read {len(messages)} messages from session")
    except Exception as e:
        print(f"✗ Failed to read session: {e}")
        sys.exit(1)

    # Extract conversation
    conversation = consolidator.extract_conversation_text(messages)
    print(f"✓ Extracted conversation ({len(conversation)} chars)")

    # Extract memories
    print("\nExtracting memories...")
    memories = consolidator.extract_memories(conversation)
    print(f"✓ Extracted {len(memories)} memories")

    if len(memories) > 0:
        print("\nMemories found:")
        for i, mem in enumerate(memories[:5], 1):
            print(f"  {i}. [{mem.importance:.2f}] {mem.content[:80]}...")
        if len(memories) > 5:
            print(f"  ... and {len(memories) - 5} more")

    # Test deduplication
    print("\nTesting deduplication...")
    unique_memories = consolidator.deduplicate(memories)
    deduplicated = len(memories) - len(unique_memories)
    print(f"✓ Deduplicated: {deduplicated} duplicates removed, {len(unique_memories)} unique")

    # Calculate quality
    from src.session_consolidator import calculate_session_quality
    quality = calculate_session_quality(memories)
    print(f"\nSession quality:")
    print(f"  Total memories: {quality.total_memories}")
    print(f"  High value (≥0.7): {quality.high_value_count}")
    print(f"  Quality score: {quality.quality_score:.3f}")

    # Ask if user wants to save
    print("\n" + "="*70)
    print(f"Ready to save {len(unique_memories)} memories to memory-ts")

    if auto_save:
        response = 'y'
        print("Auto-saving (--yes flag)")
    else:
        response = input("Save these memories? (y/n): ").strip().lower()

    if response == 'y':
        result = consolidator.consolidate_session(session_file)
        print(f"\n✓ Consolidation complete!")
        print(f"  Memories extracted: {result.memories_extracted}")
        print(f"  Memories saved: {result.memories_saved}")
        print(f"  Duplicates filtered: {result.memories_deduplicated}")
        print(f"  Quality score: {result.session_quality.quality_score:.3f}")
    else:
        print("\nSkipped saving (test mode)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test session consolidation")
    parser.add_argument("session_file", help="Path to session JSONL file")
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-save without prompting")
    args = parser.parse_args()

    test_consolidation(args.session_file, auto_save=args.yes)
