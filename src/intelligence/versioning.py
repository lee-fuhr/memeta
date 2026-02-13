"""
Memory versioning - Track memory evolution over time (Feature 23)

Store edit history for each memory, enable rollback, diff view, and
"why did this change?" queries.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from .database import IntelligenceDB


@dataclass
class MemoryVersion:
    """A specific version of a memory"""
    version: int
    memory_id: str
    content: str
    importance: float
    changed_by: str
    change_reason: Optional[str]
    timestamp: int


class MemoryVersioning:
    """
    Tracks memory evolution through versioning

    Every edit creates a new version entry. Enables:
    - Complete edit history
    - Rollback to any previous version
    - Diff between versions
    - "Why did this change?" queries
    """

    def __init__(self, db: Optional[IntelligenceDB] = None):
        """
        Initialize versioning system

        Args:
            db: Intelligence database instance (creates new if None)
        """
        self.db = db or IntelligenceDB()

    def create_version(
        self,
        memory_id: str,
        content: str,
        importance: float,
        changed_by: str = "user",
        change_reason: Optional[str] = None
    ) -> MemoryVersion:
        """
        Create a new version entry for a memory

        Args:
            memory_id: Memory identifier
            content: Memory content at this version
            importance: Importance score (0.0-1.0)
            changed_by: Who made the change (user | llm | system)
            change_reason: Why it changed (optional)

        Returns:
            MemoryVersion object
        """
        timestamp = int(time.time())

        # Get next version number
        conn = self.db._connect()
        cursor = conn.execute(
            "SELECT MAX(version) FROM memory_versions WHERE memory_id = ?",
            (memory_id,)
        )
        max_version = cursor.fetchone()[0]
        version = (max_version or 0) + 1

        # Insert new version
        conn.execute(
            """INSERT INTO memory_versions
               (memory_id, version, content, importance, changed_by, change_reason, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (memory_id, version, content, importance, changed_by, change_reason, timestamp)
        )
        conn.commit()
        conn.close()

        return MemoryVersion(
            version=version,
            memory_id=memory_id,
            content=content,
            importance=importance,
            changed_by=changed_by,
            change_reason=change_reason,
            timestamp=timestamp
        )

    def get_version_history(self, memory_id: str) -> List[MemoryVersion]:
        """
        Get all versions of a memory, sorted oldest to newest

        Args:
            memory_id: Memory identifier

        Returns:
            List of MemoryVersion objects
        """
        conn = self.db._connect()
        cursor = conn.execute(
            """SELECT version, memory_id, content, importance, changed_by, change_reason, timestamp
               FROM memory_versions
               WHERE memory_id = ?
               ORDER BY version ASC""",
            (memory_id,)
        )
        versions = [
            MemoryVersion(
                version=row[0],
                memory_id=row[1],
                content=row[2],
                importance=row[3],
                changed_by=row[4],
                change_reason=row[5],
                timestamp=row[6]
            )
            for row in cursor.fetchall()
        ]
        conn.close()
        return versions

    def get_version(self, memory_id: str, version_number: int) -> Optional[MemoryVersion]:
        """
        Get a specific version of a memory

        Args:
            memory_id: Memory identifier
            version_number: Version to retrieve

        Returns:
            MemoryVersion object or None if not found
        """
        conn = self.db._connect()
        cursor = conn.execute(
            """SELECT version, memory_id, content, importance, changed_by, change_reason, timestamp
               FROM memory_versions
               WHERE memory_id = ? AND version = ?""",
            (memory_id, version_number)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return MemoryVersion(
            version=row[0],
            memory_id=row[1],
            content=row[2],
            importance=row[3],
            changed_by=row[4],
            change_reason=row[5],
            timestamp=row[6]
        )

    def get_latest_version(self, memory_id: str) -> Optional[MemoryVersion]:
        """
        Get the most recent version of a memory

        Args:
            memory_id: Memory identifier

        Returns:
            MemoryVersion object or None if no versions exist
        """
        conn = self.db._connect()
        cursor = conn.execute(
            """SELECT version, memory_id, content, importance, changed_by, change_reason, timestamp
               FROM memory_versions
               WHERE memory_id = ?
               ORDER BY version DESC
               LIMIT 1""",
            (memory_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return MemoryVersion(
            version=row[0],
            memory_id=row[1],
            content=row[2],
            importance=row[3],
            changed_by=row[4],
            change_reason=row[5],
            timestamp=row[6]
        )

    def diff_versions(
        self,
        memory_id: str,
        version_a: int,
        version_b: int
    ) -> Optional[Dict]:
        """
        Show differences between two versions

        Args:
            memory_id: Memory identifier
            version_a: First version number
            version_b: Second version number

        Returns:
            Dict with diff information, or None if versions don't exist
        """
        va = self.get_version(memory_id, version_a)
        vb = self.get_version(memory_id, version_b)

        if va is None or vb is None:
            return None

        return {
            'memory_id': memory_id,
            'version_a': version_a,
            'version_b': version_b,
            'content_changed': va.content != vb.content,
            'importance_changed': va.importance != vb.importance,
            'content_diff': {
                'before': va.content,
                'after': vb.content
            },
            'importance_diff': {
                'before': va.importance,
                'after': vb.importance
            },
            'time_between_seconds': vb.timestamp - va.timestamp,
            'changed_by_a': va.changed_by,
            'changed_by_b': vb.changed_by,
            'change_reason_a': va.change_reason,
            'change_reason_b': vb.change_reason
        }

    def rollback_to_version(
        self,
        memory_id: str,
        version_number: int
    ) -> Optional[MemoryVersion]:
        """
        Rollback memory to a specific version

        This creates a NEW version with the old content (doesn't delete history).

        Args:
            memory_id: Memory identifier
            version_number: Version to rollback to

        Returns:
            New MemoryVersion created from rollback, or None if version doesn't exist
        """
        target_version = self.get_version(memory_id, version_number)
        if target_version is None:
            return None

        # Create new version with old content
        return self.create_version(
            memory_id=memory_id,
            content=target_version.content,
            importance=target_version.importance,
            changed_by="system",
            change_reason=f"Rollback to version {version_number}"
        )

    def get_version_count(self, memory_id: str) -> int:
        """
        Get total number of versions for a memory

        Args:
            memory_id: Memory identifier

        Returns:
            Number of versions
        """
        conn = self.db._connect()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = ?",
            (memory_id,)
        )
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_all_versioned_memories(self) -> List[str]:
        """
        Get list of all memory IDs that have versions

        Returns:
            List of memory IDs
        """
        conn = self.db._connect()
        cursor = conn.execute(
            "SELECT DISTINCT memory_id FROM memory_versions ORDER BY memory_id"
        )
        memory_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return memory_ids

    def get_recent_changes(self, limit: int = 10) -> List[MemoryVersion]:
        """
        Get recently changed memories across all memories

        Args:
            limit: Maximum number of results

        Returns:
            List of MemoryVersion objects, most recent first
        """
        conn = self.db._connect()
        cursor = conn.execute(
            """SELECT version, memory_id, content, importance, changed_by, change_reason, timestamp
               FROM memory_versions
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,)
        )
        versions = [
            MemoryVersion(
                version=row[0],
                memory_id=row[1],
                content=row[2],
                importance=row[3],
                changed_by=row[4],
                change_reason=row[5],
                timestamp=row[6]
            )
            for row in cursor.fetchall()
        ]
        conn.close()
        return versions
