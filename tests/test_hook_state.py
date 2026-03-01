"""
Tests for hook shared state module.

Covers:
- Session ID detection from environment
- State file loading (missing, corrupt, valid)
- Atomic state file saving
- Session state initialization and retrieval
- Session state updates with merge semantics
- Exchange counter increment
- Injection timing logic (interval + last injection gap)
- Injection recording
- Stale session cleanup
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.hook_state import (
    DEFAULT_INJECTION_INTERVAL,
    DEFAULT_STATE_FILE,
    cleanup_stale_sessions,
    get_session_id,
    get_session_state,
    increment_exchange,
    load_state,
    record_injection,
    save_state,
    should_inject,
    update_session_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_file(tmp_path):
    """Provide a temporary state file path."""
    return tmp_path / "hook-state.json"


# ---------------------------------------------------------------------------
# TestGetSessionId
# ---------------------------------------------------------------------------

class TestGetSessionId:
    def test_from_env_var(self, monkeypatch):
        """Reads session ID from CLAUDE_SESSION_ID env var."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123")
        assert get_session_id() == "abc-123"

    def test_fallback_to_unknown(self, monkeypatch):
        """Falls back to 'unknown' when env var is not set."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        assert get_session_id() == "unknown"

    def test_env_var_empty_string(self, monkeypatch):
        """Empty string env var falls back to 'unknown'."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "")
        assert get_session_id() == "unknown"


# ---------------------------------------------------------------------------
# TestLoadState
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_missing_file_returns_empty(self, state_file):
        """Non-existent file returns empty dict."""
        assert load_state(state_file) == {}

    def test_corrupt_json_returns_empty(self, state_file):
        """Corrupt JSON returns empty dict without raising."""
        state_file.write_text("{invalid json!!!")
        assert load_state(state_file) == {}

    def test_valid_json_loads(self, state_file):
        """Valid JSON is loaded correctly."""
        data = {"session-1": {"exchange_count": 5}}
        state_file.write_text(json.dumps(data))
        assert load_state(state_file) == data

    def test_custom_path(self, tmp_path):
        """Loads from a custom file path."""
        custom = tmp_path / "subdir" / "custom.json"
        custom.parent.mkdir(parents=True)
        custom.write_text(json.dumps({"key": "value"}))
        assert load_state(custom) == {"key": "value"}


# ---------------------------------------------------------------------------
# TestSaveState
# ---------------------------------------------------------------------------

class TestSaveState:
    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "state.json"
        save_state({"test": True}, deep_path)
        assert deep_path.exists()
        assert json.loads(deep_path.read_text()) == {"test": True}

    def test_atomic_write(self, state_file):
        """Uses tmp file then rename (no partial writes visible)."""
        save_state({"data": 1}, state_file)
        # The .tmp file should not remain after successful write
        tmp_file = state_file.with_suffix(".json.tmp")
        assert not tmp_file.exists()
        assert state_file.exists()
        assert json.loads(state_file.read_text()) == {"data": 1}

    def test_overwrites_existing(self, state_file):
        """Overwrites existing state file with new data."""
        save_state({"version": 1}, state_file)
        save_state({"version": 2}, state_file)
        assert json.loads(state_file.read_text()) == {"version": 2}


# ---------------------------------------------------------------------------
# TestGetSessionState
# ---------------------------------------------------------------------------

class TestGetSessionState:
    def test_initializes_defaults(self, state_file, monkeypatch):
        """New session gets default schema values."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "new-session")
        state = get_session_state(session_id="new-session", state_file=state_file)
        assert state["exchange_count"] == 0
        assert state["project"] is None
        assert state["last_injection_ts"] is None
        assert state["last_injection_exchange"] == 0
        assert state["last_injected_ids"] == []
        assert state["active_skills"] == []
        assert state["injection_interval"] == DEFAULT_INJECTION_INTERVAL
        assert "initialized_at" in state

    def test_returns_existing(self, state_file):
        """Returns existing session state without re-initializing."""
        seed = {
            "sess-1": {
                "exchange_count": 42,
                "project": "memeta",
                "last_injection_ts": None,
                "last_injection_exchange": 0,
                "last_injected_ids": [],
                "active_skills": [],
                "injection_interval": 10,
                "initialized_at": "2026-01-01T00:00:00",
            }
        }
        state_file.write_text(json.dumps(seed))
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["exchange_count"] == 42
        assert state["project"] == "memeta"

    def test_auto_detects_session_id(self, state_file, monkeypatch):
        """Uses get_session_id() when no session_id is passed."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "auto-detected")
        state = get_session_state(state_file=state_file)
        # Should have initialized a session with auto-detected ID
        full = load_state(state_file)
        assert "auto-detected" in full


# ---------------------------------------------------------------------------
# TestUpdateSessionState
# ---------------------------------------------------------------------------

class TestUpdateSessionState:
    def test_merges_updates(self, state_file):
        """Updates are merged into existing session state."""
        get_session_state(session_id="sess-1", state_file=state_file)
        updated = update_session_state(
            {"project": "memeta", "exchange_count": 5},
            session_id="sess-1",
            state_file=state_file,
        )
        assert updated["project"] == "memeta"
        assert updated["exchange_count"] == 5

    def test_preserves_unmodified_fields(self, state_file):
        """Fields not in updates dict are preserved."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"project": "memeta"},
            session_id="sess-1",
            state_file=state_file,
        )
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["injection_interval"] == DEFAULT_INJECTION_INTERVAL
        assert state["last_injected_ids"] == []

    def test_creates_session_if_missing(self, state_file):
        """If session doesn't exist, initializes defaults then merges updates."""
        updated = update_session_state(
            {"project": "new-project"},
            session_id="brand-new",
            state_file=state_file,
        )
        assert updated["project"] == "new-project"
        assert updated["exchange_count"] == 0  # default preserved


# ---------------------------------------------------------------------------
# TestIncrementExchange
# ---------------------------------------------------------------------------

class TestIncrementExchange:
    def test_increments_from_zero(self, state_file):
        """First increment goes from 0 to 1."""
        count = increment_exchange(session_id="sess-1", state_file=state_file)
        assert count == 1

    def test_increments_existing(self, state_file):
        """Successive increments accumulate."""
        increment_exchange(session_id="sess-1", state_file=state_file)
        increment_exchange(session_id="sess-1", state_file=state_file)
        count = increment_exchange(session_id="sess-1", state_file=state_file)
        assert count == 3

    def test_returns_new_count(self, state_file):
        """Returns the new count after increment, not the old one."""
        c1 = increment_exchange(session_id="sess-1", state_file=state_file)
        c2 = increment_exchange(session_id="sess-1", state_file=state_file)
        assert c1 == 1
        assert c2 == 2


# ---------------------------------------------------------------------------
# TestShouldInject
# ---------------------------------------------------------------------------

class TestShouldInject:
    def test_false_before_interval(self, state_file):
        """Returns False when exchange_count < injection_interval."""
        get_session_state(session_id="sess-1", state_file=state_file)
        # Set exchange_count to 5 (below default interval of 10)
        update_session_state(
            {"exchange_count": 5},
            session_id="sess-1",
            state_file=state_file,
        )
        assert should_inject(session_id="sess-1", state_file=state_file) is False

    def test_true_at_interval(self, state_file):
        """Returns True when exchange_count is a multiple of injection_interval."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 10, "last_injection_exchange": 0},
            session_id="sess-1",
            state_file=state_file,
        )
        assert should_inject(session_id="sess-1", state_file=state_file) is True

    def test_false_after_recent_injection(self, state_file):
        """Returns False when not enough exchanges since last injection."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 20, "last_injection_exchange": 15},
            session_id="sess-1",
            state_file=state_file,
        )
        assert should_inject(session_id="sess-1", state_file=state_file) is False

    def test_true_when_interval_passed_since_last(self, state_file):
        """Returns True when injection_interval exchanges passed since last injection."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 20, "last_injection_exchange": 10},
            session_id="sess-1",
            state_file=state_file,
        )
        assert should_inject(session_id="sess-1", state_file=state_file) is True

    def test_false_at_zero_exchanges(self, state_file):
        """Returns False at exchange_count 0 (initial state, no modular arithmetic trap)."""
        get_session_state(session_id="sess-1", state_file=state_file)
        # exchange_count defaults to 0, which is a multiple of any interval
        # but should NOT trigger injection
        assert should_inject(session_id="sess-1", state_file=state_file) is False

    def test_false_not_multiple_of_interval(self, state_file):
        """Returns False when exchange_count is not a multiple of interval."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 13, "last_injection_exchange": 0},
            session_id="sess-1",
            state_file=state_file,
        )
        assert should_inject(session_id="sess-1", state_file=state_file) is False


# ---------------------------------------------------------------------------
# TestRecordInjection
# ---------------------------------------------------------------------------

class TestRecordInjection:
    def test_records_timestamp(self, state_file):
        """Sets last_injection_ts to current ISO timestamp."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 10},
            session_id="sess-1",
            state_file=state_file,
        )
        before = datetime.now().isoformat()
        record_injection(
            ["mem-1", "mem-2"],
            session_id="sess-1",
            state_file=state_file,
        )
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["last_injection_ts"] is not None
        assert state["last_injection_ts"] >= before

    def test_records_exchange_number(self, state_file):
        """Sets last_injection_exchange to current exchange_count."""
        get_session_state(session_id="sess-1", state_file=state_file)
        update_session_state(
            {"exchange_count": 15},
            session_id="sess-1",
            state_file=state_file,
        )
        record_injection(
            ["mem-1"],
            session_id="sess-1",
            state_file=state_file,
        )
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["last_injection_exchange"] == 15

    def test_records_memory_ids(self, state_file):
        """Sets last_injected_ids to the provided memory IDs."""
        get_session_state(session_id="sess-1", state_file=state_file)
        record_injection(
            ["mem-a", "mem-b", "mem-c"],
            session_id="sess-1",
            state_file=state_file,
        )
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["last_injected_ids"] == ["mem-a", "mem-b", "mem-c"]


# ---------------------------------------------------------------------------
# TestCleanupStaleSessions
# ---------------------------------------------------------------------------

class TestCleanupStaleSessions:
    def test_removes_old_sessions(self, state_file):
        """Removes sessions older than max_age_hours."""
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
        data = {
            "old-session": {
                "exchange_count": 5,
                "project": None,
                "last_injection_ts": None,
                "last_injection_exchange": 0,
                "last_injected_ids": [],
                "active_skills": [],
                "injection_interval": 10,
                "initialized_at": old_ts,
            }
        }
        state_file.write_text(json.dumps(data))
        removed = cleanup_stale_sessions(state_file=state_file, max_age_hours=24)
        assert removed == 1
        assert load_state(state_file) == {}

    def test_keeps_recent_sessions(self, state_file):
        """Sessions within max_age_hours are preserved."""
        recent_ts = datetime.now().isoformat()
        data = {
            "recent-session": {
                "exchange_count": 5,
                "project": None,
                "last_injection_ts": None,
                "last_injection_exchange": 0,
                "last_injected_ids": [],
                "active_skills": [],
                "injection_interval": 10,
                "initialized_at": recent_ts,
            }
        }
        state_file.write_text(json.dumps(data))
        removed = cleanup_stale_sessions(state_file=state_file, max_age_hours=24)
        assert removed == 0
        assert "recent-session" in load_state(state_file)

    def test_returns_count_removed(self, state_file):
        """Returns exact count of removed sessions."""
        old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
        recent_ts = datetime.now().isoformat()
        data = {
            "old-1": {
                "exchange_count": 1,
                "initialized_at": old_ts,
            },
            "old-2": {
                "exchange_count": 2,
                "initialized_at": old_ts,
            },
            "recent": {
                "exchange_count": 3,
                "initialized_at": recent_ts,
            },
        }
        state_file.write_text(json.dumps(data))
        removed = cleanup_stale_sessions(state_file=state_file, max_age_hours=24)
        assert removed == 2
        remaining = load_state(state_file)
        assert "recent" in remaining
        assert "old-1" not in remaining
        assert "old-2" not in remaining


# ---------------------------------------------------------------------------
# TestFrustrationDetection
# ---------------------------------------------------------------------------

class TestFrustrationDetection:
    def test_you_should_know_pattern(self):
        """Detects 'you should know' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("you should know this already") is True
        assert detect_memory_signal("You should know about the API key") is True

    def test_weve_done_this_pattern(self):
        """Detects 'we've done this' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("we've done this before") is True
        assert detect_memory_signal("we have discussed this already") is True
        assert detect_memory_signal("we have talked about this") is True

    def test_ive_told_you_pattern(self):
        """Detects 'I've told you' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("I've already told you") is True
        assert detect_memory_signal("I have previously mentioned this") is True
        assert detect_memory_signal("I already said this") is True

    def test_remember_when_pattern(self):
        """Detects 'remember when' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("remember when we fixed this?") is True

    def test_as_i_said_pattern(self):
        """Detects 'as I said' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("as I said earlier") is True
        assert detect_memory_signal("as we discussed") is True
        assert detect_memory_signal("like we mentioned") is True

    def test_this_isnt_new_pattern(self):
        """Detects 'this isn't new' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("this isn't new information") is True
        assert detect_memory_signal("this is not new") is True

    def test_we_went_over_pattern(self):
        """Detects 'we went over this' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("we went over this yesterday") is True
        assert detect_memory_signal("we went through this already") is True

    def test_youve_forgotten_pattern(self):
        """Detects 'you've forgotten' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("you've forgotten about that") is True
        assert detect_memory_signal("you have forgotten") is True

    def test_how_many_times_pattern(self):
        """Detects 'how many times' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("how many times do I have to tell you") is True
        assert detect_memory_signal("how do I explain this") is True
        assert detect_memory_signal("how can I make this clearer") is True

    def test_pay_attention_pattern(self):
        """Detects 'pay attention' pattern."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("pay attention to what I'm saying") is True

    def test_false_positives_normal_conversation(self):
        """Does NOT match normal conversation without frustration."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("Can you help me with this?") is False
        assert detect_memory_signal("What should I do next?") is False
        assert detect_memory_signal("Let's review the documentation") is False
        assert detect_memory_signal("I need to understand this better") is False
        assert detect_memory_signal("Could you explain how this works?") is False

    def test_case_insensitive_matching(self):
        """Matches patterns case-insensitively."""
        from memory_system.hook_state import detect_memory_signal
        assert detect_memory_signal("YOU SHOULD KNOW THIS") is True
        assert detect_memory_signal("We've Done This Before") is True

    def test_should_inject_immediately_true(self):
        """should_inject_immediately returns True for frustration signals."""
        from memory_system.hook_state import should_inject_immediately
        assert should_inject_immediately("you should know this") is True
        assert should_inject_immediately("we've done this before") is True

    def test_should_inject_immediately_false(self):
        """should_inject_immediately returns False for normal prompts."""
        from memory_system.hook_state import should_inject_immediately
        assert should_inject_immediately("Can you help me?") is False
        assert should_inject_immediately("What is the solution?") is False


# ---------------------------------------------------------------------------
# TestIntervalReduction
# ---------------------------------------------------------------------------

class TestIntervalReduction:
    def test_reduces_interval_from_10_to_5(self, state_file):
        """Reduces injection_interval from 10 to 5 after frustration."""
        from memory_system.hook_state import reduce_injection_interval
        get_session_state(session_id="sess-1", state_file=state_file)
        # Initial interval should be 10
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["injection_interval"] == 10

        # Reduce interval
        reduce_injection_interval(session_id="sess-1", state_file=state_file)

        # Interval should now be 5
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["injection_interval"] == 5

    def test_reduced_interval_persists(self, state_file):
        """Reduced interval persists for the session."""
        from memory_system.hook_state import reduce_injection_interval
        get_session_state(session_id="sess-1", state_file=state_file)
        reduce_injection_interval(session_id="sess-1", state_file=state_file)

        # Simulate more exchanges
        update_session_state(
            {"exchange_count": 20},
            session_id="sess-1",
            state_file=state_file,
        )

        # Interval should still be 5
        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["injection_interval"] == 5

    def test_interval_reduction_idempotent(self, state_file):
        """Multiple calls to reduce_injection_interval don't reduce below 5."""
        from memory_system.hook_state import reduce_injection_interval
        get_session_state(session_id="sess-1", state_file=state_file)
        reduce_injection_interval(session_id="sess-1", state_file=state_file)
        reduce_injection_interval(session_id="sess-1", state_file=state_file)
        reduce_injection_interval(session_id="sess-1", state_file=state_file)

        state = get_session_state(session_id="sess-1", state_file=state_file)
        assert state["injection_interval"] == 5
