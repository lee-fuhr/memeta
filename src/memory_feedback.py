"""
Memory feedback mechanism for human quality assessment.

Provides:
- get_quality_check_batch() - Get random memories for review
- save_feedback() - Store thumbs up/down feedback
- get_quality_metrics() - Calculate quality score from feedback
- Dashboard integration functions

Database schema (intelligence.db):
    CREATE TABLE memory_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id TEXT NOT NULL,
        feedback TEXT NOT NULL CHECK (feedback IN ('good', 'bad')),
        timestamp TEXT NOT NULL,
        session_context TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )

    CREATE TABLE feedback_trigger_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_feedback_completion TEXT,
        session_count INTEGER DEFAULT 0
    )
"""

import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(__file__).parent.parent / "intelligence.db"
DEFAULT_MEMORY_DIR = Path.home() / ".local/share/memory/default/memories"
DEFAULT_BATCH_SIZE = 5
DEFAULT_DAYS_BACK = 30
DEFAULT_TRIGGER_INTERVAL = 20  # sessions


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_feedback_tables(db_path: Optional[Path] = None) -> None:
    """Initialize feedback tables if they don't exist.

    Args:
        db_path: Path to intelligence.db. Defaults to DEFAULT_DB_PATH.
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    with sqlite3.connect(db_path) as conn:
        # Feedback storage table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                feedback TEXT NOT NULL CHECK (feedback IN ('good', 'bad')),
                timestamp TEXT NOT NULL,
                session_context TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Trigger state table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback_trigger_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_feedback_completion TEXT,
                session_count INTEGER DEFAULT 0
            )
        """)

        # Initialize trigger state if empty
        conn.execute("""
            INSERT OR IGNORE INTO feedback_trigger_state (id, session_count)
            VALUES (1, 0)
        """)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def get_quality_check_batch(
    memory_dir: Optional[Path] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    days_back: int = DEFAULT_DAYS_BACK,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Get a random batch of recent memories for quality review.

    Filters:
    - Only memories from last `days_back` days
    - Excludes memories that already have feedback

    Args:
        memory_dir: Directory containing memory .md files
        batch_size: Number of memories to return
        days_back: Only include memories from this many days back
        db_path: Path to intelligence.db

    Returns:
        List of memory dicts with id, content, importance, tags, created_at
    """
    memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    init_feedback_tables(db_path)

    # Get already-reviewed memory IDs
    with sqlite3.connect(db_path) as conn:
        reviewed = conn.execute(
            "SELECT DISTINCT memory_id FROM memory_feedback"
        ).fetchall()
        reviewed_ids = {row[0] for row in reviewed}

    # Scan memory files
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    candidates = []

    if not memory_dir.exists():
        return []

    for filepath in memory_dir.glob("*.md"):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            memory_id = meta.get("id")
            if not memory_id:
                continue

            # Skip if already reviewed
            if memory_id in reviewed_ids:
                continue

            # Check if recent enough
            created_at = meta.get("created_at", "")
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created_dt < cutoff_date:
                        continue
                except (ValueError, AttributeError):
                    pass

            candidates.append({
                "id": memory_id,
                "content": body.strip(),
                "importance": meta.get("importance_weight", meta.get("importance", 0.5)),
                "tags": meta.get("semantic_tags", meta.get("tags", [])),
                "created_at": created_at,
            })

        except (OSError, UnicodeDecodeError):
            continue

    # Random sample
    if len(candidates) <= batch_size:
        return candidates

    return random.sample(candidates, batch_size)


def save_feedback(
    memory_id: str,
    feedback: str,
    session_context: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """Save human feedback for a memory.

    Args:
        memory_id: Memory ID to provide feedback for
        feedback: "good" or "bad"
        session_context: Optional context (e.g., prompt version)
        db_path: Path to intelligence.db

    Returns:
        True if saved successfully

    Raises:
        ValueError: If feedback is not "good" or "bad"
    """
    if feedback not in ("good", "bad"):
        raise ValueError(f"feedback must be 'good' or 'bad', got: {feedback}")

    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    timestamp = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO memory_feedback (memory_id, feedback, timestamp, session_context)
               VALUES (?, ?, ?, ?)""",
            (memory_id, feedback, timestamp, session_context)
        )

    return True


def get_quality_metrics(
    db_path: Optional[Path] = None,
    days_back: Optional[int] = None,
) -> dict:
    """Calculate quality metrics from feedback.

    Args:
        db_path: Path to intelligence.db
        days_back: Optional time window (only count recent feedback)

    Returns:
        Dict with total_feedback, good_count, bad_count, quality_score
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    query = "SELECT feedback FROM memory_feedback"
    params = []

    if days_back is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        query += " WHERE timestamp >= ?"
        params.append(cutoff)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return {
            "total_feedback": 0,
            "good_count": 0,
            "bad_count": 0,
            "quality_score": 0.0,
        }

    good_count = sum(1 for row in rows if row[0] == "good")
    bad_count = sum(1 for row in rows if row[0] == "bad")
    total = good_count + bad_count

    return {
        "total_feedback": total,
        "good_count": good_count,
        "bad_count": bad_count,
        "quality_score": good_count / total if total > 0 else 0.0,
    }


def get_feedback_by_context(
    session_context: str,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Get all feedback for a specific session context (e.g., prompt version).

    Args:
        session_context: Context to filter by
        db_path: Path to intelligence.db

    Returns:
        List of feedback dicts with memory_id, feedback, timestamp, session_context
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """SELECT memory_id, feedback, timestamp, session_context
               FROM memory_feedback
               WHERE session_context = ?""",
            (session_context,)
        ).fetchall()

    return [
        {
            "memory_id": row[0],
            "feedback": row[1],
            "timestamp": row[2],
            "session_context": row[3],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Trigger logic
# ---------------------------------------------------------------------------

def should_show_feedback_prompt(
    session_count: int,
    interval: int = DEFAULT_TRIGGER_INTERVAL,
    db_path: Optional[Path] = None,
) -> bool:
    """Determine if feedback prompt should be shown.

    Shows every `interval` sessions, unless recently completed (<24h ago).

    Args:
        session_count: Current session count
        interval: Show every N sessions
        db_path: Path to intelligence.db

    Returns:
        True if feedback prompt should be shown
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    # Check if session count hits interval
    if session_count % interval != 0:
        return False

    # Check if recently completed
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_feedback_completion FROM feedback_trigger_state WHERE id = 1"
        ).fetchone()

    if row and row[0]:
        try:
            last_completion = datetime.fromisoformat(row[0])
            time_since = datetime.now(timezone.utc) - last_completion

            # Don't show if completed < 24 hours ago
            if time_since < timedelta(hours=24):
                return False
        except (ValueError, TypeError):
            pass

    return True


def mark_feedback_completed(db_path: Optional[Path] = None) -> None:
    """Mark that user completed feedback round.

    Args:
        db_path: Path to intelligence.db
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    timestamp = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE feedback_trigger_state SET last_feedback_completion = ? WHERE id = 1",
            (timestamp,)
        )


def increment_session_count(db_path: Optional[Path] = None) -> int:
    """Increment and return session count.

    Args:
        db_path: Path to intelligence.db

    Returns:
        New session count
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    init_feedback_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE feedback_trigger_state SET session_count = session_count + 1 WHERE id = 1"
        )
        row = conn.execute(
            "SELECT session_count FROM feedback_trigger_state WHERE id = 1"
        ).fetchone()

    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from memory file.

    Args:
        text: Full file content

    Returns:
        Tuple of (frontmatter_dict, body_content)
    """
    text = text.strip()

    if not text.startswith("---"):
        return {}, text

    rest = text[3:].lstrip("\n")
    closing_idx = rest.find("\n---")

    if closing_idx == -1:
        return {}, text

    frontmatter_text = rest[:closing_idx]
    body = rest[closing_idx + 4:].strip()

    meta = {}
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_idx = line.find(":")
        if colon_idx == -1:
            continue

        key = line[:colon_idx].strip()
        value = line[colon_idx + 1:].strip()

        # Parse common types
        if value.lower() in ("null", "none", "~"):
            meta[key] = None
        elif value.lower() == "true":
            meta[key] = True
        elif value.lower() == "false":
            meta[key] = False
        elif value.startswith("[") and value.endswith("]"):
            try:
                meta[key] = json.loads(value)
            except json.JSONDecodeError:
                meta[key] = value
        else:
            try:
                meta[key] = float(value)
                if meta[key] == int(meta[key]) and "." not in value:
                    meta[key] = int(meta[key])
            except ValueError:
                meta[key] = value

    return meta, body
