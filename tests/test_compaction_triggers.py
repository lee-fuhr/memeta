"""
Tests for compaction_triggers — time-based and event-based compaction triggers.
"""

from datetime import datetime, timedelta, timezone

import pytest

from memory_system.compaction_triggers import (
    check_inactivity_timeout,
    detect_session_end_signal,
    should_compact_enhanced,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _msg(content: str = "", minutes_ago: int = 0, has_timestamp: bool = True) -> dict:
    """Build a message dict with optional timestamp set to `minutes_ago` in the past."""
    msg: dict = {"role": "user", "content": content}
    if has_timestamp:
        ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        msg["timestamp"] = ts.isoformat()
    return msg


# ---------------------------------------------------------------------------
# check_inactivity_timeout
# ---------------------------------------------------------------------------

class TestCheckInactivityTimeout:
    """Tests for the inactivity timeout trigger."""

    def test_old_messages_trigger(self):
        """Messages older than timeout should trigger."""
        messages = [_msg(minutes_ago=120)]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is True

    def test_recent_messages_no_trigger(self):
        """Messages within timeout should not trigger."""
        messages = [_msg(minutes_ago=5)]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is False

    def test_empty_list_no_trigger(self):
        """Empty message list should not trigger."""
        assert check_inactivity_timeout([], timeout_minutes=60) is False

    def test_no_timestamps_no_trigger(self):
        """Messages without timestamp fields should not trigger."""
        messages = [_msg(has_timestamp=False), _msg(has_timestamp=False)]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is False

    def test_single_message_old_timestamp(self):
        """Edge case: single message with a very old timestamp triggers."""
        messages = [_msg(minutes_ago=1440)]  # 24 hours ago
        assert check_inactivity_timeout(messages, timeout_minutes=60) is True

    def test_uses_latest_timestamp(self):
        """When multiple messages exist, the latest timestamp is used."""
        messages = [
            _msg(minutes_ago=200),  # old
            _msg(minutes_ago=10),   # recent — this should be the reference
            _msg(minutes_ago=150),  # old
        ]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is False

    def test_boundary_just_over(self):
        """Exactly one minute past timeout should trigger."""
        messages = [_msg(minutes_ago=61)]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is True

    def test_boundary_just_under(self):
        """Just under the timeout should not trigger."""
        messages = [_msg(minutes_ago=59)]
        assert check_inactivity_timeout(messages, timeout_minutes=60) is False


# ---------------------------------------------------------------------------
# detect_session_end_signal
# ---------------------------------------------------------------------------

class TestDetectSessionEndSignal:
    """Tests for session-end signal detection."""

    @pytest.mark.parametrize("text", [
        "That's all for today",
        "thats all",
        "I'm done for now",
        "Done for today, thanks!",
        "Signing off!",
        "Ok sign off",
        "Wrapping up for the day",
        "Let's wrap up",
        "Good night!",
        "goodnight",
        "Talk later",
        "Talk tomorrow",
        "Closing out this session",
        "Let me close out",
        "Shutting down now",
    ])
    def test_positive_signals(self, text: str):
        """Known session-end phrases should be detected."""
        assert detect_session_end_signal(text) is True

    @pytest.mark.parametrize("text", [
        "Can you check the tests?",
        "What about the compaction logic?",
        "Let's keep going",
        "Not done yet",
        "I need more help",
    ])
    def test_negative_signals(self, text: str):
        """Normal conversation should not trigger."""
        assert detect_session_end_signal(text) is False

    def test_empty_string(self):
        """Empty string should not trigger."""
        assert detect_session_end_signal("") is False

    def test_delegates_to_handoff(self):
        """Should also detect handoff patterns from event_detector."""
        # "continue later" is a HANDOFF_KEYWORD in event_detector
        assert detect_session_end_signal("I'll continue later") is True

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert detect_session_end_signal("THAT'S ALL") is True
        assert detect_session_end_signal("DONE FOR NOW") is True


# ---------------------------------------------------------------------------
# should_compact_enhanced
# ---------------------------------------------------------------------------

class TestShouldCompactEnhanced:
    """Tests for the unified enhanced compaction check."""

    def test_message_count_triggers(self):
        """Exceeding message threshold triggers compaction."""
        messages = [_msg(minutes_ago=1) for _ in range(55)]
        result = should_compact_enhanced(messages, message_threshold=50)
        assert result["should_compact"] is True
        assert result["reason"] == "message_count"

    def test_inactivity_triggers_when_count_low(self):
        """Inactivity timeout triggers when count is below threshold."""
        messages = [_msg(content="hello", minutes_ago=120)]
        result = should_compact_enhanced(
            messages, message_threshold=50, timeout_minutes=60
        )
        assert result["should_compact"] is True
        assert result["reason"] == "inactivity_timeout"

    def test_session_end_signal_triggers(self):
        """Session-end signal in last message triggers compaction."""
        messages = [
            _msg(content="working on it", minutes_ago=5),
            _msg(content="Done for today, thanks!", minutes_ago=1),
        ]
        result = should_compact_enhanced(messages, message_threshold=50)
        assert result["should_compact"] is True
        assert result["reason"] == "session_end_signal"

    def test_no_triggers(self):
        """No triggers fire when all conditions are below threshold."""
        messages = [
            _msg(content="Let's keep going", minutes_ago=5),
            _msg(content="Sure, what's next?", minutes_ago=3),
        ]
        result = should_compact_enhanced(
            messages, message_threshold=50, timeout_minutes=60
        )
        assert result["should_compact"] is False
        assert result["reason"] is None

    def test_priority_message_count_wins(self):
        """When multiple triggers fire, message_count wins (highest priority)."""
        # 55 messages (over threshold), last one is a session-end signal,
        # and the timestamp is old — all three triggers would fire.
        messages = [_msg(content="stuff", minutes_ago=120) for _ in range(54)]
        messages.append(_msg(content="That's all for today", minutes_ago=120))
        result = should_compact_enhanced(
            messages, message_threshold=50, timeout_minutes=60
        )
        assert result["should_compact"] is True
        assert result["reason"] == "message_count"

    def test_priority_session_end_over_inactivity(self):
        """Session-end signal has higher priority than inactivity timeout."""
        messages = [
            _msg(content="Wrapping up", minutes_ago=120),
        ]
        result = should_compact_enhanced(
            messages, message_threshold=50, timeout_minutes=60
        )
        assert result["should_compact"] is True
        # session_end_signal should win over inactivity_timeout
        assert result["reason"] == "session_end_signal"

    def test_empty_messages(self):
        """Empty message list should not trigger."""
        result = should_compact_enhanced([])
        assert result["should_compact"] is False
        assert result["reason"] is None

    def test_details_populated(self):
        """Result dict always includes a human-readable 'details' string."""
        result = should_compact_enhanced([_msg(content="hi", minutes_ago=1)])
        assert isinstance(result["details"], str)
        assert len(result["details"]) > 0

    def test_at_threshold_no_trigger(self):
        """Exactly at threshold (not over) should not trigger on count."""
        messages = [_msg(minutes_ago=1) for _ in range(50)]
        result = should_compact_enhanced(messages, message_threshold=50)
        # 50 is NOT > 50, so message_count should not trigger
        assert result["reason"] != "message_count"
