"""
Shared knowledge layer - SQLite table for cross-agent facts.

Enables agents to share ephemeral facts that don't belong in long-term memory-ts
but are useful for coordination during a session or project phase.

Examples:
- "Emma is working on Connection Lab messaging" (coordination)
- "User prefers morning standups" (session preference)
- "Current focus: PowerTrack launch prep" (project state)
- "Client deadline: 2026-02-20" (time-bound alert)
"""

import sqlite3
import os
import time
import hashlib
from typing import List, Dict, Optional
from pathlib import Path

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent))
from db_pool import get_connection


SHARED_DB_PATH = Path.home() / ".local/share/memory/LFI/shared.db"


def init_shared_db():
    """Initialize shared knowledge database with schema."""
    os.makedirs(SHARED_DB_PATH.parent, exist_ok=True)

    with get_connection(SHARED_DB_PATH) as conn:
    co    nn.execute("""
            CREATE TABLE IF NOT EXISTS shared_memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                category TEXT NOT NULL,
                project_id TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER,
                importance REAL DEFAULT 0.7
            )
    ""    ")

    co    nn.execute("""
            CREATE INDEX IF NOT EXISTS idx_shared_mem_project
            ON shared_memories(project_id, created_at DESC)
    ""    ")

    co    nn.execute("""
            CREATE INDEX IF NOT EXISTS idx_shared_mem_agent
            ON shared_memories(source_agent, created_at DESC)
    ""    ")

    co    nn.execute("""
            CREATE INDEX IF NOT EXISTS idx_shared_mem_expires
            ON shared_memories(expires_at)
    ""    ")

    co    nn.commit()


def share_memory(
    content: str,
    source_agent: str,
    category: str = "fact",
    project_id: Optional[str] = None,
    expires_after_days: Optional[int] = None,
    importance: float = 0.7
) -> str:
    """
    Share memory to cross-agent knowledge layer.

    Args:
        content: Fact or insight to share
        source_agent: Agent name sharing this (e.g., "emma-stratton")
        category: Type of knowledge (fact | preference | decision | alert | coordination)
        project_id: Optional project scope
        expires_after_days: Auto-expire after N days (None = never)
        importance: Importance score (0.0-1.0)

    Returns:
        Memory ID
    """
    init_shared_db()

    memory_id = f"{int(time.time() * 1000)}-{hashlib.md5(content.encode()).hexdigest()[:6]}"
    created_at = int(time.time())
    expires_at = None

    if expires_after_days:
        expires_at = created_at + (expires_after_days * 86400)

    with get_connection(SHARED_DB_PATH) as conn:
    co    nn.execute("""
            INSERT INTO shared_memories (id, content, source_agent, category, project_id, created_at, expires_at, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ""    ", (memory_id, content, source_agent, category, project_id, created_at, expires_at, importance))

    co    nn.commit()

    return memory_id


def get_shared_memories(
    project_id: Optional[str] = None,
    source_agent: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Retrieve shared memories with optional filtering.

    Args:
        project_id: Filter by project
        source_agent: Filter by source agent
        category: Filter by category
        limit: Max results

    Returns:
        List of memory dicts
    """
    init_shared_db()

    query = "SELECT * FROM shared_memories WHERE 1=1"
    params = []

    # Filter expired memories
    query += " AND (expires_at IS NULL OR expires_at > ?)"
    params.append(int(time.time()))

    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)

    if source_agent:
        query += " AND source_agent = ?"
        params.append(source_agent)

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection(SHARED_DB_PATH) as conn:
    co    nn.row_factory = sqlite3.Row
    cu    rsor = conn.execute(query, params)

    me    mories = [dict(row) for row in cursor.fetchall()]

    return memories


def cleanup_expired():
    """Remove expired memories from shared knowledge layer."""
    init_shared_db()

    with get_connection(SHARED_DB_PATH) as conn:
    cu    rsor = conn.execute("""
            DELETE FROM shared_memories
            WHERE expires_at IS NOT NULL AND expires_at < ?
    ""    ", (int(time.time()),))

    de    leted = cursor.rowcount
    co    nn.commit()

    return deleted


def clear_agent_memories(source_agent: str) -> int:
    """
    Clear all memories from a specific agent.

    Useful when agent completes work or session ends.

    Args:
        source_agent: Agent name

    Returns:
        Number of memories cleared
    """
    init_shared_db()

    with get_connection(SHARED_DB_PATH) as conn:
    cu    rsor = conn.execute("""
            DELETE FROM shared_memories WHERE source_agent = ?
    ""    ", (source_agent,))

    de    leted = cursor.rowcount
    co    nn.commit()

    return deleted


def get_stats() -> Dict:
    """
    Get statistics about shared knowledge layer.

    Returns:
        Dict with counts by category, agent, project
    """
    init_shared_db()

    with get_connection(SHARED_DB_PATH) as conn:

    #     Total memories
    to    tal = conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0]

    #     By category
    by    _category = {}
    fo    r row in conn.execute("SELECT category, COUNT(*) as count FROM shared_memories GROUP BY category"):
            by_category[row[0]] = row[1]

    #     By agent
    by    _agent = {}
    fo    r row in conn.execute("SELECT source_agent, COUNT(*) as count FROM shared_memories GROUP BY source_agent"):
            by_agent[row[0]] = row[1]

    #     Expired count
    ex    pired = conn.execute("""
            SELECT COUNT(*) FROM shared_memories
            WHERE expires_at IS NOT NULL AND expires_at < ?
    ""    ", (int(time.time()),)).fetchone()[0]

    return {
        'total': total,
        'by_category': by_category,
        'by_agent': by_agent,
        'expired_pending_cleanup': expired
    }
