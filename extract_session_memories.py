#!/usr/bin/env python3
"""
Extract memories from current session using LLM analysis

This script should be called BY Claude during the session.
The user asks Claude: "Extract memories from this session"
Claude runs this script which outputs a prompt for Claude to analyze.
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.session_consolidator import SessionConsolidator


def get_current_session_file():
    """Get the current session JSONL file"""
    import os

    session_id = os.environ.get("PROJECT_ID")
    if not session_id:
        # Try to find most recent session
        projects_dir = Path.home() / ".claude/projects"
        sessions = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for session_file in project_dir.glob("*.jsonl"):
                sessions.append((session_file.stat().st_mtime, session_file))

        if sessions:
            sessions.sort(reverse=True)
            return sessions[0][1]

        return None

    # Find session file
    projects_dir = Path.home() / ".claude/projects"
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        session_file = project_dir / f"{session_id}.jsonl"
        if session_file.exists():
            return session_file

    return None


if __name__ == "__main__":
    session_file = get_current_session_file()
    if not session_file:
        print("Error: Could not find session file")
        sys.exit(1)

    # Read session
    consolidator = SessionConsolidator(project_id="LFI")
    messages = consolidator.read_session(session_file)
    conversation = consolidator.extract_conversation_text(messages)

    # Generate prompt for Claude to analyze
    print("Analyze this session and extract learnings:")
    print()
    print(f"CONVERSATION (last 15,000 chars):")
    print(conversation[-15000:])
    print()
    print("Extract as JSON array with format:")
    print('[{"content": "...", "importance": 0.75, "reasoning": "..."}]')
