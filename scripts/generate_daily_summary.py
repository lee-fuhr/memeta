#!/usr/bin/env python3
"""
Daily episodic summary generator.

Runs at 11:55 PM daily via LaunchAgent.
Summarizes all sessions from past 24 hours.
"""

import os
import sqlite3
from datetime import datetime, timedelta

from memory_system.session_consolidator import SessionConsolidator


def generate_daily_summary():
    """
    Summarizes all sessions from today.
    Writes to ~/.local/share/memory/LFI/daily/YYYY-MM-DD.md
    """
    today = datetime.now().date()

    # Find all session files from today in the Claude Code projects directory
    # Sessions are stored in ~/.claude/projects/-Users-lee--local-share-memory/
    session_dir = Path.home() / ".claude" / "projects" / "-Users-lee--local-share-memory"

    if not session_dir.exists():
        print(f"❌ Session directory not found: {session_dir}")
        return

    # Get all .jsonl files modified today
    all_sessions = list(session_dir.glob("*.jsonl"))

    # Filter to sessions modified today
    today_sessions = []
    for session_file in all_sessions:
        # Check file modification time
        mtime = datetime.fromtimestamp(session_file.stat().st_mtime).date()
        if mtime == today:
            today_sessions.append(session_file)

    if not today_sessions:
        print(f"No sessions today ({today})")
        return

    print(f"Found {len(today_sessions)} sessions for {today}")
    sessions = [(sf.stem, sf.stem, None) for sf in today_sessions]  # (session_id, name, timestamp)

    # Collect all memories extracted from today's sessions
    all_memories = []
    session_names = []

    for session_id, name, timestamp in sessions:
        session_names.append(session_id[:8])  # Use short ID as name

        # Session file is already a Path object in today_sessions
        session_file = next((sf for sf in today_sessions if sf.stem == session_id), None)

        if not session_file or not session_file.exists():
            print(f"  ⚠️  Session file not found: {session_id}")
            continue

        # Use consolidator to extract memories (but don't save them)
        consolidator = SessionConsolidator(project_id="LFI")

        try:
            # Extract memories but skip saving
            result = consolidator.consolidate_session(
                session_file=session_file,
                skip_save=True  # Don't save - just extract for summary
            )

            all_memories.extend(result.extracted_memories)
            print(f"  ✓ {session_id[:8]}: {len(result.extracted_memories)} memories")

        except Exception as e:
            print(f"  ⚠️  Error consolidating {session_id}: {e}")

    if not all_memories:
        print("No memories extracted from today's sessions")
        return

    # Sort memories by importance (SessionMemory is a dataclass, not a dict)
    all_memories.sort(key=lambda x: x.importance, reverse=True)

    # LLM synthesis using ask_claude helper
    from src.llm_extractor import ask_claude

    summary_prompt = f"""
Summarize key learnings from today's {len(sessions)} sessions.

Focus on:
- Patterns across sessions
- Decisions made
- Insights discovered
- Important context for tomorrow

Max 300 words. Be concise and actionable.

Top memories:
{chr(10).join([f"- {m.content}" for m in all_memories[:20]])}
"""

    try:
        summary = ask_claude(summary_prompt, timeout=15)
    except Exception as e:
        print(f"❌ LLM synthesis failed: {e}")
        summary = "Summary generation failed."

    # Write to daily summary file
    daily_dir = os.path.expanduser("~/.local/share/memory/LFI/daily")
    os.makedirs(daily_dir, exist_ok=True)

    summary_path = os.path.join(daily_dir, f"{today}.md")
    with open(summary_path, 'w') as f:
        f.write(f"# Daily summary: {today}\n\n")
        f.write(f"**Sessions:** {len(sessions)}\n")
        f.write(f"**Memories extracted:** {len(all_memories)}\n\n")
        f.write("## Sessions\n\n")
        for i, name in enumerate(session_names, 1):
            f.write(f"{i}. {name}\n")
        f.write(f"\n## Summary\n\n")
        f.write(summary)
        f.write(f"\n\n## Top memories\n\n")
        for i, mem in enumerate(all_memories[:10], 1):
            f.write(f"{i}. {mem.content} (importance: {mem.importance:.2f})\n")

    print(f"✅ Daily summary written to {summary_path}")


if __name__ == "__main__":
    generate_daily_summary()
