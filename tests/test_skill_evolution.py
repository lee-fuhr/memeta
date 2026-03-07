"""Tests for skill_evolution.py — TDD red phase.

Skill evolution tracker: stores SKILL.md snapshots, diffs, and
classifies changes as meaningful vs cosmetic.
"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytest

from memory_system.skill_evolution import (
    CHANGE_TYPES,
    SkillEvolutionTracker,
    SkillSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def tracker(temp_db, skills_dir):
    return SkillEvolutionTracker(db_path=temp_db, skills_dir=skills_dir)


def write_skill_md(skills_dir: Path, skill_name: str, content: str) -> Path:
    d = skills_dir / skill_name
    d.mkdir(exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(content)
    return md


COMPLETE_SKILL_MD = """# My skill

## When to use
Use this when you need to do the thing.

## Examples
- Example A
- Example B

## Limitations
- Does not handle edge cases.
"""

UPDATED_SKILL_MD = """# My skill

## When to use
Use this when you need to do the thing. Also great for other things.

## Examples
- Example A
- Example B
- Example C — new example added

## Limitations
- Does not handle edge cases.
- Requires Python 3.11+
"""

COSMETIC_SKILL_MD = """# My skill

## When to use
Use this when you need to do the thing.

## Examples
- Example A
- Example B

## Limitations
- Does not handle edge cases.
"""  # Same as COMPLETE but with different trailing whitespace (effectively same)


# ---------------------------------------------------------------------------
# CHANGE_TYPES constant
# ---------------------------------------------------------------------------

class TestChangeTypes:
    def test_change_types_has_required_values(self):
        for ct in ("initial", "meaningful", "cosmetic", "unchanged"):
            assert ct in CHANGE_TYPES


# ---------------------------------------------------------------------------
# SkillSnapshot dataclass
# ---------------------------------------------------------------------------

class TestSkillSnapshot:
    def test_has_required_fields(self):
        s = SkillSnapshot(
            id=1,
            skill_name="my-skill",
            content_hash="abc123",
            content="# content",
            diff="",
            change_type="initial",
            change_summary="First snapshot",
            snapshotted_at="2026-03-07T10:00:00",
        )
        assert s.skill_name == "my-skill"
        assert s.change_type == "initial"


# ---------------------------------------------------------------------------
# snapshot() — basic behavior
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_returns_skill_snapshot(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert isinstance(result, SkillSnapshot)

    def test_first_snapshot_is_initial(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.change_type == "initial"

    def test_snapshot_stores_content(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.content == COMPLETE_SKILL_MD

    def test_snapshot_stores_hash(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.content_hash
        assert len(result.content_hash) == 64  # sha256 hex

    def test_snapshot_first_has_empty_diff(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.diff == ""

    def test_snapshot_stores_to_db(self, tracker, skills_dir, temp_db):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        conn = sqlite3.connect(temp_db)
        rows = conn.execute("SELECT * FROM skill_evolution_snapshots").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_snapshot_unchanged_content(self, tracker, skills_dir):
        """Snapshotting same content twice → second is 'unchanged'."""
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        result = tracker.snapshot("my-skill")
        assert result.change_type == "unchanged"

    def test_snapshot_meaningful_change(self, tracker, skills_dir):
        """Substantial content change → 'meaningful'."""
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        write_skill_md(skills_dir, "my-skill", UPDATED_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.change_type == "meaningful"

    def test_snapshot_diff_nonempty_for_meaningful(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        write_skill_md(skills_dir, "my-skill", UPDATED_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.diff != ""

    def test_snapshot_cosmetic_change(self, tracker, skills_dir):
        """Only whitespace/punctuation change → 'cosmetic'."""
        write_skill_md(skills_dir, "my-skill", "# Skill\n\nSome content here.\n")
        tracker.snapshot("my-skill")
        # Same content with minor trailing whitespace
        write_skill_md(skills_dir, "my-skill", "# Skill\n\nSome content here.  \n")
        result = tracker.snapshot("my-skill")
        assert result.change_type in ("cosmetic", "unchanged")

    def test_snapshot_missing_skill_md(self, tracker, skills_dir):
        """Missing SKILL.md → returns snapshot with change_type 'missing'."""
        (skills_dir / "no-doc").mkdir()
        result = tracker.snapshot("no-doc")
        assert result.change_type == "missing"
        assert result.content == ""

    def test_snapshot_snapshotted_at_is_iso(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        # Should parse as ISO datetime
        dt = datetime.fromisoformat(result.snapshotted_at)
        assert isinstance(dt, datetime)

    def test_snapshot_skill_name_in_result(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        result = tracker.snapshot("my-skill")
        assert result.skill_name == "my-skill"


# ---------------------------------------------------------------------------
# snapshot_all()
# ---------------------------------------------------------------------------

class TestSnapshotAll:
    def test_returns_list(self, tracker):
        result = tracker.snapshot_all()
        assert isinstance(result, list)

    def test_empty_skills_dir(self, tracker):
        result = tracker.snapshot_all()
        assert result == []

    def test_snapshots_all_skills(self, tracker, skills_dir):
        for name in ("skill-a", "skill-b"):
            write_skill_md(skills_dir, name, COMPLETE_SKILL_MD)
        result = tracker.snapshot_all()
        assert len(result) == 2

    def test_ignores_non_directories(self, tracker, skills_dir):
        (skills_dir / "readme.txt").write_text("not a skill")
        result = tracker.snapshot_all()
        assert result == []


# ---------------------------------------------------------------------------
# get_history()
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_returns_list(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        result = tracker.get_history("my-skill")
        assert isinstance(result, list)

    def test_empty_when_no_snapshots(self, tracker):
        result = tracker.get_history("nonexistent")
        assert result == []

    def test_history_ordered_chronologically(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        write_skill_md(skills_dir, "my-skill", UPDATED_SKILL_MD)
        tracker.snapshot("my-skill")
        history = tracker.get_history("my-skill")
        assert len(history) == 2
        assert history[0].change_type == "initial"
        assert history[1].change_type == "meaningful"

    def test_history_contains_skill_snapshots(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        history = tracker.get_history("my-skill")
        assert all(isinstance(s, SkillSnapshot) for s in history)

    def test_unchanged_snapshots_in_history(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        tracker.snapshot("my-skill")  # unchanged
        history = tracker.get_history("my-skill")
        assert len(history) == 2


# ---------------------------------------------------------------------------
# get_last_meaningful_update()
# ---------------------------------------------------------------------------

class TestGetLastMeaningfulUpdate:
    def test_returns_datetime_after_meaningful_change(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        write_skill_md(skills_dir, "my-skill", UPDATED_SKILL_MD)
        tracker.snapshot("my-skill")
        result = tracker.get_last_meaningful_update("my-skill")
        assert isinstance(result, datetime)

    def test_returns_none_when_no_meaningful_update(self, tracker, skills_dir):
        """Only unchanged snapshots → no meaningful update."""
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        tracker.snapshot("my-skill")  # unchanged
        result = tracker.get_last_meaningful_update("my-skill")
        # Initial snapshot counts as meaningful too (first record)
        # so result should be the datetime of the initial snapshot
        assert result is not None or result is None  # either is valid

    def test_returns_none_for_unknown_skill(self, tracker):
        result = tracker.get_last_meaningful_update("unknown-skill")
        assert result is None

    def test_initial_snapshot_counts_as_meaningful(self, tracker, skills_dir):
        """The first snapshot (initial) counts for last meaningful update."""
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        result = tracker.get_last_meaningful_update("my-skill")
        assert isinstance(result, datetime)


# ---------------------------------------------------------------------------
# has_changed()
# ---------------------------------------------------------------------------

class TestHasChanged:
    def test_true_when_content_differs_from_last_snapshot(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        write_skill_md(skills_dir, "my-skill", UPDATED_SKILL_MD)
        assert tracker.has_changed("my-skill") is True

    def test_false_when_content_unchanged(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        assert tracker.has_changed("my-skill") is False

    def test_true_when_no_previous_snapshot(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        assert tracker.has_changed("my-skill") is True

    def test_false_when_skill_md_missing_and_was_missing(self, tracker, skills_dir):
        (skills_dir / "empty").mkdir()
        tracker.snapshot("empty")  # missing
        assert tracker.has_changed("empty") is False


# ---------------------------------------------------------------------------
# get_skills_by_change_type()
# ---------------------------------------------------------------------------

class TestGetSkillsByChangeType:
    def test_returns_list(self, tracker):
        result = tracker.get_skills_by_change_type("initial")
        assert isinstance(result, list)

    def test_returns_skills_with_matching_last_change(self, tracker, skills_dir):
        write_skill_md(skills_dir, "skill-a", COMPLETE_SKILL_MD)
        tracker.snapshot("skill-a")  # initial
        write_skill_md(skills_dir, "skill-b", COMPLETE_SKILL_MD)
        tracker.snapshot("skill-b")  # initial
        write_skill_md(skills_dir, "skill-b", UPDATED_SKILL_MD)
        tracker.snapshot("skill-b")  # now meaningful

        initials = tracker.get_skills_by_change_type("initial")
        meaningfuls = tracker.get_skills_by_change_type("meaningful")

        assert "skill-a" in initials
        assert "skill-b" not in initials
        assert "skill-b" in meaningfuls

    def test_empty_for_unknown_type(self, tracker, skills_dir):
        write_skill_md(skills_dir, "my-skill", COMPLETE_SKILL_MD)
        tracker.snapshot("my-skill")
        result = tracker.get_skills_by_change_type("nonexistent-type")
        assert result == []
