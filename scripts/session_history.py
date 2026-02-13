#!/usr/bin/env python3
"""
Session History CLI - Query and browse full session transcripts.

Usage:
  python session_history.py search "error handling"
  python session_history.py recent --limit 20
  python session_history.py get abc123-session-id
  python session_history.py stats
  python session_history.py save <session-id>  # Save current/specified session
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_history_db import (
    search_sessions,
    get_session_by_id,
    get_recent_sessions,
    get_session_stats,
    save_session
)


def format_timestamp(ts: int) -> str:
    """Format unix timestamp as readable date."""
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def format_duration(seconds: int) -> str:
    """Format duration in seconds."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def cmd_search(args):
    """Search sessions by query."""
    results = search_sessions(args.query, limit=args.limit)

    if not results:
        print(f"No sessions found for: {args.query}")
        return

    print(f"Found {len(results)} sessions:\n")

    for session in results:
        print(f"{'='*60}")
        print(f"ID: {session['id']}")
        print(f"Name: {session['name'] or '(unnamed)'}")
        print(f"Date: {format_timestamp(session['timestamp'])}")
        print(f"Messages: {session['message_count']} | Tool calls: {session['tool_call_count']}")
        print(f"Memories: {session['memories_extracted']} | Quality: {session['session_quality']:.2f}")
        if session['duration_seconds']:
            print(f"Duration: {format_duration(session['duration_seconds'])}")
        print()


def cmd_get(args):
    """Get full session transcript."""
    session = get_session_by_id(args.session_id)

    if not session:
        print(f"Session not found: {args.session_id}")
        return

    print(f"{'='*60}")
    print(f"Session: {session['name'] or session['id']}")
    print(f"Date: {format_timestamp(session['timestamp'])}")
    print(f"Messages: {session['message_count']}")
    print(f"Tool calls: {session['tool_call_count']}")
    print(f"Memories: {session['memories_extracted']}")
    print(f"Quality: {session['session_quality']:.2f}")
    print(f"{'='*60}\n")

    # Print transcript
    transcript = session['transcript']

    for i, msg in enumerate(transcript, 1):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        # Handle structured content
        if isinstance(content, list):
            content_str = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'tool_use':
                        content_str.append(f"[TOOL: {item.get('name')}]")
                    elif item.get('type') == 'text':
                        content_str.append(item.get('text', ''))
            content = '\n'.join(content_str)

        # Truncate long messages
        if len(content) > 500 and not args.full:
            content = content[:500] + "... (truncated, use --full for complete)"

        print(f"[{i}] {role.upper()}: {content}\n")


def cmd_recent(args):
    """Show recent sessions."""
    sessions = get_recent_sessions(limit=args.limit)

    if not sessions:
        print("No sessions found")
        return

    print(f"Recent {len(sessions)} sessions:\n")

    for session in sessions:
        print(f"{session['id'][:8]}  {format_timestamp(session['timestamp'])}  {session['name'] or '(unnamed)'}")
        print(f"  Messages: {session['message_count']}, Quality: {session['session_quality']:.2f}")
        print()


def cmd_stats(args):
    """Show session history statistics."""
    stats = get_session_stats()

    print("Session History Statistics\n")
    print(f"Total sessions: {stats['total_sessions']}")
    print(f"Total messages: {stats['total_messages']}")
    print(f"Total memories extracted: {stats['total_memories_extracted']}")
    print(f"Average session quality: {stats['avg_quality']:.2f}")


def cmd_save(args):
    """Save a session to history DB."""
    # Find session file
    session_dir = Path.home() / ".claude" / "projects" / "-Users-lee--local-share-memory"
    session_file = session_dir / f"{args.session_id}.jsonl"

    if not session_file.exists():
        print(f"❌ Session file not found: {args.session_id}")
        return

    # Read transcript
    transcript = []
    with open(session_file) as f:
        for line in f:
            try:
                transcript.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not transcript:
        print(f"❌ No messages in session: {args.session_id}")
        return

    # Save to DB
    success = save_session(
        session_id=args.session_id,
        transcript=transcript,
        project_id="LFI"
    )

    if success:
        print(f"✅ Saved session {args.session_id} ({len(transcript)} messages)")
    else:
        print(f"❌ Failed to save session")


def main():
    parser = argparse.ArgumentParser(description="Session History CLI")
    subparsers = parser.add_subparsers(dest='command', help='Command')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search sessions')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', type=int, default=20, help='Max results')

    # Get command
    get_parser = subparsers.add_parser('get', help='Get full session')
    get_parser.add_argument('session_id', help='Session ID')
    get_parser.add_argument('--full', action='store_true', help='Show full messages (no truncation)')

    # Recent command
    recent_parser = subparsers.add_parser('recent', help='Show recent sessions')
    recent_parser.add_argument('--limit', type=int, default=10, help='Number of sessions')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')

    # Save command
    save_parser = subparsers.add_parser('save', help='Save session to history')
    save_parser.add_argument('session_id', help='Session ID to save')

    args = parser.parse_args()

    if args.command == 'search':
        cmd_search(args)
    elif args.command == 'get':
        cmd_get(args)
    elif args.command == 'recent':
        cmd_recent(args)
    elif args.command == 'stats':
        cmd_stats(args)
    elif args.command == 'save':
        cmd_save(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
