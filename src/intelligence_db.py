"""
Shared intelligence database for Features 23-75

Central SQLite database with schema namespacing by feature.
Enables cross-feature queries and unified storage.

Uses connection pooling via db_pool for better concurrency
and reduced SQLITE_BUSY errors.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

from memory_system.db_pool import get_pool, close_all_pools


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

    Connection management:
    - Uses connection pooling from db_pool module
    - self.conn provides a PooledConnection for backward compatibility
    - PooledConnection proxies all operations to the underlying SQLite connection
    - close() returns the connection to the pool instead of destroying it
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
        self._pool = get_pool(str(self.db_path))
        self.conn = self._pool.get_connection()
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

        # Feature 51: Temporal pattern prediction
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS temporal_patterns (
                id TEXT PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                trigger_condition TEXT NOT NULL,
                predicted_need TEXT NOT NULL,
                memory_ids TEXT,
                confidence REAL DEFAULT 0.5,
                occurrence_count INTEGER DEFAULT 0,
                dismissed_count INTEGER DEFAULT 0,
                last_confirmed INTEGER,
                last_dismissed INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # memory_access_log table is owned by access_tracker.py — do not recreate here

        # Indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_voice_project ON voice_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_image_project ON image_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_language ON code_memories(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_project ON code_memories(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_project ON decision_journal(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_outcome ON decision_journal(outcome_success)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_date ON decision_journal(decided_at)")

        # F25: Memory clustering
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_clusters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                memory_ids TEXT NOT NULL,
                centroid_embedding BLOB,
                cohesion_score REAL,
                member_count INTEGER NOT NULL,
                project_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # F26: Memory summarization
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_summaries (
                id TEXT PRIMARY KEY,
                summary_type TEXT NOT NULL,
                target_id TEXT,
                period_start INTEGER,
                period_end INTEGER,
                summary TEXT NOT NULL,
                memory_count INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        # F51: Temporal patterns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_temporal_pattern_type ON temporal_patterns(pattern_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_temporal_trigger ON temporal_patterns(trigger_condition)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_temporal_confidence ON temporal_patterns(confidence DESC)")
        # memory_access_log indexes owned by access_tracker.py — do not recreate here

        # F25: Clustering indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_project ON memory_clusters(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_cohesion ON memory_clusters(cohesion_score DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_size ON memory_clusters(member_count DESC)")

        # F26: Summarization indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_type ON memory_summaries(summary_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_target ON memory_summaries(target_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_period ON memory_summaries(period_start, period_end)")

        self.conn.commit()

    def close(self):
        """Return connection to pool.

        The PooledConnection.close() method returns the connection to
        the pool rather than destroying it, enabling reuse.
        Safe to call multiple times.
        """
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Return connection to pool on context exit"""
        self.close()
