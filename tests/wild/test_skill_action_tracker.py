"""Tests for skill action tracker — tracks recurring action patterns and skill usage events."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta

from memory_system.wild.skill_action_tracker import SkillActionTracker, ActionPattern


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def temp_state(tmp_path):
    """Create temporary state file path."""
    return tmp_path / "action-patterns.json"


@pytest.fixture
def tracker(temp_db, temp_state):
    """Create SkillActionTracker with temp database and state file."""
    return SkillActionTracker(state_path=temp_state, db_path=temp_db)


# --- Initialization ---

def test_initialization_creates_default_state(tracker, temp_state):
    """Tracker creates a default state file on first load."""
    assert temp_state.exists()
    with open(temp_state) as f:
        state = json.load(f)
    assert state["version"] == 1
    assert state["action_patterns"] == {}
    assert state["processed_sessions"] == {}


def test_initialization_loads_existing_state(temp_db, temp_state):
    """Tracker loads existing state from disk."""
    existing = {
        "version": 1,
        "action_patterns": {
            "abc123": {
                "id": "abc123",
                "action_signature": "test action",
                "canonical_form": "test_action",
                "first_seen": "2026-02-20T10:00:00",
                "last_seen": "2026-02-20T10:00:00",
                "frequency": 3,
                "daily_occurrences": {"2026-02-20": 3},
                "session_ids": ["s1"],
                "mapped_skill": None,
                "proposed_skill": None,
            }
        },
        "processed_sessions": {},
    }
    temp_state.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_state, "w") as f:
        json.dump(existing, f)

    tracker = SkillActionTracker(state_path=temp_state, db_path=temp_db)
    patterns = tracker.get_patterns()
    assert len(patterns) == 1
    assert patterns[0].action_signature == "test action"
    assert patterns[0].frequency == 3


# --- record_action ---

def test_record_action_new_pattern(tracker):
    """Recording a new action creates a new pattern entry."""
    pattern = tracker.record_action("create google doc", session_id="sess1")
    assert isinstance(pattern, ActionPattern)
    assert pattern.action_signature == "create google doc"
    assert pattern.frequency == 1
    assert "sess1" in pattern.session_ids


def test_record_action_existing_pattern_increments(tracker):
    """Recording the same action increments frequency."""
    tracker.record_action("create google doc", session_id="sess1")
    pattern = tracker.record_action("create google doc", session_id="sess2")
    assert pattern.frequency == 2


def test_record_action_updates_daily_occurrences(tracker):
    """Daily occurrences are tracked per date."""
    pattern = tracker.record_action("create google doc", session_id="sess1")
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in pattern.daily_occurrences
    assert pattern.daily_occurrences[today] == 1

    pattern = tracker.record_action("create google doc", session_id="sess2")
    assert pattern.daily_occurrences[today] == 2


def test_record_action_tracks_session_ids(tracker):
    """Session IDs are deduplicated across recordings."""
    tracker.record_action("create google doc", session_id="sess1")
    tracker.record_action("create google doc", session_id="sess1")
    pattern = tracker.record_action("create google doc", session_id="sess2")
    assert sorted(pattern.session_ids) == ["sess1", "sess2"]


def test_record_action_auto_generates_canonical_form(tracker):
    """Canonical form is auto-generated from the action signature."""
    pattern = tracker.record_action("Create Google Doc with formatting", session_id="s1")
    assert pattern.canonical_form == "create_google_doc_formatting"


def test_record_action_uses_provided_canonical_form(tracker):
    """Provided canonical form overrides auto-generation."""
    pattern = tracker.record_action(
        "Create Google Doc with formatting",
        session_id="s1",
        canonical_form="gdoc_formatted",
    )
    assert pattern.canonical_form == "gdoc_formatted"


# --- record_skill_usage ---

def test_record_skill_usage_creates_event(tracker, temp_db):
    """Skill usage event is logged to the database."""
    tracker.record_skill_usage("google-docs-editor", session_id="sess1")

    import sqlite3
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM skill_usage_events WHERE skill_name = ?", ("google-docs-editor",)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess1"


def test_record_skill_usage_multiple_events(tracker, temp_db):
    """Multiple skill usage events are logged independently."""
    tracker.record_skill_usage("google-docs-editor", session_id="sess1")
    tracker.record_skill_usage("google-docs-editor", session_id="sess2")
    tracker.record_skill_usage("copywriting", session_id="sess1")

    import sqlite3
    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT COUNT(*) FROM skill_usage_events").fetchone()
    conn.close()
    assert rows[0] == 3


# --- get_patterns ---

def test_get_patterns_returns_all(tracker):
    """get_patterns returns all recorded patterns."""
    tracker.record_action("action one", session_id="s1")
    tracker.record_action("action two", session_id="s1")
    patterns = tracker.get_patterns()
    assert len(patterns) == 2


def test_get_patterns_with_min_frequency(tracker):
    """get_patterns filters by minimum frequency."""
    tracker.record_action("rare action", session_id="s1")
    tracker.record_action("common action", session_id="s1")
    tracker.record_action("common action", session_id="s2")
    tracker.record_action("common action", session_id="s3")

    patterns = tracker.get_patterns(min_frequency=3)
    assert len(patterns) == 1
    assert patterns[0].action_signature == "common action"


# --- get_pattern ---

def test_get_pattern_by_id(tracker):
    """get_pattern retrieves a single pattern by its hash ID."""
    pattern = tracker.record_action("test action", session_id="s1")
    result = tracker.get_pattern(pattern.id)
    assert result is not None
    assert result.action_signature == "test action"


def test_get_pattern_not_found_returns_none(tracker):
    """get_pattern returns None for unknown IDs."""
    assert tracker.get_pattern("nonexistent_hash") is None


# --- extract_skill_invocations ---

def test_extract_skill_invocations_finds_skill_tool(tracker):
    """Extracts skill names from session messages containing Skill tool use."""
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "copywriting"}},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "seo-audit"}},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]},
    ]
    skills = tracker.extract_skill_invocations(messages)
    assert sorted(skills) == ["copywriting", "seo-audit"]


def test_extract_skill_invocations_empty_messages(tracker):
    """Returns empty list for empty or no-skill messages."""
    assert tracker.extract_skill_invocations([]) == []
    assert tracker.extract_skill_invocations([{"role": "user", "content": "hello"}]) == []


# --- compute_prompt_similarity ---

def test_compute_prompt_similarity_identical(tracker):
    """Identical prompts have similarity of 1.0."""
    assert tracker.compute_prompt_similarity("create a doc", "create a doc") == 1.0


def test_compute_prompt_similarity_different(tracker):
    """Completely different prompts have similarity of 0.0."""
    assert tracker.compute_prompt_similarity("apple banana cherry", "dog elephant frog") == 0.0


def test_compute_prompt_similarity_partial_overlap(tracker):
    """Partially overlapping prompts have similarity between 0 and 1."""
    sim = tracker.compute_prompt_similarity("create a google doc", "create a notion page")
    assert 0.0 < sim < 1.0


# --- self-cleaning ---

def test_self_clean_removes_old_entries(tracker):
    """Entries older than max_age_days are removed on save."""
    old_date = (datetime.now() - timedelta(days=100)).isoformat()
    state = tracker._load_state()
    state["action_patterns"]["old_hash"] = {
        "id": "old_hash",
        "action_signature": "old action",
        "canonical_form": "old_action",
        "first_seen": old_date,
        "last_seen": old_date,
        "frequency": 5,
        "daily_occurrences": {},
        "session_ids": ["s1"],
        "mapped_skill": None,
        "proposed_skill": None,
    }
    tracker._save_state(state)

    reloaded = tracker._load_state()
    assert "old_hash" not in reloaded["action_patterns"]


def test_self_clean_keeps_recent_entries(tracker):
    """Recent entries are preserved during self-cleaning."""
    recent_date = datetime.now().isoformat()
    state = tracker._load_state()
    state["action_patterns"]["new_hash"] = {
        "id": "new_hash",
        "action_signature": "recent action",
        "canonical_form": "recent_action",
        "first_seen": recent_date,
        "last_seen": recent_date,
        "frequency": 2,
        "daily_occurrences": {},
        "session_ids": ["s1"],
        "mapped_skill": None,
        "proposed_skill": None,
    }
    tracker._save_state(state)

    reloaded = tracker._load_state()
    assert "new_hash" in reloaded["action_patterns"]


# --- save creates parent dirs ---

def test_save_state_creates_parent_dirs(tmp_path, temp_db):
    """Saving state creates parent directories if they don't exist."""
    nested_path = tmp_path / "deep" / "nested" / "dir" / "action-patterns.json"
    tracker = SkillActionTracker(state_path=nested_path, db_path=temp_db)
    # Initialization triggers _load_state which creates the file
    assert nested_path.exists()
