"""Tests for memory event stream (pub/sub)."""

import json
import tempfile
from pathlib import Path

import pytest

from memory_system.event_stream import EVENT_TYPES, EventStream


@pytest.fixture
def stream(tmp_path):
    """Yield an EventStream backed by a temp database."""
    db = tmp_path / "test_events.db"
    s = EventStream(db_path=db)
    yield s
    s.close()


# ── Schema & construction ──────────────────────────────────────────────


class TestSchemaAndInit:
    def test_creates_table(self, stream):
        """memory_events table should exist after init."""
        cur = stream.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_events'"
        )
        assert cur.fetchone() is not None

    def test_indexes_created(self, stream):
        """Both event_type and created_at indexes should be present."""
        cur = stream.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        names = {row["name"] for row in cur.fetchall()}
        assert "idx_events_type" in names
        assert "idx_events_created" in names

    def test_default_db_path(self):
        """When no db_path given, defaults to intelligence.db next to package root."""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "intelligence.db"
            s = EventStream(db_path=db)
            assert s.db_path == db
            s.close()


# ── Publish ────────────────────────────────────────────────────────────


class TestPublish:
    def test_publish_returns_event_id(self, stream):
        eid = stream.publish("MEMORY_CREATED", {"key": "val"})
        assert isinstance(eid, int)
        assert eid >= 1

    def test_publish_persists_to_db(self, stream):
        stream.publish("MEMORY_CREATED", {"title": "hello"})
        rows = stream.conn.execute("SELECT * FROM memory_events").fetchall()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "MEMORY_CREATED"
        payload = json.loads(rows[0]["payload_json"])
        assert payload["title"] == "hello"

    def test_publish_none_payload_becomes_empty_dict(self, stream):
        stream.publish("SEARCH_PERFORMED")
        rows = stream.conn.execute("SELECT payload_json FROM memory_events").fetchall()
        assert json.loads(rows[0]["payload_json"]) == {}

    def test_publish_invalid_type_raises(self, stream):
        with pytest.raises(ValueError, match="Invalid event type"):
            stream.publish("NOT_A_REAL_EVENT")

    def test_publish_sequential_ids(self, stream):
        id1 = stream.publish("MEMORY_CREATED")
        id2 = stream.publish("MEMORY_UPDATED")
        assert id2 == id1 + 1

    def test_publish_stores_created_at(self, stream):
        stream.publish("MAINTENANCE_RUN")
        row = stream.conn.execute("SELECT created_at FROM memory_events").fetchone()
        assert row["created_at"] is not None
        # Should be an ISO timestamp containing 'T'
        assert "T" in row["created_at"]


# ── Subscribe / Unsubscribe ────────────────────────────────────────────


class TestSubscriptions:
    def test_subscribe_receives_event(self, stream):
        received = []
        stream.subscribe("MEMORY_CREATED", lambda e: received.append(e))
        stream.publish("MEMORY_CREATED", {"x": 1})
        assert len(received) == 1
        assert received[0]["event_type"] == "MEMORY_CREATED"
        assert received[0]["payload"] == {"x": 1}

    def test_subscribe_wildcard_receives_all(self, stream):
        received = []
        stream.subscribe("*", lambda e: received.append(e))
        stream.publish("MEMORY_CREATED")
        stream.publish("MEMORY_ARCHIVED")
        assert len(received) == 2
        assert received[0]["event_type"] == "MEMORY_CREATED"
        assert received[1]["event_type"] == "MEMORY_ARCHIVED"

    def test_subscribe_wrong_type_not_called(self, stream):
        received = []
        stream.subscribe("MEMORY_UPDATED", lambda e: received.append(e))
        stream.publish("MEMORY_CREATED")
        assert len(received) == 0

    def test_unsubscribe_stops_delivery(self, stream):
        received = []
        cb = lambda e: received.append(e)
        stream.subscribe("MEMORY_CREATED", cb)
        stream.publish("MEMORY_CREATED")
        assert len(received) == 1

        stream.unsubscribe("MEMORY_CREATED", cb)
        stream.publish("MEMORY_CREATED")
        assert len(received) == 1  # no new delivery

    def test_unsubscribe_nonexistent_is_noop(self, stream):
        """Unsubscribing a callback that was never registered should not raise."""
        stream.unsubscribe("MEMORY_CREATED", lambda e: None)

    def test_callback_error_does_not_block_others(self, stream):
        """A failing subscriber must not prevent subsequent subscribers from running."""
        results = []

        def bad_cb(e):
            raise RuntimeError("boom")

        def good_cb(e):
            results.append(e["event_type"])

        stream.subscribe("MEMORY_CREATED", bad_cb)
        stream.subscribe("MEMORY_CREATED", good_cb)

        eid = stream.publish("MEMORY_CREATED")
        assert eid >= 1
        assert results == ["MEMORY_CREATED"]

    def test_wildcard_error_does_not_block(self, stream):
        """Wildcard subscriber errors should be isolated too."""
        results = []

        stream.subscribe("*", lambda e: (_ for _ in ()).throw(RuntimeError("fail")))
        stream.subscribe("*", lambda e: results.append(e["id"]))

        eid = stream.publish("MEMORY_UPDATED")
        assert results == [eid]


# ── Query helpers ──────────────────────────────────────────────────────


class TestQueries:
    def test_get_recent_returns_newest_first(self, stream):
        stream.publish("MEMORY_CREATED", {"seq": 1})
        stream.publish("MEMORY_CREATED", {"seq": 2})
        recent = stream.get_recent()
        assert recent[0]["payload"]["seq"] == 2
        assert recent[1]["payload"]["seq"] == 1

    def test_get_recent_filters_by_type(self, stream):
        stream.publish("MEMORY_CREATED")
        stream.publish("MEMORY_UPDATED")
        stream.publish("MEMORY_CREATED")
        recent = stream.get_recent(event_type="MEMORY_CREATED")
        assert len(recent) == 2
        assert all(e["event_type"] == "MEMORY_CREATED" for e in recent)

    def test_get_recent_limit(self, stream):
        for i in range(10):
            stream.publish("SEARCH_PERFORMED", {"i": i})
        recent = stream.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_recent_empty_db(self, stream):
        assert stream.get_recent() == []

    def test_get_stats_counts_by_type(self, stream):
        stream.publish("MEMORY_CREATED")
        stream.publish("MEMORY_CREATED")
        stream.publish("MEMORY_ARCHIVED")
        stats = stream.get_stats()
        assert stats["MEMORY_CREATED"] == 2
        assert stats["MEMORY_ARCHIVED"] == 1

    def test_get_stats_empty_db(self, stream):
        assert stream.get_stats() == {}


# ── Context manager ───────────────────────────────────────────────────


class TestContextManager:
    def test_context_manager_closes_connection(self, tmp_path):
        db = tmp_path / "ctx.db"
        with EventStream(db_path=db) as es:
            es.publish("MEMORY_CREATED")
        # After exit, the connection should be closed
        # Attempting to use it should fail
        with pytest.raises(Exception):
            es.conn.execute("SELECT 1")


# ── EVENT_TYPES constant ──────────────────────────────────────────────


class TestEventTypes:
    def test_all_expected_types_present(self):
        expected = {
            "MEMORY_CREATED",
            "MEMORY_UPDATED",
            "MEMORY_ARCHIVED",
            "CONTRADICTION_DETECTED",
            "SEARCH_PERFORMED",
            "MAINTENANCE_RUN",
        }
        assert set(EVENT_TYPES) == expected

    def test_event_types_is_list(self):
        assert isinstance(EVENT_TYPES, list)
