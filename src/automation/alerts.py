"""
Feature 29: Smart Alerts

Proactive notifications for:
- Expiring memories (due for review)
- Detected patterns
- Contradictions
- Daily digest

Uses: Pushover for mobile notifications, email for digests
Database: intelligence.db (alerts table)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


@dataclass
class Alert:
    """Alert notification"""
    alert_id: int
    alert_type: str  # "expiring_memory", "pattern_detected", "contradiction", "digest"
    title: str
    message: str
    memory_ids: List[str]
    priority: int  # 0=low, 1=normal, 2=high
    created_at: datetime
    delivered_at: Optional[datetime]
    acknowledged: bool


class SmartAlerts:
    """
    Proactive notification system for memory events.
    
    Example:
        alerts = SmartAlerts()
        
        # Create alert
        alert = alerts.create_alert(
            alert_type="contradiction",
            title="Contradictory memories detected",
            message="mem_001 contradicts mem_002",
            memory_ids=["mem_001", "mem_002"],
            priority=2
        )
        
        # Get pending alerts
        pending = alerts.get_pending_alerts()
        
        # Mark delivered
        alerts.mark_delivered(alert.alert_id)
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    memory_ids TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    delivered_at INTEGER,
                    acknowledged BOOLEAN DEFAULT FALSE
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_pending
                ON alerts(delivered_at, priority DESC)
            """)
            
            conn.commit()

    def create_alert(
        self,
        alert_type: str,
        title: str,
        message: str,
        memory_ids: List[str],
        priority: int = 1
    ) -> Alert:
        """Create new alert."""
        import json
        now = int(datetime.now().timestamp())
        
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO alerts (alert_type, title, message, memory_ids, priority, created_at, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, FALSE)
            """, (alert_type, title, message, json.dumps(memory_ids), priority, now))
            
            alert_id = cursor.lastrowid
            conn.commit()
            
            return self.get_alert(alert_id)

    def get_alert(self, alert_id: int) -> Optional[Alert]:
        """Get alert by ID."""
        import json
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT alert_id, alert_type, title, message, memory_ids, priority,
                       created_at, delivered_at, acknowledged
                FROM alerts
                WHERE alert_id = ?
            """, (alert_id,))
            
            row = cursor.fetchone()
            if row is None:
                return None
                
            return Alert(
                alert_id=row[0],
                alert_type=row[1],
                title=row[2],
                message=row[3],
                memory_ids=json.loads(row[4]),
                priority=row[5],
                created_at=datetime.fromtimestamp(row[6]),
                delivered_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                acknowledged=bool(row[8])
            )

    def get_pending_alerts(self, priority: Optional[int] = None) -> List[Alert]:
        """Get alerts not yet delivered."""
        import json
        with get_connection(self.db_path) as conn:
            if priority is not None:
                query = "SELECT * FROM alerts WHERE delivered_at IS NULL AND priority = ? ORDER BY priority DESC, created_at"
                params = (priority,)
            else:
                query = "SELECT * FROM alerts WHERE delivered_at IS NULL ORDER BY priority DESC, created_at"
                params = ()
            
            cursor = conn.execute(query, params)
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append(Alert(
                    alert_id=row[0],
                    alert_type=row[1],
                    title=row[2],
                    message=row[3],
                    memory_ids=json.loads(row[4]),
                    priority=row[5],
                    created_at=datetime.fromtimestamp(row[6]),
                    delivered_at=datetime.fromtimestamp(row[7]) if row[7] else None,
                    acknowledged=bool(row[8])
                ))
            
            return alerts

    def mark_delivered(self, alert_id: int):
        """Mark alert as delivered."""
        now = int(datetime.now().timestamp())
        with get_connection(self.db_path) as conn:
            conn.execute("UPDATE alerts SET delivered_at = ? WHERE alert_id = ?", (now, alert_id))
            conn.commit()

    def acknowledge_alert(self, alert_id: int):
        """Mark alert as acknowledged by user."""
        with get_connection(self.db_path) as conn:
            conn.execute("UPDATE alerts SET acknowledged = TRUE WHERE alert_id = ?", (alert_id,))
            conn.commit()
