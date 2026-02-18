"""
Tests for Feature 29: Smart Alerts
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from memory_system.automation.alerts import SmartAlerts, Alert, AlertDigest


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def alerts(temp_db):
    """Create alerts instance."""
    return SmartAlerts(db_path=temp_db)


def test_init_creates_tables(alerts, temp_db):
    """Test initialization creates tables."""
    from memory_system.db_pool import get_connection

    with get_connection(temp_db) as conn:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('smart_alerts', 'alert_log')
        """)
        tables = {row[0] for row in cursor.fetchall()}

    assert "smart_alerts" in tables
    assert "alert_log" in tables


def test_create_alert(alerts):
    """Test creating an alert."""
    alert = alerts.create_alert(
        alert_type="contradiction",
        severity="critical",
        title="Test Alert",
        message="Test message",
        memory_ids=["mem_001", "mem_002"]
    )

    assert alert.alert_id > 0
    assert alert.alert_type == "contradiction"
    assert alert.severity == "critical"
    assert alert.title == "Test Alert"
    assert alert.action_taken is False
    assert alert.dismissed_at is None


def test_create_alert_with_metadata(alerts):
    """Test creating alert with metadata."""
    metadata = {"confidence": 0.95, "source": "pattern_detector"}

    alert = alerts.create_alert(
        alert_type="pattern_detected",
        severity="high",
        title="Pattern Detected",
        message="Recurring pattern identified",
        metadata=metadata
    )

    assert alert.alert_id > 0
    metadata_dict = json.loads(alert.metadata)
    assert metadata_dict["confidence"] == 0.95
    assert metadata_dict["source"] == "pattern_detector"


def test_get_alert(alerts):
    """Test retrieving alert."""
    created = alerts.create_alert(
        "expiring_memory",
        "medium",
        "Review Due",
        "Memory needs review",
        ["mem_001"]
    )

    retrieved = alerts.get_alert(created.alert_id)

    assert retrieved is not None
    assert retrieved.alert_id == created.alert_id
    assert retrieved.title == "Review Due"


def test_get_alert_nonexistent(alerts):
    """Test getting nonexistent alert returns None."""
    alert = alerts.get_alert(999)
    assert alert is None


def test_get_unread_alerts(alerts):
    """Test getting unread alerts."""
    # Create some alerts
    a1 = alerts.create_alert("contradiction", "critical", "Critical Alert", "Msg", ["m1"])
    a2 = alerts.create_alert("stale_memory", "low", "Stale Memory", "Msg", ["m2"])
    a3 = alerts.create_alert("quality_issue", "medium", "Quality Issue", "Msg", ["m3"])

    unread = alerts.get_unread_alerts()

    assert len(unread) == 3
    # All alerts should be returned
    alert_ids = {a.alert_id for a in unread}
    assert a1.alert_id in alert_ids
    assert a2.alert_id in alert_ids
    assert a3.alert_id in alert_ids


def test_get_unread_alerts_by_severity(alerts):
    """Test filtering unread alerts by severity."""
    alerts.create_alert("contradiction", "critical", "Critical 1", "Msg", ["m1"])
    alerts.create_alert("contradiction", "critical", "Critical 2", "Msg", ["m2"])
    alerts.create_alert("stale_memory", "low", "Low Priority", "Msg", ["m3"])

    critical = alerts.get_unread_alerts(severity="critical")

    assert len(critical) == 2
    assert all(a.severity == "critical" for a in critical)


def test_get_unread_alerts_by_type(alerts):
    """Test filtering unread alerts by type."""
    alerts.create_alert("contradiction", "high", "Contradiction 1", "Msg", ["m1"])
    alerts.create_alert("contradiction", "high", "Contradiction 2", "Msg", ["m2"])
    alerts.create_alert("stale_memory", "low", "Stale", "Msg", ["m3"])

    contradictions = alerts.get_unread_alerts(alert_type="contradiction")

    assert len(contradictions) == 2
    assert all(a.alert_type == "contradiction" for a in contradictions)


def test_dismiss_alert(alerts):
    """Test dismissing an alert."""
    alert = alerts.create_alert("quality_issue", "low", "Low Quality", "Msg", ["m1"])

    alerts.dismiss_alert(alert.alert_id, notes="False positive")

    # Verify it's dismissed
    retrieved = alerts.get_alert(alert.alert_id)
    assert retrieved.dismissed_at is not None

    # Should not appear in unread
    unread = alerts.get_unread_alerts()
    assert len(unread) == 0


def test_mark_action_taken(alerts):
    """Test marking action taken on alert."""
    alert = alerts.create_alert("expiring_memory", "high", "Review Due", "Msg", ["m1"])

    alerts.mark_action_taken(alert.alert_id, notes="Reviewed memory")

    # Verify action_taken is true
    retrieved = alerts.get_alert(alert.alert_id)
    assert retrieved.action_taken is True


def test_get_daily_digest(alerts):
    """Test getting daily digest."""
    # Create alerts with different severities
    alerts.create_alert("contradiction", "critical", "Critical 1", "Msg", ["m1"])
    alerts.create_alert("contradiction", "critical", "Critical 2", "Msg", ["m2"])
    alerts.create_alert("expiring_memory", "high", "High Priority", "Msg", ["m3"])
    alerts.create_alert("stale_memory", "medium", "Medium Priority", "Msg", ["m4"])
    alerts.create_alert("quality_issue", "low", "Low Priority", "Msg", ["m5"])

    digest = alerts.get_daily_digest()

    assert digest.critical_count == 2
    assert digest.high_count == 1
    assert digest.medium_count == 1
    assert digest.low_count == 1
    assert len(digest.alerts) == 5
    # Should be ordered by severity (critical first)
    assert digest.alerts[0].severity == "critical"
    assert digest.alerts[1].severity == "critical"
    assert digest.alerts[2].severity == "high"


def test_get_daily_digest_specific_date(alerts):
    """Test getting digest for specific date."""
    # Create alert today
    alerts.create_alert("contradiction", "high", "Today's Alert", "Msg", ["m1"])

    # Get yesterday's digest (should be empty)
    yesterday = datetime.now() - timedelta(days=1)
    digest = alerts.get_daily_digest(yesterday)

    assert digest.critical_count == 0
    assert digest.high_count == 0
    assert len(digest.alerts) == 0


def test_get_alert_stats(alerts):
    """Test getting alert statistics."""
    # Create various alerts
    alerts.create_alert("contradiction", "critical", "C1", "Msg", ["m1"])
    alerts.create_alert("contradiction", "high", "C2", "Msg", ["m2"])
    alerts.create_alert("stale_memory", "medium", "S1", "Msg", ["m3"])
    alerts.create_alert("quality_issue", "low", "Q1", "Msg", ["m4"])

    # Dismiss one
    alert = alerts.create_alert("expiring_memory", "high", "E1", "Msg", ["m5"])
    alerts.dismiss_alert(alert.alert_id)

    # Mark action on one
    alert2 = alerts.create_alert("pattern_detected", "high", "P1", "Msg", ["m6"])
    alerts.mark_action_taken(alert2.alert_id)

    stats = alerts.get_alert_stats(days=7)

    assert stats['total_alerts'] == 6
    assert stats['by_type']['contradiction'] == 2
    assert stats['by_type']['stale_memory'] == 1
    assert stats['by_severity']['critical'] == 1
    assert stats['by_severity']['high'] == 3
    assert stats['dismissed_rate'] > 0
    assert stats['action_taken_rate'] > 0


def test_cleanup_old_alerts(alerts):
    """Test cleaning up old dismissed alerts."""
    # Create and dismiss an alert
    alert = alerts.create_alert("quality_issue", "low", "Old Alert", "Msg", ["m1"])
    alerts.dismiss_alert(alert.alert_id)

    # Manually set dismissed_at to 100 days ago
    from memory_system.db_pool import get_connection
    old_timestamp = int((datetime.now() - timedelta(days=100)).timestamp())
    with get_connection(alerts.db_path) as conn:
        conn.execute("UPDATE smart_alerts SET dismissed_at = ? WHERE alert_id = ?",
                    (old_timestamp, alert.alert_id))
        conn.commit()

    # Cleanup (default 90 days)
    alerts.cleanup_old_alerts(days=90)

    # Alert should be gone
    retrieved = alerts.get_alert(alert.alert_id)
    assert retrieved is None


def test_cleanup_keeps_recent_alerts(alerts):
    """Test cleanup preserves recent dismissed alerts."""
    # Create and dismiss alert recently
    alert = alerts.create_alert("quality_issue", "low", "Recent Alert", "Msg", ["m1"])
    alerts.dismiss_alert(alert.alert_id)

    # Cleanup should not remove it
    alerts.cleanup_old_alerts(days=90)

    # Alert should still exist
    retrieved = alerts.get_alert(alert.alert_id)
    assert retrieved is not None


def test_cleanup_keeps_undismissed_alerts(alerts):
    """Test cleanup only removes dismissed alerts."""
    # Create old undismissed alert
    alert = alerts.create_alert("quality_issue", "low", "Old Undismissed", "Msg", ["m1"])

    # Manually set created_at to 100 days ago
    from memory_system.db_pool import get_connection
    old_timestamp = int((datetime.now() - timedelta(days=100)).timestamp())
    with get_connection(alerts.db_path) as conn:
        conn.execute("UPDATE smart_alerts SET created_at = ? WHERE alert_id = ?",
                    (old_timestamp, alert.alert_id))
        conn.commit()

    # Cleanup should not remove undismissed alerts
    alerts.cleanup_old_alerts(days=90)

    # Alert should still exist
    retrieved = alerts.get_alert(alert.alert_id)
    assert retrieved is not None


# -----------------------------------------------------------------------
# Notification center: get_all_alerts, dismiss_all, new types, to_dict
# -----------------------------------------------------------------------


def test_get_all_alerts_with_pagination(alerts):
    """Test get_all_alerts returns both read and unread, with pagination."""
    for i in range(5):
        a = alerts.create_alert("consolidation_summary", "medium", f"Alert {i}", "Msg")
        if i < 2:
            alerts.dismiss_alert(a.alert_id)

    all_alerts, total = alerts.get_all_alerts(limit=3, offset=0)
    assert total == 5
    assert len(all_alerts) == 3

    # Second page
    all_alerts_p2, total_p2 = alerts.get_all_alerts(limit=3, offset=3)
    assert total_p2 == 5
    assert len(all_alerts_p2) == 2


def test_get_all_alerts_filter_by_type(alerts):
    """Test get_all_alerts type filter."""
    alerts.create_alert("consolidation_summary", "medium", "Consolidation", "Msg")
    alerts.create_alert("memory_promoted", "high", "Promotion", "Msg")
    alerts.create_alert("consolidation_summary", "medium", "Consolidation 2", "Msg")

    filtered, total = alerts.get_all_alerts(alert_type="consolidation_summary")
    assert total == 2
    assert len(filtered) == 2
    assert all(a.alert_type == "consolidation_summary" for a in filtered)


def test_get_all_alerts_returns_newest_first(alerts):
    """Test get_all_alerts returns in reverse chronological order."""
    import time
    a1 = alerts.create_alert("consolidation_summary", "medium", "First", "Msg")
    time.sleep(1.1)  # created_at uses int(time.time()) — need >1s gap
    a2 = alerts.create_alert("consolidation_summary", "medium", "Second", "Msg")

    all_alerts, _ = alerts.get_all_alerts()
    assert all_alerts[0].title == "Second"
    assert all_alerts[1].title == "First"


def test_dismiss_all(alerts):
    """Test dismiss_all marks all unread as dismissed."""
    alerts.create_alert("consolidation_summary", "medium", "A1", "Msg")
    alerts.create_alert("reinforcement_detected", "medium", "A2", "Msg")
    alerts.create_alert("memory_promoted", "high", "A3", "Msg")

    assert len(alerts.get_unread_alerts()) == 3

    alerts.dismiss_all()

    assert len(alerts.get_unread_alerts()) == 0

    # All should still exist in get_all_alerts
    all_alerts, total = alerts.get_all_alerts()
    assert total == 3
    assert all(a.dismissed_at is not None for a in all_alerts)


def test_new_alert_types(alerts):
    """Test new consolidation-related alert types work correctly."""
    a1 = alerts.create_alert(
        "consolidation_summary", "medium", "Session consolidated",
        "5 memories saved", metadata={"memories_saved": 5, "session_id": "abc123"}
    )
    a2 = alerts.create_alert(
        "memory_promoted", "high", "3 memories promoted",
        "Reached threshold"
    )
    a3 = alerts.create_alert(
        "reinforcement_detected", "medium", "2 reinforcements",
        "Patterns found"
    )

    assert a1.alert_type == "consolidation_summary"
    assert a2.alert_type == "memory_promoted"
    assert a3.alert_type == "reinforcement_detected"

    meta = json.loads(a1.metadata)
    assert meta["memories_saved"] == 5
    assert meta["session_id"] == "abc123"


def test_alert_to_dict(alerts):
    """Test Alert.to_dict() serialization for API."""
    a = alerts.create_alert(
        "consolidation_summary", "medium", "Test",
        "Message", memory_ids=["m1", "m2"],
        metadata={"key": "value"}
    )
    d = a.to_dict()
    assert d["alert_id"] == a.alert_id
    assert d["alert_type"] == "consolidation_summary"
    assert d["memory_ids"] == ["m1", "m2"]
    assert d["metadata"]["key"] == "value"
    assert d["dismissed_at"] is None
    assert isinstance(d["created_at"], str)


def test_alert_to_dict_handles_empty(alerts):
    """Test to_dict with no memory_ids or metadata."""
    a = alerts.create_alert(
        "stale_memory", "low", "Stale", "Message"
    )
    d = a.to_dict()
    assert d["memory_ids"] == []
    assert d["metadata"] == {}


def test_dismiss_all_idempotent(alerts):
    """Test dismiss_all with no unread alerts doesn't error."""
    alerts.dismiss_all()  # No alerts exist, should not raise
    assert len(alerts.get_unread_alerts()) == 0
