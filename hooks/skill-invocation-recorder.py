#!/usr/bin/env python3
"""Skill invocation recorder — PreToolUse hook.

Records every Skill tool invocation: calls SkillProvenanceTracker and
appends the skill name to active_skills in hook_state.json so the
session-end hook can later resolve outcomes.

DEPLOYMENT: Register with the memory-system venv Python in ~/.claude/settings.json:
  {
    "type": "command",
    "command": "~/.local/venvs/memory-system/bin/python3 /path/to/memeta/hooks/skill-invocation-recorder.py",
    "matcher": "Skill",
    "timeout": 10000
  }

Fires on: PreToolUse — Skill tool calls only (via matcher).
Fails silently: any exception exits 0 so Claude Code is never blocked.
"""

import json
import sys
from pathlib import Path

# Add src to path so memory_system imports work without pip install -e
_ms_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ms_root / "src"))


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return

    try:
        from memory_system.skill_invocation_recorder import process_tool_event
        process_tool_event(payload)
    except Exception:
        pass  # Never block Claude Code


if __name__ == "__main__":
    main()
