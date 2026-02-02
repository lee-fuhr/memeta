#!/usr/bin/env python3
"""
Pattern detection runner - called after session consolidation

Takes new session memories and checks for reinforcement patterns
against existing memories. Logs reinforcements to FSRS scheduler.

Usage:
    python3 pattern_detection_runner.py <session_id> <memories_json>
"""

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pattern_detector import PatternDetector
from src.fsrs_scheduler import FSRSScheduler


def main():
    if len(sys.argv) < 3:
        print("Usage: pattern_detection_runner.py <session_id> <memories_json_file>")
        sys.exit(1)

    session_id = sys.argv[1]
    memories_file = Path(sys.argv[2])

    if not memories_file.exists():
        print(f"Memories file not found: {memories_file}")
        sys.exit(1)

    memories = json.loads(memories_file.read_text())

    memory_dir = Path.home() / ".local/share/memory/LFI/memories"
    fsrs_db = project_root / "fsrs.db"

    detector = PatternDetector(
        memory_dir=memory_dir,
        scheduler=FSRSScheduler(db_path=fsrs_db),
    )

    signals = detector.detect_reinforcements(
        new_memories=memories,
        session_id=session_id,
    )

    if signals:
        print(f"Detected {len(signals)} reinforcements:")
        for s in signals:
            print(f"  {s.memory_id} (grade={s.grade.name}, score={s.similarity_score:.2f})")
    else:
        print("No reinforcements detected")


if __name__ == "__main__":
    main()
