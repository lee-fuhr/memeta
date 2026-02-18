"""
Feature 29: Smart Alerts

Proactive notifications for expiring memories, detected patterns, contradictions.
Daily digest of important alerts.

Database: intelligence.db (smart_alerts, alert_log tables)
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Literal, Tuple
from dataclasses import dataclass

from memory_system.db_pool import get_connection


# Alert types
AlertType = Literal[
    "expiring_memory", "contradiction", "pattern_detected", "stale_memory", "quality_issue",
    "consolidation_summary", "memory_promoted", "reinforcement_detected",
]


@dataclass
class Alert:
    """Smart alert for memory system event"""
    alert_id: int
    alert_type: AlertType
    severity: str  # "low", "medium", "high", "critical"
    title: str
    message: str
    memory_ids: str  # JSON array of related memory IDs
    created_at: datetime
    dismissed_at: Optional[datetime]
    action_taken: bool
    metadata: str  # JSON additional data

    def to_dict(self) -> Dict:
        """Serialize alert for JSON API response."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "memory_ids": json.loads(self.memory_ids) if isinstance(self.memory_ids, str) else (self.memory_ids or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "action_taken": self.action_taken,
            "metadata": json.loads(self.metadata) if isinstance(self.metadata, str) else (self.metadata or {}),
        }


@dataclass
class AlertDigest:
    """Daily digest of alerts"""
    date: datetime
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    alerts: List[Alert]


class SmartAlerts:
    """
    Proactive notification system for memory events.

    Alert types:
    - **expiring_memory**: Memory approaching FSRS review date
    - **contradiction**: New memory contradicts existing memory
    - **pattern_detected**: Recurring pattern identified
    - **stale_memory**: Memory hasn't been accessed in long time
    - **quality_issue**: Low-quality memory detected

    Severity levels:
    - **critical**: Immediate attention required (contradictions, critical expiration)
    - **high**: Important but not urgent (patterns, upcoming review)
    - **medium**: Worth knowing (stale memories, minor quality issues)
    - **low**: FYI only (suggestions, optimizations)

    Example:
        alerts = SmartAlerts()

        # Create alert for contradiction
        alert = alerts.create_alert(
            alert_type="contradiction",
            severity="critical",
            title="Conflicting memories detected",
            message="Memory A contradicts Memory B about client preferences",
            memory_ids=["mem_001", "mem_002"]
        )

        # Get unread alerts
        unread = alerts.get_unread_alerts()

        # Get daily digest
        digest = alerts.get_daily_digest()
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize alerts system.

        Args:
            db_path: Path to intelligence.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Create alert tables."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    memory_ids TEXT,
                    created_at INTEGER NOT NULL,
                    dismissed_at INTEGER,
                    action_taken BOOLEAN DEFAULT FALSE,
                    metadata TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT DEFAULT 'user',
                    timestamp INTEGER NOT NULL,
                    notes TEXT,
                    FOREIGN KEY (alert_id) REFERENCES smart_alerts(alert_id)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_type_severity
                ON smart_alerts(alert_type, severity)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_dismissed
                ON smart_alerts(dismissed_at, created_at DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_log_alert
                ON alert_log(alert_id, timestamp DESC)
            """)

            conn.commit()

    def create_alert(
        self,
        alert_type: AlertType,
        severity: str,
        title: str,
        message: str,
        memory_ids: Optional[List[str]] = None,
        metadata: Optional[Dict] = None
    ) -> Alert:
        """
        Create a new alert.

        Args:
            alert_type: Type of alert
            severity: Severity level (low, medium, high, critical)
            title: Short alert title
            message: Detailed alert message
            memory_ids: Related memory IDs
            metadata: Additional data

        Returns:
            Created alert
        """
        now = int(time.time())
        memory_ids_json = json.dumps(memory_ids or [])
        metadata_json = json.dumps(metadata or {})

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO smart_alerts
                (alert_type, severity, title, message, memory_ids, created_at, metadata, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
            """, (alert_type, severity, title, message, memory_ids_json, now, metadata_json))

            alert_id = cursor.lastrowid
            conn.commit()

            return self.get_alert(alert_id)

    def get_alert(self, alert_id: int) -> Optional[Alert]:
        """Get alert by ID."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT alert_id, alert_type, severity, title, message,
                       memory_ids, created_at, dismissed_at, action_taken, metadata
                FROM smart_alerts
                WHERE alert_id = ?
            """, (alert_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return Alert(
                alert_id=row[0],
                alert_type=row[1],
                severity=row[2],
                title=row[3],
                message=row[4],
                memory_ids=row[5],
                created_at=datetime.fromtimestamp(row[6]),
                dismissed_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                action_taken=bool(row[8]),
                metadata=row[9]
            )

    def get_unread_alerts(
        self,
        severity: Optional[str] = None,
        alert_type: Optional[AlertType] = None,
        limit: int = 50
    ) -> List[Alert]:
        """
        Get undismissed alerts.

        Args:
            severity: Filter by severity level
            alert_type: Filter by alert type
            limit: Maximum alerts to return

        Returns:
            List of alerts, most recent first
        """
        query = """
            SELECT alert_id, alert_type, severity, title, message,
                   memory_ids, created_at, dismissed_at, action_taken, metadata
            FROM smart_alerts
            WHERE dismissed_at IS NULL
        """

        params = []
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        if alert_type:
            query += " AND alert_type = ?"
            params.append(alert_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(query, params)

            alerts = []
            for row in cursor.fetchall():
                alerts.append(Alert(
                    alert_id=row[0],
                    alert_type=row[1],
                    severity=row[2],
                    title=row[3],
                    message=row[4],
                    memory_ids=row[5],
                    created_at=datetime.fromtimestamp(row[6]),
                    dismissed_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                    action_taken=bool(row[8]),
                    metadata=row[9]
                ))

            return alerts

    def get_all_alerts(
        self,
        alert_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Alert], int]:
        """
        Get all alerts (both read and unread) with pagination.

        Args:
            alert_type: Filter by alert type (None = all)
            limit: Page size
            offset: Skip N records

        Returns:
            Tuple of (alerts_list, total_count)
        """
        count_query = "SELECT COUNT(*) FROM smart_alerts"
        query = """
            SELECT alert_id, alert_type, severity, title, message,
                   memory_ids, created_at, dismissed_at, action_taken, metadata
            FROM smart_alerts
        """

        params: list = []
        if alert_type:
            count_query += " WHERE alert_type = ?"
            query += " WHERE alert_type = ?"
            params.append(alert_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"

        with get_connection(self.db_path) as conn:
            total = conn.execute(count_query, params[:1] if alert_type else []).fetchone()[0]
            cursor = conn.execute(query, params + [limit, offset])

            alerts = []
            for row in cursor.fetchall():
                alerts.append(Alert(
                    alert_id=row[0],
                    alert_type=row[1],
                    severity=row[2],
                    title=row[3],
                    message=row[4],
                    memory_ids=row[5],
                    created_at=datetime.fromtimestamp(row[6]),
                    dismissed_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                    action_taken=bool(row[8]),
                    metadata=row[9]
                ))

        return alerts, total

    def dismiss_all(self):
        """Dismiss all unread alerts."""
        now = int(time.time())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE smart_alerts
                SET dismissed_at = ?
                WHERE dismissed_at IS NULL
            """, (now,))
            conn.commit()

    def dismiss_alert(self, alert_id: int, notes: Optional[str] = None):
        """
        Dismiss an alert.

        Args:
            alert_id: Alert to dismiss
            notes: Optional dismissal notes
        """
        now = int(time.time())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE smart_alerts
                SET dismissed_at = ?
                WHERE alert_id = ?
            """, (now, alert_id))

            conn.execute("""
                INSERT INTO alert_log (alert_id, action, timestamp, notes)
                VALUES (?, 'dismissed', ?, ?)
            """, (alert_id, now, notes))

            conn.commit()

    def mark_action_taken(self, alert_id: int, notes: Optional[str] = None):
        """
        Mark alert as action taken.

        Args:
            alert_id: Alert ID
            notes: Optional action notes
        """
        now = int(time.time())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE smart_alerts
                SET action_taken = TRUE
                WHERE alert_id = ?
            """, (alert_id,))

            conn.execute("""
                INSERT INTO alert_log (alert_id, action, timestamp, notes)
                VALUES (?, 'action_taken', ?, ?)
            """, (alert_id, now, notes))

            conn.commit()

    def get_daily_digest(self, date: Optional[datetime] = None) -> AlertDigest:
        """
        Get digest of alerts for a specific day.

        Args:
            date: Date to get digest for (default: today)

        Returns:
            AlertDigest with counts and alert list
        """
        if date is None:
            date = datetime.now()

        # Get start and end of day
        start_of_day = datetime(date.year, date.month, date.day)
        end_of_day = start_of_day + timedelta(days=1)

        start_ts = int(start_of_day.timestamp())
        end_ts = int(end_of_day.timestamp())

        with get_connection(self.db_path) as conn:
            # Get counts by severity
            cursor = conn.execute("""
                SELECT severity, COUNT(*) as count
                FROM smart_alerts
                WHERE created_at >= ? AND created_at < ?
                GROUP BY severity
            """, (start_ts, end_ts))

            counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Get all alerts for the day
            cursor = conn.execute("""
                SELECT alert_id, alert_type, severity, title, message,
                       memory_ids, created_at, dismissed_at, action_taken, metadata
                FROM smart_alerts
                WHERE created_at >= ? AND created_at < ?
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at DESC
            """, (start_ts, end_ts))

            alerts = []
            for row in cursor.fetchall():
                alerts.append(Alert(
                    alert_id=row[0],
                    alert_type=row[1],
                    severity=row[2],
                    title=row[3],
                    message=row[4],
                    memory_ids=row[5],
                    created_at=datetime.fromtimestamp(row[6]),
                    dismissed_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                    action_taken=bool(row[8]),
                    metadata=row[9]
                ))

        return AlertDigest(
            date=date,
            critical_count=counts.get('critical', 0),
            high_count=counts.get('high', 0),
            medium_count=counts.get('medium', 0),
            low_count=counts.get('low', 0),
            alerts=alerts
        )

    def get_alert_stats(self, days: int = 7) -> Dict:
        """
        Get alert statistics over time period.

        Args:
            days: Number of days to analyze

        Returns:
            Stats dictionary with counts by type and severity
        """
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())

        with get_connection(self.db_path) as conn:
            # Total counts
            cursor = conn.execute("""
                SELECT COUNT(*) FROM smart_alerts WHERE created_at >= ?
            """, (cutoff,))
            total = cursor.fetchone()[0]

            # By type
            cursor = conn.execute("""
                SELECT alert_type, COUNT(*) as count
                FROM smart_alerts
                WHERE created_at >= ?
                GROUP BY alert_type
            """, (cutoff,))
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # By severity
            cursor = conn.execute("""
                SELECT severity, COUNT(*) as count
                FROM smart_alerts
                WHERE created_at >= ?
                GROUP BY severity
            """, (cutoff,))
            by_severity = {row[0]: row[1] for row in cursor.fetchall()}

            # Dismissed rate
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN dismissed_at IS NOT NULL THEN 1 ELSE 0 END) as dismissed
                FROM smart_alerts
                WHERE created_at >= ?
            """, (cutoff,))
            row = cursor.fetchone()
            dismissed_rate = row[1] / row[0] if row[0] > 0 else 0.0

            # Action taken rate
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN action_taken THEN 1 ELSE 0 END) as acted
                FROM smart_alerts
                WHERE created_at >= ?
            """, (cutoff,))
            row = cursor.fetchone()
            action_rate = row[1] / row[0] if row[0] > 0 else 0.0

        return {
            'period_days': days,
            'total_alerts': total,
            'by_type': by_type,
            'by_severity': by_severity,
            'dismissed_rate': dismissed_rate,
            'action_taken_rate': action_rate
        }

    def cleanup_old_alerts(self, days: int = 90):
        """
        Remove old dismissed alerts.

        Args:
            days: Keep alerts from last N days
        """
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())

        with get_connection(self.db_path) as conn:
            # Delete log entries first (foreign key constraint)
            conn.execute("""
                DELETE FROM alert_log
                WHERE alert_id IN (
                    SELECT alert_id FROM smart_alerts
                    WHERE dismissed_at IS NOT NULL AND dismissed_at < ?
                )
            """, (cutoff,))

            # Then delete alerts
            conn.execute("""
                DELETE FROM smart_alerts
                WHERE dismissed_at IS NOT NULL AND dismissed_at < ?
            """, (cutoff,))

            conn.commit()
