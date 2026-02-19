"""
Cross-project sharing — persistent database layer (Feature 27)

Stores shared insights in SQLite via the db_pool connection pooling system.
Enables sharing memory insights between projects with deduplication,
per-project enable/disable controls, and sharing statistics.

Usage:
    from memory_system.cross_project_sharing_db import CrossProjectSharer

    sharer = CrossProjectSharer()
    result = sharer.share(memory, target_project='other-project', relevance_score=0.8)
    insights = sharer.get_shared('other-project')
"""

import sqlite3
import time
import uuid
from typing import List, Dict, Optional
from pathlib import Path

from .db_pool import get_connection
from .config import cfg


class CrossProjectSharer:
    """Persistent cross-project memory sharing with SQLite backend."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(cfg.intelligence_db_path)
        self._init_schema()

    def _init_schema(self):
        """Create shared_insights and project_sharing_config tables if not exist."""
        with get_connection(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS shared_insights (
                id TEXT PRIMARY KEY,
                source_project TEXT NOT NULL,
                target_project TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                memory_content TEXT NOT NULL,
                relevance_score REAL DEFAULT 0.0,
                created_at INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                UNIQUE(memory_id, target_project)
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS project_sharing_config (
                project_id TEXT PRIMARY KEY,
                share_enabled INTEGER DEFAULT 1,
                updated_at INTEGER NOT NULL
            )''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_shared_target ON shared_insights(target_project)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_shared_source ON shared_insights(source_project)')
            conn.commit()

    def share(self, memory: Dict, target_project: str, relevance_score: float = 0.5) -> Dict:
        """
        Share a memory insight to another project.

        Checks if target project has sharing enabled (default: enabled).
        Deduplicates by (memory_id, target_project) UNIQUE constraint.

        Args:
            memory: Dict with at least 'id', 'content', and 'project_id' keys.
            target_project: Project ID to share the insight to.
            relevance_score: 0.0-1.0 relevance score for the insight.

        Returns:
            {'shared': bool, 'id': str or None, 'reason': str}
        """
        if not self.is_sharing_enabled(target_project):
            return {'shared': False, 'id': None, 'reason': 'sharing_disabled'}

        insight_id = str(uuid.uuid4())
        memory_id = memory.get('id', str(uuid.uuid4()))
        source_project = memory.get('project_id', 'unknown')
        content = memory.get('content', '')
        now = int(time.time())

        try:
            with get_connection(self.db_path) as conn:
                conn.execute(
                    '''INSERT INTO shared_insights
                       (id, source_project, target_project, memory_id, memory_content,
                        relevance_score, created_at, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'active')''',
                    (insight_id, source_project, target_project, memory_id,
                     content, relevance_score, now)
                )
                conn.commit()
            return {'shared': True, 'id': insight_id, 'reason': 'success'}

        except sqlite3.IntegrityError:
            # UNIQUE constraint on (memory_id, target_project) — already shared
            return {'shared': False, 'id': None, 'reason': 'duplicate'}

    def get_shared(self, project_id: str) -> List[Dict]:
        """
        Get all insights shared TO this project.

        Only returns results if the project has sharing enabled
        (or has no config row, which defaults to enabled).

        Args:
            project_id: The project to retrieve shared insights for.

        Returns:
            List of insight dicts with id, source_project, memory_id,
            memory_content, relevance_score, created_at, status.
        """
        if not self.is_sharing_enabled(project_id):
            return []

        with get_connection(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                '''SELECT id, source_project, target_project, memory_id,
                          memory_content, relevance_score, created_at, status
                   FROM shared_insights
                   WHERE target_project = ? AND status = 'active'
                   ORDER BY created_at DESC''',
                (project_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def set_sharing_enabled(self, project_id: str, enabled: bool) -> None:
        """Enable or disable sharing for a project.

        Args:
            project_id: The project to configure.
            enabled: True to enable sharing, False to disable.
        """
        now = int(time.time())
        with get_connection(self.db_path) as conn:
            conn.execute(
                '''INSERT INTO project_sharing_config (project_id, share_enabled, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(project_id)
                   DO UPDATE SET share_enabled = excluded.share_enabled,
                                 updated_at = excluded.updated_at''',
                (project_id, 1 if enabled else 0, now)
            )
            conn.commit()

    def is_sharing_enabled(self, project_id: str) -> bool:
        """Check if sharing is enabled for a project.

        Returns True by default when no configuration row exists.

        Args:
            project_id: The project to check.

        Returns:
            True if sharing is enabled (or unconfigured), False if disabled.
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT share_enabled FROM project_sharing_config WHERE project_id = ?',
                (project_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return True  # Default: enabled
            return bool(row[0])

    def get_sharing_stats(self) -> Dict:
        """
        Return sharing statistics.

        Returns:
            Dict with total_shared, by_source_project, by_target_project,
            and avg_relevance.
        """
        with get_connection(self.db_path) as conn:
            # Total shared
            cursor = conn.execute('SELECT COUNT(*) FROM shared_insights')
            total = cursor.fetchone()[0]

            # By source project
            cursor = conn.execute(
                'SELECT source_project, COUNT(*) as cnt FROM shared_insights GROUP BY source_project'
            )
            by_source = {row[0]: row[1] for row in cursor.fetchall()}

            # By target project
            cursor = conn.execute(
                'SELECT target_project, COUNT(*) as cnt FROM shared_insights GROUP BY target_project'
            )
            by_target = {row[0]: row[1] for row in cursor.fetchall()}

            # Average relevance
            cursor = conn.execute('SELECT AVG(relevance_score) FROM shared_insights')
            avg_row = cursor.fetchone()[0]
            avg_relevance = round(avg_row, 4) if avg_row is not None else 0.0

            return {
                'total_shared': total,
                'by_source_project': by_source,
                'by_target_project': by_target,
                'avg_relevance': avg_relevance,
            }
