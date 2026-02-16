#!/usr/bin/env python3
"""
SessionEnd Hook - Async Consolidation (Fast Version)

Replaces blocking consolidation with queue-based async processing.

Performance:
- Before: 60-120s blocking (timeout risk)
- After: <1s (just writes to queue)

The actual consolidation happens in background worker.

Usage:
    Add to ~/.claude/settings.json:
    {
      "hooks": {
        "SessionEnd": {
          "type": "command",
          "command": "python3 /path/to/session-memory-consolidation-async.py",
          "timeout": 10000
        }
      }
    }
"""

import sys
import os
import json

from memory_system.async_consolidation import ConsolidationQueue


def main():
    """Fast SessionEnd hook - just adds to queue"""

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except Exception as e:
        print(f"❌ Error reading hook input: {e}", file=sys.stderr)
        return 1

    session_id = hook_input.get('sessionId')
    project_path = hook_input.get('projectPath')

    if not session_id or not project_path:
        print("⚠️  Missing sessionId or projectPath", file=sys.stderr)
        return 1

    # Construct session path
    session_dir = Path.home() / ".claude/projects" / os.path.basename(project_path)
    session_path = session_dir / f"{session_id}.jsonl"

    if not session_path.exists():
        print(f"⚠️  Session file not found: {session_path}", file=sys.stderr)
        return 1

    # Add to queue (FAST - just a DB insert)
    try:
        queue = ConsolidationQueue()
        added = queue.add(session_id, str(session_path))

        if added:
            print(f"✅ Session queued for consolidation: {session_id[:8]}")
        else:
            print(f"ℹ️  Session already queued: {session_id[:8]}")

        return 0

    except Exception as e:
        print(f"❌ Error queuing session: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
