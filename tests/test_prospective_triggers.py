"""
Tests for prospective_triggers — event/topic/time-based memory triggers
extracted from conversation intent.

Based on Einstein & McDaniel (1990) prospective memory research.
"""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from memory_system.prospective_triggers import (
    ProspectiveTrigger,
    ProspectiveTriggerManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return a temporary database path."""
    return str(tmp_path / "test_triggers.db")


@pytest.fixture
def manager(db_path):
    """Return a fresh ProspectiveTriggerManager with an empty database."""
    return ProspectiveTriggerManager(db_path)


# ---------------------------------------------------------------------------
# ProspectiveTrigger dataclass
# ---------------------------------------------------------------------------

class TestProspectiveTriggerDataclass:
    """Basic sanity checks on the dataclass."""

    def test_create_trigger(self):
        t = ProspectiveTrigger(
            trigger_id=1,
            memory_id="mem-001",
            trigger_type="topic",
            condition={"keywords": ["deploy"]},
            status="pending",
            created_at="2026-02-19T10:00:00+00:00",
        )
        assert t.trigger_id == 1
        assert t.memory_id == "mem-001"
        assert t.trigger_type == "topic"
        assert t.status == "pending"
        assert t.fired_at is None

    def test_fired_at_default_none(self):
        t = ProspectiveTrigger(
            trigger_id=2,
            memory_id="mem-002",
            trigger_type="time",
            condition={"after_date": "2026-03-01"},
            status="pending",
            created_at="2026-02-19T10:00:00+00:00",
        )
        assert t.fired_at is None

    def test_trigger_with_fired_at(self):
        t = ProspectiveTrigger(
            trigger_id=3,
            memory_id="mem-003",
            trigger_type="event",
            condition={"project": "website"},
            status="fired",
            created_at="2026-02-19T10:00:00+00:00",
            fired_at="2026-02-19T12:00:00+00:00",
        )
        assert t.fired_at == "2026-02-19T12:00:00+00:00"
        assert t.status == "fired"


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    """Verify the manager creates the database and schema correctly."""

    def test_creates_database_file(self, db_path):
        ProspectiveTriggerManager(db_path)
        assert os.path.exists(db_path)

    def test_creates_triggers_table(self, db_path):
        ProspectiveTriggerManager(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prospective_triggers'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_creates_indexes(self, db_path):
        ProspectiveTriggerManager(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        index_names = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "idx_triggers_status" in index_names
        assert "idx_triggers_memory" in index_names

    def test_idempotent_init(self, db_path):
        """Creating manager twice on same DB should not error."""
        ProspectiveTriggerManager(db_path)
        ProspectiveTriggerManager(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT count(*) FROM prospective_triggers")
        assert cursor.fetchone()[0] == 0
        conn.close()


# ---------------------------------------------------------------------------
# classify_trigger_type
# ---------------------------------------------------------------------------

class TestClassifyTriggerType:
    """Test trigger classification from extracted text."""

    def test_time_based_with_date(self, manager):
        ttype, condition = manager.classify_trigger_type("after March 1st check the deployment")
        assert ttype == "time"
        assert "after_date" in condition

    def test_time_based_with_next_week(self, manager):
        ttype, condition = manager.classify_trigger_type("next week review the PR")
        assert ttype == "time"
        assert "after_date" in condition

    def test_time_based_with_tomorrow(self, manager):
        ttype, condition = manager.classify_trigger_type("tomorrow send the report")
        assert ttype == "time"
        assert "after_date" in condition

    def test_event_based_with_project(self, manager):
        ttype, condition = manager.classify_trigger_type("working on project website-redesign")
        assert ttype == "event"
        assert "keywords" in condition

    def test_topic_based_default(self, manager):
        ttype, condition = manager.classify_trigger_type("update the API documentation")
        assert ttype == "topic"
        assert "keywords" in condition

    def test_topic_keywords_extracted(self, manager):
        ttype, condition = manager.classify_trigger_type("deploy the production server")
        assert ttype == "topic"
        assert len(condition["keywords"]) > 0
        # Should contain meaningful words, not stopwords
        for kw in condition["keywords"]:
            assert kw not in ("the", "a", "to", "is", "and", "or")


# ---------------------------------------------------------------------------
# extract_triggers
# ---------------------------------------------------------------------------

class TestExtractTriggers:
    """Test trigger extraction from natural language text."""

    def test_extract_remember_to(self, manager):
        text = "remember to update the changelog before release"
        triggers = manager.extract_triggers(text, "mem-100")
        assert len(triggers) >= 1
        assert any("changelog" in json.dumps(t.condition).lower() for t in triggers)

    def test_extract_next_time(self, manager):
        text = "next time we work on the API, check the rate limits"
        triggers = manager.extract_triggers(text, "mem-101")
        assert len(triggers) >= 1

    def test_extract_dont_forget(self, manager):
        text = "don't forget to run the migration scripts"
        triggers = manager.extract_triggers(text, "mem-102")
        assert len(triggers) >= 1

    def test_extract_when_we_get_to(self, manager):
        text = "when we get to deployment, double check the env vars"
        triggers = manager.extract_triggers(text, "mem-103")
        assert len(triggers) >= 1

    def test_extract_todo(self, manager):
        text = "TODO: add error handling for the webhook endpoint"
        triggers = manager.extract_triggers(text, "mem-104")
        assert len(triggers) >= 1

    def test_extract_note_for(self, manager):
        text = "note for next session: pick up where we left off on search"
        triggers = manager.extract_triggers(text, "mem-105")
        assert len(triggers) >= 1

    def test_no_triggers_in_plain_text(self, manager):
        text = "The weather is nice today."
        triggers = manager.extract_triggers(text, "mem-106")
        assert len(triggers) == 0

    def test_multiple_triggers_in_one_text(self, manager):
        text = (
            "remember to update the docs. "
            "Also, don't forget to check the CI pipeline."
        )
        triggers = manager.extract_triggers(text, "mem-107")
        assert len(triggers) >= 2

    def test_triggers_saved_to_db(self, manager):
        text = "remember to fix the login bug"
        manager.extract_triggers(text, "mem-108")
        pending = manager.get_pending_triggers()
        assert len(pending) >= 1
        assert any(t.memory_id == "mem-108" for t in pending)

    def test_trigger_status_is_pending(self, manager):
        text = "TODO: refactor the database layer"
        triggers = manager.extract_triggers(text, "mem-109")
        for t in triggers:
            assert t.status == "pending"

    def test_trigger_has_created_at(self, manager):
        text = "remember to test edge cases"
        triggers = manager.extract_triggers(text, "mem-110")
        for t in triggers:
            assert t.created_at is not None
            # Should be parseable as ISO datetime
            datetime.fromisoformat(t.created_at)


# ---------------------------------------------------------------------------
# check_triggers
# ---------------------------------------------------------------------------

class TestCheckTriggers:
    """Test trigger matching against session context."""

    def test_topic_match_by_keyword(self, manager):
        text = "remember to check the deployment pipeline"
        manager.extract_triggers(text, "mem-200")
        matched = manager.check_triggers({"keywords": ["deployment", "pipeline"]})
        assert len(matched) >= 1

    def test_no_match_for_unrelated_context(self, manager):
        text = "remember to check the deployment pipeline"
        manager.extract_triggers(text, "mem-201")
        matched = manager.check_triggers({"keywords": ["cooking", "recipes"]})
        assert len(matched) == 0

    def test_time_trigger_fires_after_date(self, manager):
        # Manually insert a time-based trigger for yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-202", "time", json.dumps({"after_date": yesterday}), "pending",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        matched = manager.check_triggers({"current_date": today})
        assert len(matched) >= 1
        assert any(t.memory_id == "mem-202" for t in matched)

    def test_time_trigger_not_before_date(self, manager):
        # Insert a time-based trigger for next month
        future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-203", "time", json.dumps({"after_date": future}), "pending",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        matched = manager.check_triggers({"current_date": today})
        assert not any(t.memory_id == "mem-203" for t in matched)

    def test_already_fired_triggers_not_returned(self, manager):
        text = "remember to check the test coverage"
        triggers = manager.extract_triggers(text, "mem-204")
        if triggers:
            manager.fire_trigger(triggers[0].trigger_id)
        matched = manager.check_triggers({"keywords": ["test", "coverage"]})
        assert not any(t.memory_id == "mem-204" for t in matched)

    def test_event_match_by_project(self, manager):
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-205", "event", json.dumps({"project": "total-rekall"}), "pending",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        matched = manager.check_triggers({"project": "total-rekall"})
        assert len(matched) >= 1
        assert any(t.memory_id == "mem-205" for t in matched)

    def test_event_no_match_wrong_project(self, manager):
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-206", "event", json.dumps({"project": "total-rekall"}), "pending",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        matched = manager.check_triggers({"project": "unrelated-project"})
        assert not any(t.memory_id == "mem-206" for t in matched)


# ---------------------------------------------------------------------------
# fire_trigger / dismiss_trigger
# ---------------------------------------------------------------------------

class TestFireAndDismiss:
    """Test trigger state transitions."""

    def test_fire_trigger(self, manager):
        text = "remember to review the PR"
        triggers = manager.extract_triggers(text, "mem-300")
        assert len(triggers) >= 1
        tid = triggers[0].trigger_id
        manager.fire_trigger(tid)
        pending = manager.get_pending_triggers()
        assert not any(t.trigger_id == tid for t in pending)

    def test_fire_sets_fired_at(self, manager):
        text = "remember to update the docs"
        triggers = manager.extract_triggers(text, "mem-301")
        tid = triggers[0].trigger_id
        manager.fire_trigger(tid)
        # Read back from DB
        conn = sqlite3.connect(manager._db_path)
        row = conn.execute(
            "SELECT status, fired_at FROM prospective_triggers WHERE trigger_id = ?",
            (tid,),
        ).fetchone()
        conn.close()
        assert row[0] == "fired"
        assert row[1] is not None

    def test_dismiss_trigger(self, manager):
        text = "remember to clean up temp files"
        triggers = manager.extract_triggers(text, "mem-302")
        tid = triggers[0].trigger_id
        manager.dismiss_trigger(tid)
        pending = manager.get_pending_triggers()
        assert not any(t.trigger_id == tid for t in pending)

    def test_dismiss_sets_status(self, manager):
        text = "remember to check the logs"
        triggers = manager.extract_triggers(text, "mem-303")
        tid = triggers[0].trigger_id
        manager.dismiss_trigger(tid)
        conn = sqlite3.connect(manager._db_path)
        row = conn.execute(
            "SELECT status FROM prospective_triggers WHERE trigger_id = ?",
            (tid,),
        ).fetchone()
        conn.close()
        assert row[0] == "dismissed"


# ---------------------------------------------------------------------------
# get_pending_triggers
# ---------------------------------------------------------------------------

class TestGetPendingTriggers:
    """Test retrieval of pending triggers."""

    def test_empty_db_returns_empty(self, manager):
        assert manager.get_pending_triggers() == []

    def test_returns_only_pending(self, manager):
        text = "remember to fix bug A. Also remember to fix bug B."
        triggers = manager.extract_triggers(text, "mem-400")
        if len(triggers) >= 2:
            manager.fire_trigger(triggers[0].trigger_id)
        pending = manager.get_pending_triggers()
        for t in pending:
            assert t.status == "pending"

    def test_respects_limit(self, manager):
        for i in range(10):
            manager.extract_triggers(f"remember to do task {i}", f"mem-41{i}")
        limited = manager.get_pending_triggers(limit=3)
        assert len(limited) <= 3


# ---------------------------------------------------------------------------
# expire_old_triggers
# ---------------------------------------------------------------------------

class TestExpireOldTriggers:
    """Test automatic expiration of old triggers."""

    def test_expire_old_triggers(self, manager):
        # Insert a trigger created 100 days ago
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-500", "topic", json.dumps({"keywords": ["old"]}), "pending", old_date),
        )
        conn.commit()
        conn.close()

        count = manager.expire_old_triggers(max_age_days=90)
        assert count >= 1

        pending = manager.get_pending_triggers()
        assert not any(t.memory_id == "mem-500" for t in pending)

    def test_does_not_expire_recent(self, manager):
        text = "remember to finish the feature"
        manager.extract_triggers(text, "mem-501")
        count = manager.expire_old_triggers(max_age_days=90)
        assert count == 0
        pending = manager.get_pending_triggers()
        assert len(pending) >= 1

    def test_only_expires_pending(self, manager):
        # Insert old trigger that is already fired — should not expire
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        conn = sqlite3.connect(manager._db_path)
        conn.execute(
            "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mem-502", "topic", json.dumps({"keywords": ["old"]}), "fired", old_date),
        )
        conn.commit()
        conn.close()

        count = manager.expire_old_triggers(max_age_days=90)
        assert count == 0

    def test_returns_expired_count(self, manager):
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        conn = sqlite3.connect(manager._db_path)
        for i in range(5):
            conn.execute(
                "INSERT INTO prospective_triggers (memory_id, trigger_type, condition, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"mem-exp-{i}", "topic", json.dumps({"keywords": ["stale"]}), "pending", old_date),
            )
        conn.commit()
        conn.close()

        count = manager.expire_old_triggers(max_age_days=90)
        assert count == 5
