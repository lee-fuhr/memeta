"""
Intelligence database - unified schema for Features 23-32

Single SQLite database for all intelligence features with namespaced tables.
Enables cross-feature queries and maintains consistency.
"""

import sqlite3
from pathlib import Path
from typing import Optional


class IntelligenceDB:
    """
    Unified database for memory intelligence features (23-32)

    Features covered:
    - F23: Memory versioning (memory_versions table)
    - F24: Clustering (memory_clusters, cluster_labels tables)
    - F25: Relationships (memory_relationships table)
    - F26: Forgetting curve (integrates with fsrs_scheduler.py)
    - F27: Cross-project sharing (sharing_rules, sharing_log tables)
    - F28: Triggers (trigger_rules, trigger_executions tables)
    - F29: Alerts (alert_rules, alert_history tables)
    - F30: Search (search_queries, search_cache tables)
    - F31: Summarization (topic_summaries table)
    - F32: Quality scoring (quality_scores, quality_history tables)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize intelligence database

        Args:
            db_path: Path to SQLite database (default: intelligence.db in module root)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Create database connection with WAL mode and timeout"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Create all feature tables if they don't exist"""
        with self._connect() as conn:
            # F23: Memory versioning
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL,
                    changed_by TEXT DEFAULT 'user',
                    change_reason TEXT,
                    timestamp INTEGER NOT NULL,
                    UNIQUE(memory_id, version)
                )
            """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_versions_memory
            ON memory_versions(memory_id, timestamp DESC)
        """)

        # F24: Clustering & topic detection
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_clusters (
                cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_label TEXT NOT NULL,
                keywords TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_updated INTEGER NOT NULL,
                member_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cluster_memberships (
                memory_id TEXT NOT NULL,
                cluster_id INTEGER NOT NULL,
                similarity_score REAL NOT NULL,
                added_at INTEGER NOT NULL,
                PRIMARY KEY (memory_id, cluster_id),
                FOREIGN KEY (cluster_id) REFERENCES memory_clusters(cluster_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_clusters_updated
            ON memory_clusters(last_updated DESC)
        """)

        # F25: Memory relationships graph
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_memory_id TEXT NOT NULL,
                to_memory_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at INTEGER NOT NULL,
                auto_detected BOOLEAN DEFAULT FALSE,
                UNIQUE(from_memory_id, to_memory_id, relationship_type)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relationships_from
            ON memory_relationships(from_memory_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relationships_to
            ON memory_relationships(to_memory_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relationships_type
            ON memory_relationships(relationship_type)
        """)

        # F27: Cross-project sharing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sharing_rules (
                memory_id TEXT PRIMARY KEY,
                is_universal BOOLEAN DEFAULT FALSE,
                privacy_level TEXT DEFAULT 'private',
                allowed_projects TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sharing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                source_project TEXT NOT NULL,
                target_project TEXT NOT NULL,
                shared_at INTEGER NOT NULL,
                shared_by TEXT DEFAULT 'auto',
                FOREIGN KEY (memory_id) REFERENCES sharing_rules(memory_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sharing_universal
            ON sharing_rules(is_universal, privacy_level)
        """)

        # F28: Memory-triggered automations
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trigger_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                pattern TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_config TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at INTEGER NOT NULL,
                last_triggered INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trigger_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_id INTEGER NOT NULL,
                memory_id TEXT NOT NULL,
                executed_at INTEGER NOT NULL,
                success BOOLEAN NOT NULL,
                result TEXT,
                FOREIGN KEY (trigger_id) REFERENCES trigger_rules(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_triggers_enabled
            ON trigger_rules(enabled)
        """)

        # F29: Smart memory alerts
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                condition_type TEXT NOT NULL,
                condition_value TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_rule_id INTEGER,
                memory_id TEXT,
                alert_message TEXT NOT NULL,
                severity TEXT DEFAULT 'info',
                triggered_at INTEGER NOT NULL,
                dismissed BOOLEAN DEFAULT FALSE,
                dismissed_at INTEGER,
                FOREIGN KEY (alert_rule_id) REFERENCES alert_rules(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_active
            ON alert_history(dismissed, triggered_at DESC)
        """)

        # F30: Memory-aware search
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                parsed_query TEXT NOT NULL,
                filters TEXT,
                executed_at INTEGER NOT NULL,
                result_count INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                results TEXT NOT NULL,
                cached_at INTEGER NOT NULL,
                hits INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_cache_time
            ON search_cache(cached_at DESC)
        """)

        # F31: Auto-summarization
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL,
                memory_count INTEGER NOT NULL,
                generated_at INTEGER NOT NULL,
                last_updated INTEGER NOT NULL,
                memory_ids TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_summaries_updated
            ON topic_summaries(last_updated DESC)
        """)

        # F32: Quality scoring
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_scores (
                memory_id TEXT PRIMARY KEY,
                quality_score REAL NOT NULL,
                clarity_score REAL NOT NULL,
                specificity_score REAL NOT NULL,
                usefulness_score REAL NOT NULL,
                last_scored INTEGER NOT NULL,
                score_version INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                score REAL NOT NULL,
                issues TEXT,
                suggestions TEXT,
                scored_at INTEGER NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES quality_scores(memory_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_quality_low
            ON quality_scores(quality_score ASC)
        """)

        conn.commit()
        conn.close()


def get_db() -> IntelligenceDB:
    """Get singleton instance of intelligence database"""
    return IntelligenceDB()
