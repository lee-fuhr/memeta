#!/usr/bin/env python3
"""
Seed session history database from existing .jsonl files - FIXED VERSION.

Properly parses Claude Code .jsonl format (event-based, not message-based).
"""

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Session files location
SESSION_DIR = Path.home() / ".claude/projects/-Users-lee-CC-LFI"
DB_PATH = Path.home() / ".local/share/memory/LFI/session-history.db"


def init_database():
    """Initialize session history database if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_history (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            name TEXT,
            full_transcript_json TEXT NOT NULL,
            message_count INTEGER NOT NULL,
            tool_call_count INTEGER NOT NULL,
            memories_extracted INTEGER DEFAULT 0
        )
    """)

    # Full-text search index
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS session_history_fts
        USING fts5(id, name, content)
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")


def parse_session_file(file_path: Path) -> Optional[Dict]:
    """
    Parse a .jsonl session file into structured data.
    Claude Code format: events with 'type' field (userMessage, assistantMessage, toolUse, etc.)
    """
    try:
        events = []
        user_messages = []
        assistant_messages = []
        tool_calls = []
        searchable_text = []

        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    events.append(event)

                    event_type = event.get('type', '')

                    # User messages
                    if event_type == 'user':
                        user_messages.append(event)
                        # Text might be in 'content' or 'data.text'
                        text = event.get('content', event.get('data', {}).get('text', ''))
                        if text:
                            searchable_text.append(text)

                    # Assistant messages
                    elif event_type == 'assistant':
                        assistant_messages.append(event)
                        text = event.get('content', event.get('data', {}).get('text', ''))
                        if text:
                            searchable_text.append(text)

                    # Tool calls
                    elif event_type == 'tool' or event_type == 'progress':
                        if event.get('data', {}).get('type') not in ['hookStart', 'hookEnd']:
                            tool_calls.append(event)

                except json.JSONDecodeError:
                    continue

        if not events:
            return None

        # Extract session metadata
        session_id = file_path.stem

        # Get timestamp from first event
        timestamp = events[0].get('timestamp', int(file_path.stat().st_mtime))

        # Try to extract session name
        # Check if renamed (format: YYYY-MM-DD-HH-MM-descriptive-name)
        name_parts = session_id.split('-')
        if len(name_parts) >= 5:
            # Has descriptive name
            name = ' '.join(name_parts[4:]).replace('-', ' ').title()
        elif user_messages:
            # Use first user message
            first_text = user_messages[0].get('data', {}).get('text', '')
            name = first_text[:50] + ('...' if len(first_text) > 50 else '')
        else:
            name = 'Untitled session'

        return {
            'id': session_id,
            'timestamp': timestamp,
            'name': name,
            'events': events,  # Store full events for transcript
            'message_count': len(user_messages) + len(assistant_messages),
            'tool_call_count': len(tool_calls),
            'searchable_text': '\n\n'.join(searchable_text)
        }

    except Exception as e:
        print(f"⚠️  Error parsing {file_path.name}: {e}")
        return None


def save_to_database(session_data: Dict):
    """Save session data to database."""
    conn = sqlite3.connect(DB_PATH)

    # Check if already exists
    cursor = conn.execute("SELECT id FROM session_history WHERE id = ?", (session_data['id'],))
    if cursor.fetchone():
        print(f"⏭️  Skipping {session_data['id']} (already in DB)")
        conn.close()
        return

    # Insert into main table
    conn.execute("""
        INSERT INTO session_history
        (id, timestamp, name, full_transcript_json, message_count, tool_call_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session_data['id'],
        session_data['timestamp'],
        session_data['name'],
        json.dumps(session_data['events']),
        session_data['message_count'],
        session_data['tool_call_count']
    ))

    # Insert into FTS index
    conn.execute("""
        INSERT INTO session_history_fts (id, name, content)
        VALUES (?, ?, ?)
    """, (
        session_data['id'],
        session_data['name'],
        session_data['searchable_text']
    ))

    conn.commit()
    conn.close()

    print(f"✅ {session_data['name'][:40]} ({session_data['message_count']} msgs, {session_data['tool_call_count']} tools)")


def seed_all_sessions():
    """Scan session directory and seed all .jsonl files."""
    if not SESSION_DIR.exists():
        print(f"❌ Session directory not found: {SESSION_DIR}")
        return

    session_files = list(SESSION_DIR.glob("*.jsonl"))
    print(f"\n📁 Found {len(session_files)} session files")

    if not session_files:
        print("⚠️  No .jsonl files found")
        return

    print(f"\n🔄 Processing sessions...\n")

    processed = 0
    skipped = 0
    errors = 0

    for file_path in sorted(session_files):
        session_data = parse_session_file(file_path)

        if session_data:
            try:
                save_to_database(session_data)
                processed += 1
            except Exception as e:
                print(f"❌ Error saving {file_path.name}: {e}")
                errors += 1
        else:
            skipped += 1

    print(f"\n✨ Seeding complete!")
    print(f"   Processed: {processed}")
    print(f"   Skipped: {skipped}")
    print(f"   Errors: {errors}")

    # Show stats
    conn = sqlite3.connect(DB_PATH)

    cursor = conn.execute("SELECT COUNT(*) FROM session_history")
    total = cursor.fetchone()[0]

    cursor = conn.execute("SELECT SUM(message_count) FROM session_history")
    total_messages = cursor.fetchone()[0] or 0

    cursor = conn.execute("SELECT SUM(tool_call_count) FROM session_history")
    total_tool_calls = cursor.fetchone()[0] or 0

    print(f"\n📈 Database stats:")
    print(f"   Total sessions: {total:,}")
    print(f"   Total messages: {total_messages:,}")
    print(f"   Total tool calls: {total_tool_calls:,}")

    conn.close()


if __name__ == "__main__":
    print("🌱 Session History Seeder v2 (FIXED)")
    print("=" * 50)

    init_database()
    seed_all_sessions()

    print(f"\n📊 Database: {DB_PATH}")
    print("✅ Done!")
