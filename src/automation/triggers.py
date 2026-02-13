"""
Feature 28: Memory Triggers

Rule engine: "When memory X detected, execute action Y"

Examples:
- "When client mentions deadline, add to Todoist"
- "When frustration detected, send Pushover notification"
- "When new insight about Client X, tag with project"

Database: intelligence.db (memory_triggers, trigger_log tables)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Literal, Callable
from dataclasses import dataclass

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection


# Action types
ActionType = Literal["todoist_task", "pushover_notification", "tag_memory", "run_script", "webhook"]


@dataclass
class Trigger:
    """Memory trigger rule"""
    trigger_id: int
    name: str
    condition_type: str  # "keyword_match", "pattern_match", "importance_threshold", "custom"
    condition_value: str  # JSON config for condition
    action_type: ActionType
    action_config: str  # JSON config for action
    enabled: bool
    created_at: datetime
    last_triggered: Optional[datetime]
    trigger_count: int


@dataclass
class TriggerExecution:
    """Log entry for trigger execution"""
    id: int
    trigger_id: int
    memory_id: str
    executed_at: datetime
    success: bool
    error_message: Optional[str]


class MemoryTriggers:
    """
    Rule engine for automated actions based on memory detection.

    Condition types:
    - **keyword_match**: Memory contains specific keywords
    - **pattern_match**: Regex pattern match on content
    - **importance_threshold**: Memory importance >= threshold
    - **custom**: Python callable for complex logic

    Action types:
    - **todoist_task**: Create Todoist task
    - **pushover_notification**: Send mobile notification
    - **tag_memory**: Add tag to memory
    - **run_script**: Execute Python script
    - **webhook**: POST to URL

    Example:
        triggers = MemoryTriggers()

        # Create trigger: deadline mention → Todoist
        trigger = triggers.create_trigger(
            name="Deadline to Todoist",
            condition_type="keyword_match",
            condition_value=json.dumps({"keywords": ["deadline", "due date"]}),
            action_type="todoist_task",
            action_config=json.dumps({"project": "Client Work"})
        )

        # Check memory against triggers
        triggers.check_memory("mem_001", "Client mentioned deadline next Friday")
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize triggers system.

        Args:
            db_path: Path to intelligence.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

        # Action handlers
        self._action_handlers: Dict[ActionType, Callable] = {
            "todoist_task": self._action_todoist_task,
            "pushover_notification": self._action_pushover,
            "tag_memory": self._action_tag_memory,
            "run_script": self._action_run_script,
            "webhook": self._action_webhook
        }

    def _init_db(self):
        """Create trigger tables."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_triggers (
                    trigger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    condition_type TEXT NOT NULL,
                    condition_value TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_config TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at INTEGER NOT NULL,
                    last_triggered INTEGER,
                    trigger_count INTEGER DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS trigger_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_id INTEGER NOT NULL,
                    memory_id TEXT NOT NULL,
                    executed_at INTEGER NOT NULL,
                    success BOOLEAN DEFAULT TRUE,
                    error_message TEXT,
                    FOREIGN KEY (trigger_id) REFERENCES memory_triggers(trigger_id)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trigger_log_trigger
                ON trigger_log(trigger_id, executed_at DESC)
            """)

            conn.commit()

    def create_trigger(
        self,
        name: str,
        condition_type: str,
        condition_value: str,
        action_type: ActionType,
        action_config: str,
        enabled: bool = True
    ) -> Trigger:
        """
        Create new trigger rule.

        Args:
            name: Human-readable name
            condition_type: Type of condition
            condition_value: JSON config for condition
            action_type: Type of action
            action_config: JSON config for action
            enabled: Start enabled?

        Returns:
            Created trigger
        """
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO memory_triggers
                (name, condition_type, condition_value, action_type, action_config, enabled, created_at, trigger_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (name, condition_type, condition_value, action_type, action_config, enabled, now))

            trigger_id = cursor.lastrowid
            conn.commit()

            return self.get_trigger(trigger_id)

    def get_trigger(self, trigger_id: int) -> Optional[Trigger]:
        """Get trigger by ID."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT trigger_id, name, condition_type, condition_value,
                       action_type, action_config, enabled, created_at,
                       last_triggered, trigger_count
                FROM memory_triggers
                WHERE trigger_id = ?
            """, (trigger_id,))

            row = cursor.fetchone()

            if row is None:
                return None

            return Trigger(
                trigger_id=row[0],
                name=row[1],
                condition_type=row[2],
                condition_value=row[3],
                action_type=row[4],
                action_config=row[5],
                enabled=bool(row[6]),
                created_at=datetime.fromtimestamp(row[7]),
                last_triggered=datetime.fromtimestamp(row[8]) if row[8] else None,
                trigger_count=row[9]
            )

    def get_all_triggers(self, enabled_only: bool = True) -> List[Trigger]:
        """Get all triggers."""
        with get_connection(self.db_path) as conn:
            if enabled_only:
                query = "SELECT * FROM memory_triggers WHERE enabled = TRUE"
            else:
                query = "SELECT * FROM memory_triggers"

            cursor = conn.execute(query)

            triggers = []
            for row in cursor.fetchall():
                triggers.append(Trigger(
                    trigger_id=row[0],
                    name=row[1],
                    condition_type=row[2],
                    condition_value=row[3],
                    action_type=row[4],
                    action_config=row[5],
                    enabled=bool(row[6]),
                    created_at=datetime.fromtimestamp(row[7]),
                    last_triggered=datetime.fromtimestamp(row[8]) if row[8] else None,
                    trigger_count=row[9]
                ))

            return triggers

    def check_memory(self, memory_id: str, content: str, importance: float = 0.5) -> List[int]:
        """
        Check if memory matches any triggers and execute actions.

        Args:
            memory_id: Memory identifier
            content: Memory content
            importance: Memory importance score

        Returns:
            List of trigger IDs that fired
        """
        triggers = self.get_all_triggers(enabled_only=True)
        fired_triggers = []

        for trigger in triggers:
            # Check condition
            if self._check_condition(trigger, content, importance):
                # Execute action
                success, error_msg = self._execute_action(trigger, memory_id, content)

                # Log execution
                self._log_trigger(trigger.trigger_id, memory_id, success, error_msg)

                # Update trigger stats
                self._update_trigger_stats(trigger.trigger_id)

                fired_triggers.append(trigger.trigger_id)

        return fired_triggers

    def enable_trigger(self, trigger_id: int, enabled: bool = True):
        """Enable/disable trigger."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE memory_triggers
                SET enabled = ?
                WHERE trigger_id = ?
            """, (enabled, trigger_id))

            conn.commit()

    def delete_trigger(self, trigger_id: int):
        """Delete trigger (keeps logs)."""
        with get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM memory_triggers WHERE trigger_id = ?", (trigger_id,))
            conn.commit()

    def get_trigger_log(self, trigger_id: int, limit: int = 100) -> List[TriggerExecution]:
        """Get execution log for trigger."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, trigger_id, memory_id, executed_at, success, error_message
                FROM trigger_log
                WHERE trigger_id = ?
                ORDER BY executed_at DESC
                LIMIT ?
            """, (trigger_id, limit))

            log = []
            for row in cursor.fetchall():
                log.append(TriggerExecution(
                    id=row[0],
                    trigger_id=row[1],
                    memory_id=row[2],
                    executed_at=datetime.fromtimestamp(row[3]),
                    success=bool(row[4]),
                    error_message=row[5]
                ))

            return log

    # === Private helper methods ===

    def _check_condition(self, trigger: Trigger, content: str, importance: float) -> bool:
        """Check if memory matches trigger condition."""
        try:
            config = json.loads(trigger.condition_value)

            if trigger.condition_type == "keyword_match":
                keywords = config.get("keywords", [])
                content_lower = content.lower()
                return any(kw.lower() in content_lower for kw in keywords)

            elif trigger.condition_type == "pattern_match":
                import re
                pattern = config.get("pattern", "")
                return bool(re.search(pattern, content, re.IGNORECASE))

            elif trigger.condition_type == "importance_threshold":
                threshold = config.get("threshold", 0.5)
                return importance >= threshold

            else:
                # Unknown condition type
                return False

        except Exception:
            return False

    def _execute_action(self, trigger: Trigger, memory_id: str, content: str) -> tuple[bool, Optional[str]]:
        """Execute trigger action."""
        try:
            handler = self._action_handlers.get(trigger.action_type)

            if not handler:
                return False, f"Unknown action type: {trigger.action_type}"

            config = json.loads(trigger.action_config)
            handler(memory_id, content, config)

            return True, None

        except Exception as e:
            return False, str(e)

    def _log_trigger(self, trigger_id: int, memory_id: str, success: bool, error_message: Optional[str]):
        """Log trigger execution."""
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trigger_log (trigger_id, memory_id, executed_at, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (trigger_id, memory_id, now, success, error_message))

            conn.commit()

    def _update_trigger_stats(self, trigger_id: int):
        """Update trigger statistics."""
        now = int(datetime.now().timestamp())

        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE memory_triggers
                SET trigger_count = trigger_count + 1, last_triggered = ?
                WHERE trigger_id = ?
            """, (now, trigger_id))

            conn.commit()

    # === Action handlers ===

    def _action_todoist_task(self, memory_id: str, content: str, config: dict):
        """Create Todoist task."""
        # TODO: Implement Todoist integration
        pass

    def _action_pushover(self, memory_id: str, content: str, config: dict):
        """Send Pushover notification."""
        # TODO: Implement Pushover integration
        pass

    def _action_tag_memory(self, memory_id: str, content: str, config: dict):
        """Add tag to memory."""
        # TODO: Implement memory tagging
        pass

    def _action_run_script(self, memory_id: str, content: str, config: dict):
        """Execute Python script."""
        # TODO: Implement script execution (sandboxed)
        pass

    def _action_webhook(self, memory_id: str, content: str, config: dict):
        """POST to webhook URL."""
        # TODO: Implement webhook POST
        pass
