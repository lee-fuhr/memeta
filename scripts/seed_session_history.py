#!/usr/bin/env python3
"""
Seed session history database from existing .jsonl files.

Retroactively populates session-history.db with all past conversations.
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

    Returns:
        Dict with: id, timestamp, name, messages, message_count, tool_call_count
    """
    try:
        messages = []

        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue

        if not messages:
            return None

        # Extract session metadata
        session_id = file_path.stem  # filename without .jsonl

        # Get timestamp from first message or file mtime
        timestamp = messages[0].get('timestamp', int(file_path.stat().st_mtime))

        # Try to extract session name (if renamed)
        # Format: "YYYY-MM-DD-HH-MM-descriptive-name.jsonl"
        name_parts = session_id.split('-')
        if len(name_parts) >= 5:
            # Has descriptive name after timestamp
            name = ' '.join(name_parts[4:]).replace('-', ' ').title()
        else:
            # Fallback: use first user message
            first_user_msg = next(
                (m.get('content', '') for m in messages if m.get('role') == 'user'),
                'Untitled session'
            )
            name = first_user_msg[:50] + ('...' if len(first_user_msg) > 50 else '')

        # Count messages and tool calls
        message_count = len([m for m in messages if m.get('role') in ['user', 'assistant']])
        tool_call_count = len([m for m in messages if m.get('role') == 'tool'])

        return {
            'id': session_id,
            'timestamp': timestamp,
            'name': name,
            'messages': messages,
            'message_count': message_count,
            'tool_call_count': tool_call_count
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
        json.dumps(session_data['messages']),
        session_data['message_count'],
        session_data['tool_call_count']
    ))

    # Insert into FTS index
    # Extract searchable content (user + assistant messages)
    content_parts = []
    for msg in session_data['messages']:
        if msg.get('role') in ['user', 'assistant']:
            content = msg.get('content', '')
            if content:
                content_parts.append(content)

    searchable_content = '\n\n'.join(content_parts)

    conn.execute("""
        INSERT INTO session_history_fts (id, name, content)
        VALUES (?, ?, ?)
    """, (
        session_data['id'],
        session_data['name'],
        searchable_content
    ))

    conn.commit()
    conn.close()

    print(f"✅ Saved {session_data['id']}: {session_data['name'][:40]}")


def seed_all_sessions():
    """Scan session directory and seed all .jsonl files."""
    if not SESSION_DIR.exists():
        print(f"❌ Session directory not found: {SESSION_DIR}")
        return

    session_files = list(SESSION_DIR.glob("*.jsonl"))
    print(f"\n📁 Found {len(session_files)} session files in {SESSION_DIR}")

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
    print(f"\n📊 Database: {DB_PATH}")

    # Show sample stats
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(*) FROM session_history")
    total = cursor.fetchone()[0]

    cursor = conn.execute("SELECT SUM(message_count) FROM session_history")
    total_messages = cursor.fetchone()[0]

    cursor = conn.execute("SELECT SUM(tool_call_count) FROM session_history")
    total_tool_calls = cursor.fetchone()[0]

    print(f"\n📈 Database stats:")
    print(f"   Total sessions: {total:,}")
    print(f"   Total messages: {total_messages:,}")
    print(f"   Total tool calls: {total_tool_calls:,}")

    conn.close()


if __name__ == "__main__":
    print("🌱 Session History Seeder")
    print("=" * 50)

    init_database()
    seed_all_sessions()

    print("\n✅ Done! You can now search sessions with:")
    print("   python session_history.py search 'query'")
