"""Sprint 4 hardening tests — chaos/edge-case probes for skill lifecycle.

Targets edge cases that normal test suites miss:
- Corrupted/missing data (empty files, malformed JSON, wrong schema)
- Large data (100 skills, 50 patterns, bulk decay scoring)
- Boundary conditions (use_count=0, use_count=999999, threshold-exact)
- Concurrent/race conditions (dual managers, rapid usage, duplicate maintenance)
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory_system.wild.intelligence_db import IntelligenceDB
from memory_system.wild.skill_lifecycle import SkillLifecycleManager
from memory_system.wild.skill_action_tracker import SkillActionTracker
from memory_system.wild.skill_registry_scanner import SkillRegistryScanner
from memory_system.wild.skill_decay_scorer import SkillDecayScorer
from memory_system.wild.skill_proposal_engine import SkillProposalEngine


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield Path(path)
    os.unlink(path)


@pytest.fixture
def temp_state(tmp_path):
    return tmp_path / "skill-lifecycle" / "action-patterns.json"


@pytest.fixture
def temp_skills_dir(tmp_path):
    """Create a single valid skill directory."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# Test skill\n\nA test skill for hardening.\n\n## Triggers\n- Testing\n"
    )
    return tmp_path


@pytest.fixture
def populated_db(temp_db):
    """DB with one skill already in the registry."""
    db = IntelligenceDB(temp_db)
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO skill_registry "
        "(skill_name, skill_path, description, keywords, first_seen, use_count, last_used) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("existing-skill", "/fake/path", "An existing skill", '["testing"]', now, 5, now),
    )
    db.conn.commit()
    db.close()
    return temp_db


# ═══════════════════════════════════════════════════════════════════════════
# 1. Corrupted/missing data
# ═══════════════════════════════════════════════════════════════════════════


class TestCorruptedMissingData:
    """Tests for graceful handling of corrupted or missing data."""

    def test_empty_json_state_file(self, temp_db, temp_skills_dir, tmp_path):
        """Empty (0-byte) state file should be handled — reset to defaults."""
        state_path = tmp_path / "empty-state.json"
        state_path.write_text("")  # 0 bytes of content

        # SkillLifecycleManager catches the JSONDecodeError in __init__,
        # deletes the corrupted file, and retries with defaults.
        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=state_path,
            skills_dir=temp_skills_dir,
        )
        # Should function normally after recovery
        summary = mgr.get_lifecycle_summary()
        assert "proposals" in summary
        assert "registry" in summary

    def test_malformed_json_state_file(self, temp_db, temp_skills_dir, tmp_path):
        """Malformed JSON (e.g., '{broken') should be handled — reset to defaults."""
        state_path = tmp_path / "broken-state.json"
        state_path.write_text("{broken")

        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=state_path,
            skills_dir=temp_skills_dir,
        )
        summary = mgr.get_lifecycle_summary()
        assert summary["action_patterns"]["total"] == 0

    def test_wrong_schema_state_file(self, temp_db, temp_skills_dir, tmp_path):
        """State file with unexpected schema should be handled gracefully."""
        state_path = tmp_path / "wrong-schema.json"
        state_path.write_text(json.dumps({"version": 999, "unexpected_key": True}))

        # The tracker's _load_state returns whatever is in the file.
        # Missing "action_patterns" key should not crash get_patterns.
        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=state_path,
            skills_dir=temp_skills_dir,
        )
        # get_lifecycle_summary calls tracker.get_patterns() which calls _load_state
        # and iterates state["action_patterns"].values() — will KeyError if missing.
        # The facade catches this in its try/except.
        summary = mgr.get_lifecycle_summary()
        assert isinstance(summary, dict)

    def test_missing_intelligence_db_path(self, temp_skills_dir, tmp_path):
        """Non-existent DB path should be created automatically by SQLite."""
        nonexistent_db = tmp_path / "deep" / "nested" / "intelligence.db"
        state_path = tmp_path / "state.json"

        # IntelligenceDB uses sqlite3.connect which creates the file.
        # But the parent directory must exist for SQLite to create the file.
        # Let's test what actually happens.
        nonexistent_db.parent.mkdir(parents=True, exist_ok=True)

        mgr = SkillLifecycleManager(
            db_path=nonexistent_db,
            state_path=state_path,
            skills_dir=temp_skills_dir,
        )
        summary = mgr.get_lifecycle_summary()
        assert summary["registry"]["total_skills"] == 0

    def test_db_with_tables_but_empty_rows(self, temp_db, temp_skills_dir, tmp_path):
        """DB with proper schema but zero rows — all operations should succeed."""
        state_path = tmp_path / "state.json"

        # temp_db gets schema from IntelligenceDB init inside SkillLifecycleManager
        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=state_path,
            skills_dir=temp_skills_dir,
        )

        # Every sub-operation should return empty results, not crash
        summary = mgr.run_daily_maintenance()
        assert summary["decay_scores_updated"] >= 0
        assert isinstance(summary["newly_flagged"], list)
        assert isinstance(summary["new_proposals"], list)

        lifecycle = mgr.get_lifecycle_summary()
        assert lifecycle["registry"]["total_skills"] >= 0
        assert lifecycle["proposals"]["total_pending"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Large data
# ═══════════════════════════════════════════════════════════════════════════


class TestLargeData:
    """Tests for performance with large datasets."""

    def test_100_skills_in_registry(self, temp_db, tmp_path):
        """Scanner should pick up 100 skills from filesystem."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create 100 skill directories
        for i in range(100):
            skill_dir = skills_dir / f"skill-{i:03d}"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"# Skill {i}\n\nDescription for skill {i}.\n\n## Triggers\n- trigger-{i}\n"
            )

        scanner = SkillRegistryScanner(skills_dir=skills_dir, db_path=temp_db)
        result = scanner.sync_to_db()
        assert result["new"] == 100
        assert result["total"] == 100

        all_skills = scanner.get_all_skills()
        assert len(all_skills) == 100

    def test_50_action_patterns_high_frequency(self, temp_db, tmp_path):
        """Proposal engine should handle 50 patterns without blowing up."""
        state_path = tmp_path / "state.json"

        tracker = SkillActionTracker(state_path=state_path, db_path=temp_db)

        # Create 50 patterns, each with high frequency
        for i in range(50):
            for _ in range(5):
                tracker.record_action(
                    f"action pattern number {i} with unique words {i}",
                    session_id=f"session-{i}",
                )

        engine = SkillProposalEngine(db_path=temp_db, state_path=state_path)
        # Should complete without error, even if no proposals generated
        # (patterns need daily_burst or sustained_pattern triggers)
        proposals = engine.evaluate_patterns()
        assert isinstance(proposals, list)

    def test_decay_scorer_100_skills_under_5_seconds(self, temp_db):
        """Decay scoring 100 skills should complete in under 5 seconds."""
        db = IntelligenceDB(temp_db)
        now = datetime.now(timezone.utc)

        # Insert 100 skills with varying use_counts and last_used dates
        for i in range(100):
            days_ago = i % 30
            last_used = (now - timedelta(days=days_ago)).isoformat()
            db.conn.execute(
                "INSERT INTO skill_registry "
                "(skill_name, skill_path, description, keywords, first_seen, "
                "use_count, last_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"perf-skill-{i:03d}",
                    f"/fake/{i}",
                    f"Skill {i}",
                    "[]",
                    (now - timedelta(days=60)).isoformat(),
                    i + 1,
                    last_used,
                ),
            )
        db.conn.commit()
        db.close()

        scorer = SkillDecayScorer(db_path=temp_db)

        start = time.monotonic()
        results = scorer.compute_all_decay_scores()
        elapsed = time.monotonic() - start

        assert len(results) == 100
        assert elapsed < 5.0, f"Decay scoring took {elapsed:.2f}s — exceeds 5s budget"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Boundary conditions
# ═══════════════════════════════════════════════════════════════════════════


class TestBoundaryConditions:
    """Tests for exact boundary values and edge arithmetic."""

    def test_use_count_zero_decay(self, temp_db):
        """Skill with use_count=0: decay formula uses max(1, 0)=1, no division error."""
        db = IntelligenceDB(temp_db)
        # Use naive datetimes (no tz) to match how the codebase stores dates
        # via datetime.now().isoformat() in record_skill_usage.
        now = datetime.now()
        db.conn.execute(
            "INSERT INTO skill_registry "
            "(skill_name, skill_path, description, keywords, first_seen, "
            "use_count, last_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "zero-use-skill",
                "/fake",
                "Never used",
                "[]",
                (now - timedelta(days=60)).isoformat(),
                0,
                (now - timedelta(seconds=10)).isoformat(),  # slightly in the past
            ),
        )
        db.conn.commit()
        db.close()

        scorer = SkillDecayScorer(db_path=temp_db)
        score = scorer.compute_decay("zero-use-skill")

        # Should produce a valid float, not crash
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

        # Verify the adjusted_half_life formula directly
        hl = SkillDecayScorer.adjusted_half_life(0)
        assert hl == 30.0 * (1.0 + 0.0)  # log2(max(1, 0)) = log2(1) = 0

    def test_use_count_very_high_no_overflow(self, temp_db):
        """Skill with use_count=999999: half-life calculation should not overflow."""
        db = IntelligenceDB(temp_db)
        now = datetime.now(timezone.utc)
        db.conn.execute(
            "INSERT INTO skill_registry "
            "(skill_name, skill_path, description, keywords, first_seen, "
            "use_count, last_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "mega-skill",
                "/fake",
                "Used a million times",
                "[]",
                (now - timedelta(days=365)).isoformat(),
                999999,
                (now - timedelta(days=30)).isoformat(),
            ),
        )
        db.conn.commit()
        db.close()

        scorer = SkillDecayScorer(db_path=temp_db)
        score = scorer.compute_decay("mega-skill")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

        # Verify the half-life is very large but finite
        import math
        hl = SkillDecayScorer.adjusted_half_life(999999)
        assert math.isfinite(hl)
        assert hl > 30.0  # Must be larger than base half-life

    def test_daily_burst_exactly_at_threshold(self, temp_db, tmp_path):
        """Action pattern with exactly 3 occurrences on day 1 — daily burst fires."""
        state_path = tmp_path / "state.json"

        tracker = SkillActionTracker(state_path=state_path, db_path=temp_db)

        # Record exactly DAILY_BURST_THRESHOLD (3) occurrences in one day
        for i in range(3):
            tracker.record_action(
                "threshold exact action",
                session_id=f"sess-{i}",
            )

        engine = SkillProposalEngine(db_path=temp_db, state_path=state_path)
        proposals = engine.evaluate_patterns()

        # Should trigger daily_burst (3 >= DAILY_BURST_THRESHOLD)
        assert len(proposals) == 1
        assert proposals[0].trigger_reason == "daily_burst"
        assert proposals[0].confidence == 0.6

    def test_proposal_and_flag_coexist(self, temp_db, tmp_path):
        """A skill that is both flagged for review AND has a proposal — both coexist."""
        state_path = tmp_path / "state.json"
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "flaggable-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Flaggable skill\n\nA skill to flag.\n\n## Triggers\n- flag-test\n"
        )

        mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=state_path,
            skills_dir=skills_dir,
        )

        # Sync so the skill exists in registry
        mgr.scanner.sync_to_db()

        # Backdate the skill so it can be flagged
        db = IntelligenceDB(temp_db)
        old_date = (datetime.now() - timedelta(days=180)).isoformat()
        db.conn.execute(
            "UPDATE skill_registry SET first_seen = ?, last_used = ?, use_count = 1 "
            "WHERE skill_name = ?",
            (old_date, old_date, "flaggable-skill"),
        )
        db.conn.commit()

        # Flag the skill
        flagged = mgr.decay_scorer.flag_for_review(threshold=0.01)
        assert len(flagged) >= 1

        # Now create a proposal referencing a different action
        from memory_system.wild.skill_proposal_engine import SkillProposal
        proposal = SkillProposal(
            proposed_name="auto-test-proposal",
            action_signature="create some new action",
            trigger_reason="daily_burst",
            confidence=0.6,
        )
        proposal_id = mgr.proposal_engine.create_proposal(proposal)
        assert proposal_id > 0

        # Both should be visible
        summary = mgr.get_lifecycle_summary()
        assert len(summary["flagged_skills"]) >= 1
        assert summary["proposals"]["total_pending"] >= 1

        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Concurrent/race conditions
# ═══════════════════════════════════════════════════════════════════════════


class TestConcurrentRaceConditions:
    """Tests for concurrent access patterns."""

    def test_two_managers_same_db(self, temp_db, tmp_path):
        """Two SkillLifecycleManagers pointing at same DB — no deadlock.

        Each thread creates its own manager (and thus its own SQLite connection)
        because SQLite connections are thread-local by default.
        """
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "shared-skill").mkdir()
        (skills_dir / "shared-skill" / "SKILL.md").write_text(
            "# Shared skill\n\nShared.\n\n## Triggers\n- shared\n"
        )

        errors = []

        def run_mgr(label, state_subdir):
            try:
                state_path = tmp_path / state_subdir / "state.json"
                mgr = SkillLifecycleManager(
                    db_path=temp_db, state_path=state_path, skills_dir=skills_dir,
                )
                mgr.scanner.sync_to_db()
                mgr.record_skill_usage("shared-skill", session_id=f"{label}-sess")
                mgr.decay_scorer.compute_all_decay_scores()
            except Exception as exc:
                errors.append((label, exc))

        t1 = threading.Thread(target=run_mgr, args=("mgr1", "state1"))
        t2 = threading.Thread(target=run_mgr, args=("mgr2", "state2"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Errors during concurrent access: {errors}"

    def test_rapid_skill_usage_recording(self, temp_db, tmp_path):
        """record_skill_usage called rapidly for same skill — use_count correct.

        Each thread creates its own manager (own SQLite connection) since SQLite
        connections are thread-local by default. All write to the same DB file.
        """
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "rapid-skill").mkdir()
        (skills_dir / "rapid-skill" / "SKILL.md").write_text(
            "# Rapid skill\n\nRapid.\n\n## Triggers\n- rapid\n"
        )

        # Initial setup: sync the skill into the DB
        setup_mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=tmp_path / "setup-state.json",
            skills_dir=skills_dir,
        )
        setup_mgr.scanner.sync_to_db()

        num_calls = 50
        errors = []

        def record_usage(idx):
            try:
                # Each thread gets its own manager/connection
                thread_mgr = SkillLifecycleManager(
                    db_path=temp_db,
                    state_path=tmp_path / f"state-{idx}.json",
                    skills_dir=skills_dir,
                )
                thread_mgr.record_skill_usage("rapid-skill", session_id=f"sess-{idx}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=record_usage, args=(i,)) for i in range(num_calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors during rapid recording: {errors}"

        # Verify use_count matches expected (re-read from a fresh connection)
        verify_mgr = SkillLifecycleManager(
            db_path=temp_db,
            state_path=tmp_path / "verify-state.json",
            skills_dir=skills_dir,
        )
        skill = verify_mgr.scanner.get_skill("rapid-skill")
        assert skill is not None
        assert skill["use_count"] == num_calls

    def test_daily_maintenance_twice_no_duplicate_proposals(self, temp_db, tmp_path):
        """run_daily_maintenance called twice — second run should not create duplicates."""
        state_path = tmp_path / "state.json"
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        mgr = SkillLifecycleManager(
            db_path=temp_db, state_path=state_path, skills_dir=skills_dir,
        )

        # Create a pattern that will trigger a proposal (daily burst: 3+ in one day)
        for i in range(4):
            mgr.tracker.record_action(
                "repeated maintenance action",
                session_id=f"maint-{i}",
            )

        # First run
        result1 = mgr.run_daily_maintenance()
        proposals_after_first = len(result1["new_proposals"])

        # Second run — should NOT create duplicate proposals
        result2 = mgr.run_daily_maintenance()
        proposals_after_second = len(result2["new_proposals"])

        assert proposals_after_second == 0, (
            f"Second maintenance run created {proposals_after_second} proposals "
            f"(expected 0, first run created {proposals_after_first})"
        )

        # Total pending should equal what the first run created
        all_pending = mgr.get_proposals(status="pending")
        assert len(all_pending) == proposals_after_first
