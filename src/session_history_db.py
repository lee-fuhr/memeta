"""
Session History Database - Full transcript storage with tool calls.

Feature 21 (Lee's proposal): Pre-compaction hook saves FULL session transcripts
to SQLite, including all tool calls. Enables cross-conversation analysis, debugging,
trend detection.

Schema:
  sessions(
    id TEXT PRIMARY KEY,
    timestamp INTEGER,
    name TEXT,
    full_transcript_json TEXT,
    message_count INTEGER,
    tool_call_count INTEGER,
    memories_extracted INTEGER,
    duration_seconds INTEGER,
    project_id TEXT,
    session_quality REAL
  )
"""

import sqlite3
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent))
from db_pool import get_connection


SESSION_DB_PATH = Path.home() / ".local/share/memory/LFI/session-history.db"


def init_session_db():
    """Initialize session history database."""
    os.makedirs(SESSION_DB_PATH.parent, exist_ok=True)

    with get_connection(SESSION_DB_PATH) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            name TEXT,
            full_transcript_json TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            memories_extracted INTEGER DEFAULT 0,
            duration_seconds INTEGER,
            project_id TEXT DEFAULT 'LFI',
            session_quality REAL DEFAULT 0.0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Indexes for fast queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_timestamp
        ON sessions(timestamp DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_project
        ON sessions(project_id, timestamp DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_quality
        ON sessions(session_quality DESC)
    """)

    # Full-text search on transcript
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
        USING fts5(id, name, transcript_text)
    """)

    conn.commit()


def save_session(
    session_id: str,
    transcript: List[Dict],
    session_name: Optional[str] = None,
    project_id: str = "LFI",
    memories_extracted: int = 0,
    session_quality: float = 0.0
) -> bool:
    """
    Save full session transcript to history database.

    Args:
        session_id: Session UUID
        transcript: Full conversation (list of message dicts)
        session_name: Optional session name
        project_id: Project identifier
        memories_extracted: Number of memories extracted
        session_quality: Quality score (0.0-1.0)

    Returns:
        True if saved successfully
    """
    init_session_db()

    # Extract metadata from transcript
    message_count = len(transcript)
    tool_call_count = 0
    first_timestamp = None
    last_timestamp = None

    for msg in transcript:
        # Count tool calls
        if msg.get('role') == 'assistant':
            content = msg.get('content', [])
            if isinstance(content, list):
                tool_call_count += sum(1 for item in content if isinstance(item, dict) and item.get('type') == 'tool_use')

        # Track timestamps
        ts = msg.get('timestamp')
        if ts:
            if isinstance(ts, str):
                ts = int(datetime.fromisoformat(ts).timestamp())
            if first_timestamp is None or ts < first_timestamp:
                first_timestamp = ts
            if last_timestamp is None or ts > last_timestamp:
                last_timestamp = ts

    # Calculate duration
    duration_seconds = None
    if first_timestamp and last_timestamp:
        duration_seconds = last_timestamp - first_timestamp

    # Use first message timestamp or now
    timestamp = first_timestamp or int(time.time())

    # Serialize transcript
    transcript_json = json.dumps(transcript, indent=2)

    # Extract text for full-text search
    transcript_text = '\n'.join([
        msg.get('content', '') if isinstance(msg.get('content'), str) else ''
        for msg in transcript
    ])

    try:
        conn = sqlite3.connect(SESSION_DB_PATH)

        # Save to main table
        conn.execute("""
            INSERT OR REPLACE INTO sessions
            (id, timestamp, name, full_transcript_json, message_count, tool_call_count,
             memories_extracted, duration_seconds, project_id, session_quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            timestamp,
            session_name,
            transcript_json,
            message_count,
            tool_call_count,
            memories_extracted,
            duration_seconds,
            project_id,
            session_quality
        ))

        # Update FTS index
        conn.execute("""
            INSERT OR REPLACE INTO sessions_fts (id, name, transcript_text)
            VALUES (?, ?, ?)
        """, (session_id, session_name or '', transcript_text))

        conn.commit()
        conn.close()

        return True

    except Exception as e:
        print(f"❌ Failed to save session {session_id}: {e}")
        return False


def search_sessions(
    query: str,
    limit: int = 20,
    project_id: Optional[str] = None
) -> List[Dict]:
    """
    Full-text search across all session transcripts.

    Args:
        query: Search query
        limit: Max results
        project_id: Optional project filter

    Returns:
        List of matching sessions with metadata
    """
    init_session_db()

    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row

    # FTS query
    sql = """
        SELECT s.*
        FROM sessions s
        JOIN sessions_fts fts ON s.id = fts.id
        WHERE sessions_fts MATCH ?
    """

    params = [query]

    if project_id:
        sql += " AND s.project_id = ?"
        params.append(project_id)

    sql += " ORDER BY s.timestamp DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results


def get_session_by_id(session_id: str) -> Optional[Dict]:
    """
    Retrieve full session by ID.

    Args:
        session_id: Session UUID

    Returns:
        Session dict with transcript, or None
    """
    init_session_db()

    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        session = dict(row)
        # Parse JSON transcript
        session['transcript'] = json.loads(session['full_transcript_json'])
        return session

    return None


def get_recent_sessions(limit: int = 10, project_id: Optional[str] = None) -> List[Dict]:
    """
    Get most recent sessions.

    Args:
        limit: Number of sessions
        project_id: Optional project filter

    Returns:
        List of session metadata (without full transcripts)
    """
    init_session_db()

    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row

    if project_id:
        cursor = conn.execute("""
            SELECT id, timestamp, name, message_count, tool_call_count,
                   memories_extracted, duration_seconds, session_quality
            FROM sessions
            WHERE project_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (project_id, limit))
    else:
        cursor = conn.execute("""
            SELECT id, timestamp, name, message_count, tool_call_count,
                   memories_extracted, duration_seconds, session_quality
            FROM sessions
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return results


def get_session_stats() -> Dict:
    """
    Get statistics about session history.

    Returns:
        Dict with total sessions, avg quality, etc.
    """
    init_session_db()

    conn = sqlite3.connect(SESSION_DB_PATH)

    # Total count
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    # Average quality
    avg_quality = conn.execute("SELECT AVG(session_quality) FROM sessions").fetchone()[0] or 0.0

    # Total messages
    total_messages = conn.execute("SELECT SUM(message_count) FROM sessions").fetchone()[0] or 0

    # Total memories
    total_memories = conn.execute("SELECT SUM(memories_extracted) FROM sessions").fetchone()[0] or 0

    conn.close()

    return {
        'total_sessions': total,
        'avg_quality': avg_quality,
        'total_messages': total_messages,
        'total_memories_extracted': total_memories
    }
