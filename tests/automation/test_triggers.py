"""
Tests for Feature 28: Memory Triggers
"""

import pytest
import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from automation.triggers import MemoryTriggers, Trigger


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def triggers(temp_db):
    """Create triggers instance."""
    return MemoryTriggers(db_path=temp_db)


def test_init_creates_tables(triggers, temp_db):
    """Test initialization creates tables."""
    from db_pool import get_connection

    with get_connection(temp_db) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('memory_triggers', 'trigger_log')
        """)
        tables = {row[0] for row in cursor.fetchall()}

    assert "memory_triggers" in tables
    assert "trigger_log" in tables


def test_create_trigger(triggers):
    """Test creating a trigger."""
    trigger = triggers.create_trigger(
        name="Test Trigger",
        condition_type="keyword_match",
        condition_value=json.dumps({"keywords": ["deadline"]}),
        action_type="todoist_task",
        action_config=json.dumps({"project": "Work"}),
        enabled=True
    )

    assert trigger.trigger_id > 0
    assert trigger.name == "Test Trigger"
    assert trigger.enabled is True
    assert trigger.trigger_count == 0


def test_get_trigger(triggers):
    """Test retrieving trigger."""
    created = triggers.create_trigger(
        "Get Test",
        "keyword_match",
        json.dumps({"keywords": ["test"]}),
        "pushover_notification",
        json.dumps({})
    )

    retrieved = triggers.get_trigger(created.trigger_id)

    assert retrieved is not None
    assert retrieved.trigger_id == created.trigger_id
    assert retrieved.name == "Get Test"


def test_get_trigger_nonexistent(triggers):
    """Test getting nonexistent trigger returns None."""
    trigger = triggers.get_trigger(999)
    assert trigger is None


def test_get_all_triggers_enabled_only(triggers):
    """Test getting only enabled triggers."""
    triggers.create_trigger("Enabled", "keyword_match", "{}", "tag_memory", "{}", enabled=True)
    triggers.create_trigger("Disabled", "keyword_match", "{}", "tag_memory", "{}", enabled=False)

    enabled_triggers = triggers.get_all_triggers(enabled_only=True)

    assert len(enabled_triggers) == 1
    assert enabled_triggers[0].name == "Enabled"


def test_get_all_triggers_include_disabled(triggers):
    """Test getting all triggers including disabled."""
    triggers.create_trigger("Enabled", "keyword_match", "{}", "tag_memory", "{}", enabled=True)
    triggers.create_trigger("Disabled", "keyword_match", "{}", "tag_memory", "{}", enabled=False)

    all_triggers = triggers.get_all_triggers(enabled_only=False)

    assert len(all_triggers) == 2


def test_enable_disable_trigger(triggers):
    """Test enabling/disabling trigger."""
    trigger = triggers.create_trigger("Toggle", "keyword_match", "{}", "tag_memory", "{}", enabled=True)

    # Disable
    triggers.enable_trigger(trigger.trigger_id, False)
    disabled = triggers.get_trigger(trigger.trigger_id)
    assert disabled.enabled is False

    # Re-enable
    triggers.enable_trigger(trigger.trigger_id, True)
    enabled = triggers.get_trigger(trigger.trigger_id)
    assert enabled.enabled is True


def test_delete_trigger(triggers):
    """Test deleting trigger."""
    trigger = triggers.create_trigger("Delete Me", "keyword_match", "{}", "tag_memory", "{}")

    triggers.delete_trigger(trigger.trigger_id)

    deleted = triggers.get_trigger(trigger.trigger_id)
    assert deleted is None


def test_check_condition_keyword_match_true(triggers):
    """Test keyword match condition (positive)."""
    trigger = Trigger(
        trigger_id=1,
        name="Test",
        condition_type="keyword_match",
        condition_value=json.dumps({"keywords": ["deadline", "urgent"]}),
        action_type="todoist_task",
        action_config="{}",
        enabled=True,
        created_at=None,
        last_triggered=None,
        trigger_count=0
    )

    matches = triggers._check_condition(trigger, "Client mentioned deadline tomorrow", 0.5)
    assert matches is True


def test_check_condition_keyword_match_false(triggers):
    """Test keyword match condition (negative)."""
    trigger = Trigger(
        trigger_id=1,
        name="Test",
        condition_type="keyword_match",
        condition_value=json.dumps({"keywords": ["deadline", "urgent"]}),
        action_type="todoist_task",
        action_config="{}",
        enabled=True,
        created_at=None,
        last_triggered=None,
        trigger_count=0
    )

    matches = triggers._check_condition(trigger, "Normal conversation", 0.5)
    assert matches is False


def test_check_condition_pattern_match(triggers):
    """Test regex pattern match condition."""
    trigger = Trigger(
        trigger_id=1,
        name="Test",
        condition_type="pattern_match",
        condition_value=json.dumps({"pattern": r"\d{4}-\d{2}-\d{2}"}),  # Date pattern
        action_type="tag_memory",
        action_config="{}",
        enabled=True,
        created_at=None,
        last_triggered=None,
        trigger_count=0
    )

    matches = triggers._check_condition(trigger, "Meeting on 2026-12-25", 0.5)
    assert matches is True


def test_check_condition_importance_threshold(triggers):
    """Test importance threshold condition."""
    trigger = Trigger(
        trigger_id=1,
        name="Test",
        condition_type="importance_threshold",
        condition_value=json.dumps({"threshold": 0.8}),
        action_type="pushover_notification",
        action_config="{}",
        enabled=True,
        created_at=None,
        last_triggered=None,
        trigger_count=0
    )

    matches_high = triggers._check_condition(trigger, "Important memory", 0.9)
    assert matches_high is True

    matches_low = triggers._check_condition(trigger, "Less important", 0.5)
    assert matches_low is False


def test_check_memory(triggers):
    """Test checking memory against triggers."""
    # Create trigger
    triggers.create_trigger(
        "Deadline Trigger",
        "keyword_match",
        json.dumps({"keywords": ["deadline"]}),
        "todoist_task",
        json.dumps({})
    )

    # Check memory that matches
    fired = triggers.check_memory("mem_001", "Client mentioned deadline", 0.5)

    assert len(fired) > 0


def test_check_memory_no_match(triggers):
    """Test checking memory that doesn't match any triggers."""
    triggers.create_trigger(
        "Deadline Trigger",
        "keyword_match",
        json.dumps({"keywords": ["deadline"]}),
        "todoist_task",
        json.dumps({})
    )

    fired = triggers.check_memory("mem_001", "Normal conversation", 0.5)

    assert len(fired) == 0


def test_trigger_statistics_update(triggers):
    """Test that trigger execution updates statistics."""
    trigger = triggers.create_trigger(
        "Stats Test",
        "keyword_match",
        json.dumps({"keywords": ["test"]}),
        "tag_memory",
        json.dumps({})
    )

    # Trigger it
    triggers.check_memory("mem_001", "This is a test", 0.5)

    # Check stats updated
    updated = triggers.get_trigger(trigger.trigger_id)
    assert updated.trigger_count == 1
    assert updated.last_triggered is not None


def test_get_trigger_log(triggers):
    """Test retrieving trigger execution log."""
    trigger = triggers.create_trigger(
        "Log Test",
        "keyword_match",
        json.dumps({"keywords": ["test"]}),
        "tag_memory",
        json.dumps({})
    )

    # Execute trigger multiple times
    triggers.check_memory("mem_001", "test 1", 0.5)
    triggers.check_memory("mem_002", "test 2", 0.5)

    log = triggers.get_trigger_log(trigger.trigger_id)

    assert len(log) == 2
    assert log[0].memory_id in ["mem_001", "mem_002"]
    assert log[0].success is True
