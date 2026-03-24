"""Tests for confirmation tracking — "was this memory actually helpful?"

The confirmation tracker closes the feedback loop: memories get surfaced,
and the system detects whether the user's subsequent response indicates
the memory was useful. Tracks confirmation_count and last_confirmed per memory.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Module under test — will fail until we build it (RED phase)
from memory_system.confirmation_tracker import (
    check_confirmation,
    get_confirmation_stats,
    get_frequently_ignored,
    get_most_confirmed,
    record_confirmation,
    record_surfacing,
)
from memory_system.hook_state import (
    get_session_state,
    load_state,
    save_state,
    update_session_state,
)


@pytest.fixture
def state_file(tmp_path):
    """Temp hook-state file."""
    return tmp_path / "hook-state.json"


@pytest.fixture
def memory_dir(tmp_path):
    """Temp memory dir with sample memories."""
    d = tmp_path / "memories"
    d.mkdir()
    return d


def _write_memory(memory_dir: Path, memory_id: str, content: str, **extra_fields) -> Path:
    """Helper: write a minimal memory YAML file."""
    fields = {
        "id": memory_id,
        "importance_weight": 0.7,
        "context_type": "knowledge",
        "confirmation_count": 0,
        "last_confirmed": "null",
        "surfaced_count": 0,
    }
    fields.update(extra_fields)

    frontmatter_lines = [f"{k}: {v}" for k, v in fields.items()]
    text = f"---\n" + "\n".join(frontmatter_lines) + f"\n---\n\n{content}"

    filepath = memory_dir / f"{memory_id}.md"
    filepath.write_text(text)
    return filepath


# === record_surfacing tests ===


class TestRecordSurfacing:
    """Track which memories were surfaced and when."""

    def test_records_surfaced_ids_in_hook_state(self, state_file):
        """Surfaced memory IDs are stored in hook state for later confirmation check."""
        record_surfacing(
            memory_ids=["mem-001", "mem-002"],
            user_prompt="how do I set up the calendar?",
            session_id="test-session",
            state_file=state_file,
        )
        state = load_state(state_file)
        session = state["test-session"]
        assert "pending_confirmations" in session
        assert len(session["pending_confirmations"]) == 2
        assert session["pending_confirmations"][0]["memory_id"] == "mem-001"
        assert session["pending_confirmations"][1]["memory_id"] == "mem-002"

    def test_records_prompt_context(self, state_file):
        """Stores the prompt that triggered the surfacing for later comparison."""
        record_surfacing(
            memory_ids=["mem-001"],
            user_prompt="calendar setup for household events",
            session_id="test-session",
            state_file=state_file,
        )
        state = load_state(state_file)
        pending = state["test-session"]["pending_confirmations"][0]
        assert pending["surfaced_at_prompt"] == "calendar setup for household events"

    def test_records_timestamp(self, state_file):
        """Each surfacing gets a timestamp."""
        record_surfacing(
            memory_ids=["mem-001"],
            user_prompt="test prompt",
            session_id="test-session",
            state_file=state_file,
        )
        state = load_state(state_file)
        pending = state["test-session"]["pending_confirmations"][0]
        assert "surfaced_at" in pending
        # Should be a valid ISO timestamp
        datetime.fromisoformat(pending["surfaced_at"])

    def test_appends_to_existing_pending(self, state_file):
        """Multiple surfacings accumulate, don't overwrite."""
        record_surfacing(
            memory_ids=["mem-001"],
            user_prompt="first prompt",
            session_id="test-session",
            state_file=state_file,
        )
        record_surfacing(
            memory_ids=["mem-002"],
            user_prompt="second prompt",
            session_id="test-session",
            state_file=state_file,
        )
        state = load_state(state_file)
        assert len(state["test-session"]["pending_confirmations"]) == 2


# === check_confirmation tests ===


class TestCheckConfirmation:
    """Detect whether user's response references surfaced memories."""

    def test_keyword_overlap_confirms(self, state_file):
        """If user response contains significant keywords from surfaced memory, that's a confirmation."""
        # Memory about calendar was surfaced
        record_surfacing(
            memory_ids=["mem-cal"],
            user_prompt="how do events work?",
            session_id="test-session",
            state_file=state_file,
        )

        # Memory content keywords: "TerraLee shared calendar invite attendees"
        memory_contents = {
            "mem-cal": "Calendar household events go on TerraLee shared calendar with both as attendees"
        }

        # User's next response references the calendar concept
        confirmed_ids = check_confirmation(
            user_response="yes, put it on the TerraLee shared calendar",
            memory_contents=memory_contents,
            session_id="test-session",
            state_file=state_file,
        )
        assert "mem-cal" in confirmed_ids

    def test_no_overlap_means_no_confirmation(self, state_file):
        """If user response is unrelated to surfaced memory, no confirmation."""
        record_surfacing(
            memory_ids=["mem-cal"],
            user_prompt="how do events work?",
            session_id="test-session",
            state_file=state_file,
        )

        memory_contents = {
            "mem-cal": "Calendar household events go on TerraLee shared calendar with both as attendees"
        }

        # User's response is about something completely different
        confirmed_ids = check_confirmation(
            user_response="actually let's work on the LinkedIn post instead",
            memory_contents=memory_contents,
            session_id="test-session",
            state_file=state_file,
        )
        assert len(confirmed_ids) == 0

    def test_explicit_acknowledgment_confirms(self, state_file):
        """Phrases like "right", "yes", "exactly", "good point" count as confirmation."""
        record_surfacing(
            memory_ids=["mem-voice"],
            user_prompt="draft an email",
            session_id="test-session",
            state_file=state_file,
        )

        memory_contents = {
            "mem-voice": "Lee avoids em-dashes in partner emails"
        }

        confirmed_ids = check_confirmation(
            user_response="right, and make sure there are no em-dashes",
            memory_contents=memory_contents,
            session_id="test-session",
            state_file=state_file,
        )
        assert "mem-voice" in confirmed_ids

    def test_clears_pending_after_check(self, state_file):
        """After checking, pending confirmations are cleared."""
        record_surfacing(
            memory_ids=["mem-001"],
            user_prompt="test",
            session_id="test-session",
            state_file=state_file,
        )

        check_confirmation(
            user_response="something",
            memory_contents={"mem-001": "test content"},
            session_id="test-session",
            state_file=state_file,
        )

        state = load_state(state_file)
        assert len(state["test-session"].get("pending_confirmations", [])) == 0

    def test_no_pending_returns_empty(self, state_file):
        """If there's nothing pending, return empty list."""
        # Initialize session but don't surface anything
        update_session_state(
            {"exchange_count": 1},
            session_id="test-session",
            state_file=state_file,
        )

        confirmed_ids = check_confirmation(
            user_response="anything",
            memory_contents={},
            session_id="test-session",
            state_file=state_file,
        )
        assert confirmed_ids == []

    def test_multiple_surfaced_partial_confirmation(self, state_file):
        """If 3 memories surfaced but only 1 is referenced, only that 1 is confirmed."""
        record_surfacing(
            memory_ids=["mem-cal", "mem-voice", "mem-tdd"],
            user_prompt="help me with email",
            session_id="test-session",
            state_file=state_file,
        )

        memory_contents = {
            "mem-cal": "Calendar household events on TerraLee shared calendar",
            "mem-voice": "Lee avoids em-dashes in partner emails",
            "mem-tdd": "TDD red green refactor mandatory",
        }

        confirmed_ids = check_confirmation(
            user_response="good reminder about the em-dashes, thanks",
            memory_contents=memory_contents,
            session_id="test-session",
            state_file=state_file,
        )
        assert "mem-voice" in confirmed_ids
        assert "mem-cal" not in confirmed_ids
        assert "mem-tdd" not in confirmed_ids


# === record_confirmation tests ===


class TestRecordConfirmation:
    """Persist confirmation data to memory files."""

    def test_increments_confirmation_count(self, memory_dir):
        """Confirming a memory increments its confirmation_count."""
        _write_memory(memory_dir, "mem-001", "test content", confirmation_count=0)

        record_confirmation("mem-001", memory_dir=memory_dir)

        text = (memory_dir / "mem-001.md").read_text()
        assert "confirmation_count: 1" in text

    def test_updates_last_confirmed_timestamp(self, memory_dir):
        """Confirming updates last_confirmed to current time."""
        _write_memory(memory_dir, "mem-001", "test content")

        record_confirmation("mem-001", memory_dir=memory_dir)

        text = (memory_dir / "mem-001.md").read_text()
        assert "last_confirmed: null" not in text
        # Should contain an ISO date
        assert "last_confirmed: 20" in text

    def test_increments_surfaced_count(self, memory_dir):
        """Every surfacing (confirmed or not) increments surfaced_count."""
        _write_memory(memory_dir, "mem-001", "test content", surfaced_count=0)

        record_confirmation("mem-001", memory_dir=memory_dir, was_confirmed=True)

        text = (memory_dir / "mem-001.md").read_text()
        assert "surfaced_count: 1" in text

    def test_surfaced_but_not_confirmed_only_increments_surfaced(self, memory_dir):
        """If surfaced but NOT confirmed, only surfaced_count goes up."""
        _write_memory(memory_dir, "mem-001", "test content", confirmation_count=0, surfaced_count=0)

        record_confirmation("mem-001", memory_dir=memory_dir, was_confirmed=False)

        text = (memory_dir / "mem-001.md").read_text()
        assert "confirmation_count: 0" in text
        assert "surfaced_count: 1" in text

    def test_missing_memory_file_is_noop(self, memory_dir):
        """If the memory file doesn't exist, do nothing (don't crash)."""
        # No file created — should not raise
        record_confirmation("nonexistent-mem", memory_dir=memory_dir)

    def test_multiple_confirmations_accumulate(self, memory_dir):
        """Confirming multiple times accumulates the count."""
        _write_memory(memory_dir, "mem-001", "test content", confirmation_count=0)

        record_confirmation("mem-001", memory_dir=memory_dir)
        record_confirmation("mem-001", memory_dir=memory_dir)
        record_confirmation("mem-001", memory_dir=memory_dir)

        text = (memory_dir / "mem-001.md").read_text()
        assert "confirmation_count: 3" in text


# === Query functions ===


class TestConfirmationStats:
    """Query confirmation data across memories."""

    def test_get_most_confirmed(self, memory_dir):
        """Returns memories sorted by confirmation_count descending."""
        _write_memory(memory_dir, "mem-a", "content a", confirmation_count=5)
        _write_memory(memory_dir, "mem-b", "content b", confirmation_count=12)
        _write_memory(memory_dir, "mem-c", "content c", confirmation_count=0)

        top = get_most_confirmed(memory_dir=memory_dir, top_k=2)
        assert len(top) == 2
        assert top[0]["id"] == "mem-b"
        assert top[0]["confirmation_count"] == 12
        assert top[1]["id"] == "mem-a"

    def test_get_frequently_ignored(self, memory_dir):
        """Returns memories surfaced 3+ times but never confirmed."""
        _write_memory(memory_dir, "mem-a", "useful", confirmation_count=5, surfaced_count=10)
        _write_memory(memory_dir, "mem-b", "ignored", confirmation_count=0, surfaced_count=5)
        _write_memory(memory_dir, "mem-c", "new", confirmation_count=0, surfaced_count=1)

        ignored = get_frequently_ignored(memory_dir=memory_dir, min_surfaced=3)
        assert len(ignored) == 1
        assert ignored[0]["id"] == "mem-b"

    def test_get_confirmation_stats(self, memory_dir):
        """Returns aggregate stats: total memories, total confirmations, confirmation rate."""
        _write_memory(memory_dir, "mem-a", "a", confirmation_count=5, surfaced_count=10)
        _write_memory(memory_dir, "mem-b", "b", confirmation_count=0, surfaced_count=5)
        _write_memory(memory_dir, "mem-c", "c", confirmation_count=3, surfaced_count=3)

        stats = get_confirmation_stats(memory_dir=memory_dir)
        assert stats["total_memories"] == 3
        assert stats["total_confirmations"] == 8
        assert stats["total_surfacings"] == 18
        assert stats["confirmation_rate"] == pytest.approx(8 / 18, abs=0.01)
        assert stats["never_confirmed_count"] == 1
