"""
Shared intelligence database for Features 23-75

Central SQLite database with schema namespacing by feature.
Enables cross-feature queries and unified storage.
"""

import sqlite3
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from db_pool import get_connection


class IntelligenceDB:
    """
    Shared database for advanced memory features

    Schema organization:
    - voice_memories: Feature 44 (voice capture)
    - image_memories: Feature 45 (image/screenshot context)
    - code_memories: Feature 46 (code snippet library)
    - decision_journal: Feature 47 (decisions + outcomes)
    - ab_tests: Feature 48 (memory strategy experiments)
    - cross_system_imports: Feature 49 (external patterns)
    - dream_insights: Feature 50 (overnight synthesis)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize intelligence database

        Args:
            db_path: Path to SQLite database (default: intelligence.db in module dir)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"

        self.db_path = Path(db_path)
        # Initialize connection from pool (not context manager)
        from db_pool import get_pool
        pool = get_pool(str(self.db_path))
        self.conn = pool.get_connection()
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables for all intelligence features"""
        cursor = self.conn.cursor()

        # Feature 44: Voice memories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voice_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audio_path TEXT NOT NULL,
                transcript TEXT NOT NULL,
                memory_id TEXT,  -- Link to memory-ts
                duration_seconds REAL,
                created_at TEXT NOT NULL,
                project_id TEXT,
                tags TEXT,  -- JSON array
                importance REAL DEFAULT 0.5
            )
        """)

        # Feature 45: Image memories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                ocr_text TEXT,
                vision_analysis TEXT,  -- Claude vision insights
                memory_id TEXT,  -- Link to memory-ts
                created_at TEXT NOT NULL,
                project_id TEXT,
                tags TEXT,  -- JSON array
                importance REAL DEFAULT 0.5
            )
        """)

        # Feature 46: Code memories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snippet TEXT NOT NULL,
                language TEXT NOT NULL,
                description TEXT,
                context TEXT,  -- What problem it solved
                file_path TEXT,  -- Original location
                session_id TEXT,
                created_at TEXT NOT NULL,
                project_id TEXT,
                tags TEXT,  -- JSON array
                embedding BLOB,  -- For semantic search
                importance REAL DEFAULT 0.5
            )
        """)

        # Feature 47: Decision journal
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decision_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision TEXT NOT NULL,
                options_considered TEXT NOT NULL,  -- JSON array
                chosen_option TEXT NOT NULL,
                rationale TEXT NOT NULL,
                context TEXT,
                project_id TEXT,
                session_id TEXT,
                decided_at TEXT NOT NULL,
                outcome TEXT,  -- Tracked later
                outcome_success BOOLEAN,
                outcome_recorded_at TEXT,
                commitment_id TEXT,  -- Link to ea_brain if applicable
                tags TEXT  -- JSON array
            )
        """)

        # Feature 48: A/B testing experiments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                strategy_a_name TEXT NOT NULL,
                strategy_b_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                sample_size INTEGER,
                strategy_a_performance REAL,
                strategy_b_performance REAL,
                winner TEXT,  -- 'a', 'b', or 'tie'
                adopted BOOLEAN DEFAULT 0,
                notes TEXT
            )
        """)

        # Feature 49: Cross-system learning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cross_system_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_system TEXT NOT NULL,  -- e.g., "Ben's Kit"
                pattern_type TEXT NOT NULL,
                pattern_description TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                adapted BOOLEAN DEFAULT 0,
                adaptation_notes TEXT,
                effectiveness_score REAL
            )
        """)

        # Feature 50: Dream mode insights
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dream_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                memories_analyzed INTEGER,
                patterns_found TEXT,  -- JSON array
                deep_insights TEXT,
                new_connections INTEGER,
                promoted_memories INTEGER,
                runtime_seconds REAL
            )
        """)

        # Indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_voice_project ON voice_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_image_project ON image_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_language ON code_memories(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_project ON code_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_project ON decision_journal(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_outcome ON decision_journal(outcome_success)")

        self.conn.commit()

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close on context exit"""
        self.close()
