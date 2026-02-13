"""
Shared intelligence database for Features 33-42

Single SQLite database with schema namespacing per feature.
Enables cross-feature queries and keeps architecture simple.
"""

import sqlite3
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime


DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "intelligence.db"


class IntelligenceDB:
    """
    Shared database for AI analysis and integration features

    Schema namespacing:
    - sentiment_patterns: Feature 33 (sentiment tracking)
    - learning_velocity: Feature 34 (velocity metrics)
    - personality_drift: Feature 35 (style evolution)
    - conflict_predictions: Feature 37 (conflict prediction)
    - obsidian_sync_state: Feature 38 (Obsidian sync)
    - notion_sync_state: Feature 39 (Notion sync)
    - roam_sync_state: Feature 40 (Roam sync)
    - email_patterns: Feature 41 (email intelligence)
    - meeting_memories: Feature 42 (meeting intelligence)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection

        Args:
            db_path: Path to SQLite database (defaults to intelligence.db in project root)
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create all tables for Features 33-42"""
        cursor = self.conn.cursor()

        # Feature 33: Sentiment tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sentiment TEXT NOT NULL CHECK(sentiment IN ('frustrated', 'satisfied', 'neutral')),
                trigger_words TEXT,
                context TEXT,
                memory_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_session ON sentiment_patterns(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_timestamp ON sentiment_patterns(timestamp)")

        # Feature 34: Learning velocity
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_velocity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                total_memories INTEGER NOT NULL DEFAULT 0,
                corrections INTEGER NOT NULL DEFAULT 0,
                correction_rate REAL NOT NULL DEFAULT 0.0,
                velocity_score REAL NOT NULL DEFAULT 0.0,
                acceleration REAL,
                window_days INTEGER NOT NULL DEFAULT 30,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_velocity_date ON learning_velocity(date, window_days)")

        # Feature 35: Personality drift
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS personality_drift (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                directness_score REAL NOT NULL,
                verbosity_score REAL NOT NULL,
                formality_score REAL NOT NULL,
                sample_size INTEGER NOT NULL,
                drift_magnitude REAL,
                is_intentional BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_personality_date ON personality_drift(date)")

        # Feature 37: Conflict prediction
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conflict_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                new_memory_hash TEXT NOT NULL,
                predicted_conflict_id TEXT,
                confidence_score REAL NOT NULL,
                reasoning TEXT,
                was_accurate BOOLEAN,
                user_action TEXT CHECK(user_action IN ('save_anyway', 'skip', 'merge', 'replace')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conflict_hash ON conflict_predictions(new_memory_hash)")

        # Feature 38: Obsidian sync state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS obsidian_sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL UNIQUE,
                obsidian_file_path TEXT NOT NULL,
                last_sync_at TEXT NOT NULL,
                sync_direction TEXT CHECK(sync_direction IN ('to_obsidian', 'from_obsidian', 'bidirectional')),
                checksum TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_obsidian_memory ON obsidian_sync_state(memory_id)")

        # Feature 39: Notion sync state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notion_sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL UNIQUE,
                notion_page_id TEXT NOT NULL,
                notion_database_id TEXT,
                last_sync_at TEXT NOT NULL,
                sync_status TEXT CHECK(sync_status IN ('synced', 'pending', 'error')),
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notion_memory ON notion_sync_state(memory_id)")

        # Feature 40: Roam sync state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roam_sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL UNIQUE,
                roam_block_uid TEXT NOT NULL,
                daily_note_date TEXT NOT NULL,
                last_sync_at TEXT NOT NULL,
                graph_links TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_roam_memory ON roam_sync_state(memory_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_roam_date ON roam_sync_state(daily_note_date)")

        # Feature 41: Email patterns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL CHECK(pattern_type IN ('categorization', 'threading', 'priority')),
                pattern_rule TEXT NOT NULL,
                confidence REAL NOT NULL,
                learned_from_corrections INTEGER NOT NULL DEFAULT 0,
                success_rate REAL,
                last_applied_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_pattern_type ON email_patterns(pattern_type)")

        # Feature 42: Meeting memories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meeting_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                meeting_id TEXT NOT NULL,
                transcript_db_path TEXT,
                meeting_date TEXT,
                participants TEXT,
                extracted_at TEXT NOT NULL,
                relevance_score REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meeting_memory ON meeting_memories(memory_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_meeting_id ON meeting_memories(meeting_id)")

        self.conn.commit()

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup"""
        self.close()

    # Feature 33: Sentiment tracking
    def log_sentiment(self, session_id: str, sentiment: str, trigger_words: Optional[str] = None,
                     context: Optional[str] = None, memory_id: Optional[str] = None) -> int:
        """Log sentiment pattern"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO sentiment_patterns (session_id, timestamp, sentiment, trigger_words, context, memory_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, datetime.now().isoformat(), sentiment, trigger_words, context, memory_id))
        self.conn.commit()
        return cursor.lastrowid

    def get_sentiment_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get recent sentiment patterns"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM sentiment_patterns
            WHERE timestamp >= date('now', '-' || ? || ' days')
            ORDER BY timestamp DESC
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]

    # Feature 34: Learning velocity
    def record_velocity(self, date: str, total_memories: int, corrections: int,
                       velocity_score: float, window_days: int = 30) -> int:
        """Record learning velocity metrics"""
        correction_rate = corrections / total_memories if total_memories > 0 else 0.0
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO learning_velocity
            (date, total_memories, corrections, correction_rate, velocity_score, window_days)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date, total_memories, corrections, correction_rate, velocity_score, window_days))
        self.conn.commit()
        return cursor.lastrowid

    def get_velocity_trend(self, days: int = 90) -> List[Dict[str, Any]]:
        """Get velocity trend over time"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM learning_velocity
            WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY date ASC
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]

    # Feature 35: Personality drift
    def record_personality_snapshot(self, date: str, directness: float, verbosity: float,
                                   formality: float, sample_size: int) -> int:
        """Record personality metrics snapshot"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO personality_drift
            (date, directness_score, verbosity_score, formality_score, sample_size)
            VALUES (?, ?, ?, ?, ?)
        """, (date, directness, verbosity, formality, sample_size))
        self.conn.commit()
        return cursor.lastrowid

    def get_personality_evolution(self, days: int = 180) -> List[Dict[str, Any]]:
        """Get personality evolution over time"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM personality_drift
            WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY date ASC
        """, (days,))
        return [dict(row) for row in cursor.fetchall()]

    # Feature 37: Conflict prediction
    def log_conflict_prediction(self, memory_hash: str, predicted_conflict_id: Optional[str],
                               confidence: float, reasoning: str) -> int:
        """Log a conflict prediction"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO conflict_predictions
            (new_memory_hash, predicted_conflict_id, confidence_score, reasoning)
            VALUES (?, ?, ?, ?)
        """, (memory_hash, predicted_conflict_id, confidence, reasoning))
        self.conn.commit()
        return cursor.lastrowid

    def update_prediction_accuracy(self, prediction_id: int, was_accurate: bool, user_action: str):
        """Update prediction with actual outcome"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE conflict_predictions
            SET was_accurate = ?, user_action = ?, resolved_at = ?
            WHERE id = ?
        """, (was_accurate, user_action, datetime.now().isoformat(), prediction_id))
        self.conn.commit()

    # Feature 38-40: Sync state helpers
    def update_sync_state(self, table: str, memory_id: str, **kwargs):
        """Generic sync state updater"""
        cursor = self.conn.cursor()
        fields = ', '.join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [memory_id]
        cursor.execute(f"""
            UPDATE {table}
            SET {fields}
            WHERE memory_id = ?
        """, values)
        self.conn.commit()

    # Feature 41: Email patterns
    def add_email_pattern(self, pattern_type: str, pattern_rule: str, confidence: float) -> int:
        """Add learned email pattern"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO email_patterns (pattern_type, pattern_rule, confidence)
            VALUES (?, ?, ?)
        """, (pattern_type, pattern_rule, confidence))
        self.conn.commit()
        return cursor.lastrowid

    def get_email_patterns(self, pattern_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get email patterns, optionally filtered by type"""
        cursor = self.conn.cursor()
        if pattern_type:
            cursor.execute("SELECT * FROM email_patterns WHERE pattern_type = ?", (pattern_type,))
        else:
            cursor.execute("SELECT * FROM email_patterns")
        return [dict(row) for row in cursor.fetchall()]

    # Feature 42: Meeting memories
    def link_memory_to_meeting(self, memory_id: str, meeting_id: str, meeting_date: Optional[str] = None,
                               participants: Optional[str] = None, relevance_score: float = 0.8) -> int:
        """Link a memory to a meeting transcript"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO meeting_memories
            (memory_id, meeting_id, meeting_date, participants, extracted_at, relevance_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (memory_id, meeting_id, meeting_date, participants, datetime.now().isoformat(), relevance_score))
        self.conn.commit()
        return cursor.lastrowid

    def get_meeting_memories(self, meeting_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get memories linked to meetings"""
        cursor = self.conn.cursor()
        if meeting_id:
            cursor.execute("SELECT * FROM meeting_memories WHERE meeting_id = ?", (meeting_id,))
        else:
            cursor.execute("SELECT * FROM meeting_memories ORDER BY extracted_at DESC")
        return [dict(row) for row in cursor.fetchall()]
