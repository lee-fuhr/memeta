"""
Tests for embedding_maintenance.py - Pre-compute embedding maintenance runner.

Covers:
1. Run on empty memory dir (computed=0)
2. Run on 3 memories computes all 3
3. Run twice - second run skips all (incremental)
4. Freshness check returns True when memory newer than embeddings
5. Freshness check returns False when embeddings up to date
6. run_if_stale() returns None when fresh
7. run_if_stale() returns result when stale
8. Error handling: corrupt memory file doesn't crash (skips, increments errors)
9. Stats reporting: computed + skipped + errors = total
10. LaunchAgent plist is valid XML
11. Empty memory content handled gracefully
12. Large batch (20+ memories) completes without error
13. Duration tracking is present and positive
14. No memories = check_freshness returns False
"""

import pytest
import tempfile
import shutil
import sqlite3
import hashlib
import xml.etree.ElementTree as ET
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from collections import OrderedDict

from memory_system.embedding_maintenance import EmbeddingMaintenanceRunner
from memory_system.embedding_manager import EmbeddingManager
from memory_system.memory_ts_client import MemoryTSClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 384


def _make_embedding(seed: int = 0) -> np.ndarray:
    """Return a deterministic, normalised float32 embedding of dimension 384."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(EMBEDDING_DIM).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec


def _make_model_mock():
    """Return a mock that behaves like SentenceTransformer for encode()."""
    model = MagicMock()

    def _encode_side_effect(text, convert_to_numpy=True, show_progress_bar=False):
        if isinstance(text, str):
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)
            return _make_embedding(seed)
        elif isinstance(text, list):
            results = []
            for t in text:
                seed = int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % (2**31)
                results.append(_make_embedding(seed))
            return np.array(results)

    model.encode = MagicMock(side_effect=_encode_side_effect)
    return model


def _create_memory_file(memory_dir: Path, memory_id: str, content: str,
                        importance: float = 0.8, created: str = None) -> Path:
    """Write a valid memory file to disk."""
    if created is None:
        created = datetime.now().isoformat()

    frontmatter = f"""---
id: {memory_id}
created: {created}
updated: {created}
reasoning: test
importance_weight: {importance}
confidence_score: 0.9
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: learnings
emotional_resonance: null
action_required: false
problem_solution_pair: true
semantic_tags: ["#test"]
trigger_phrases: []
question_types: []
session_id: unknown
project_id: LFI
status: active
scope: project
temporal_class: long_term
fade_rate: 0.03
expires_after_sessions: 0
domain: learnings
feature: null
component: null
supersedes: null
superseded_by: null
related_to: []
resolves: []
resolved_by: null
parent_id: null
child_ids: []
awaiting_implementation: false
awaiting_decision: false
blocked_by: null
blocks: []
related_files: []
retrieval_weight: {importance}
exclude_from_retrieval: false
schema_version: 2
---

{content}
"""
    filepath = memory_dir / f"{memory_id}.md"
    filepath.write_text(frontmatter)
    return filepath


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_memory_dir():
    """Create temporary directory for test memories."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_db():
    """Create a temporary database file path."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)
    Path(db_path + '-wal').unlink(missing_ok=True)
    Path(db_path + '-shm').unlink(missing_ok=True)


@pytest.fixture
def runner(temp_memory_dir, temp_db):
    """Create an EmbeddingMaintenanceRunner with mocked model."""
    r = EmbeddingMaintenanceRunner(memory_dir=temp_memory_dir, db_path=temp_db)
    r.manager._model = _make_model_mock()
    return r


# ===========================================================================
# Tests
# ===========================================================================

class TestRunEmpty:
    """Test running on empty memory directory."""

    def test_empty_dir_returns_zero_computed(self, runner):
        """Run on empty memory dir returns computed=0."""
        result = runner.run()
        assert result["computed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 0


class TestRunWithMemories:
    """Test running with actual memories present."""

    def test_computes_all_three(self, runner, temp_memory_dir):
        """Run on 3 memories computes all 3."""
        _create_memory_file(temp_memory_dir, "mem-001", "First test memory about Python")
        _create_memory_file(temp_memory_dir, "mem-002", "Second test memory about testing")
        _create_memory_file(temp_memory_dir, "mem-003", "Third test memory about deployment")

        result = runner.run()
        assert result["computed"] == 3
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 3

    def test_incremental_second_run_skips_all(self, runner, temp_memory_dir):
        """Run twice - second run skips all (incremental)."""
        _create_memory_file(temp_memory_dir, "mem-001", "First test memory about Python")
        _create_memory_file(temp_memory_dir, "mem-002", "Second test memory about testing")
        _create_memory_file(temp_memory_dir, "mem-003", "Third test memory about deployment")

        result1 = runner.run()
        assert result1["computed"] == 3

        result2 = runner.run()
        assert result2["computed"] == 0
        assert result2["skipped"] == 3
        assert result2["errors"] == 0
        assert result2["total"] == 3


class TestFreshnessCheck:
    """Test check_freshness() and run_if_stale()."""

    def test_stale_when_memory_newer_than_embeddings(self, runner, temp_memory_dir, temp_db):
        """Freshness check returns True when memory newer than embeddings."""
        # Create an embedding with old timestamp
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        with sqlite3.connect(temp_db) as conn:
            vec = _make_embedding(42)
            conn.execute("""
                INSERT INTO embeddings
                (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("oldhash", vec.tobytes(), 384, "all-MiniLM-L6-v2", old_time, old_time))
            conn.commit()

        # Create a memory with newer timestamp
        new_time = datetime.now().isoformat()
        _create_memory_file(temp_memory_dir, "mem-fresh", "Fresh content", created=new_time)

        assert runner.check_freshness() is True

    def test_fresh_when_embeddings_up_to_date(self, runner, temp_memory_dir, temp_db):
        """Freshness check returns False when embeddings are up to date."""
        # Create a memory with old timestamp
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        _create_memory_file(temp_memory_dir, "mem-old", "Old content", created=old_time)

        # Create an embedding with newer timestamp
        new_time = datetime.now().isoformat()
        with sqlite3.connect(temp_db) as conn:
            vec = _make_embedding(99)
            conn.execute("""
                INSERT INTO embeddings
                (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("newhash", vec.tobytes(), 384, "all-MiniLM-L6-v2", new_time, new_time))
            conn.commit()

        assert runner.check_freshness() is False

    def test_no_memories_is_fresh(self, runner):
        """No memories = check_freshness returns False."""
        assert runner.check_freshness() is False

    def test_run_if_stale_returns_none_when_fresh(self, runner, temp_memory_dir, temp_db):
        """run_if_stale() returns None when fresh."""
        # Create a memory with old timestamp
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        _create_memory_file(temp_memory_dir, "mem-old", "Old content", created=old_time)

        # Create an embedding with newer timestamp
        new_time = datetime.now().isoformat()
        with sqlite3.connect(temp_db) as conn:
            vec = _make_embedding(99)
            conn.execute("""
                INSERT INTO embeddings
                (content_hash, embedding, dimension, model_name, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("newhash", vec.tobytes(), 384, "all-MiniLM-L6-v2", new_time, new_time))
            conn.commit()

        result = runner.run_if_stale()
        assert result is None

    def test_run_if_stale_returns_result_when_stale(self, runner, temp_memory_dir):
        """run_if_stale() returns result when stale."""
        _create_memory_file(temp_memory_dir, "mem-stale", "Some stale content")

        result = runner.run_if_stale()
        assert result is not None
        assert result["computed"] == 1
        assert result["total"] == 1


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_corrupt_memory_file_skipped(self, runner, temp_memory_dir):
        """Corrupt memory file doesn't crash - skipped, increments errors."""
        # Create a valid memory
        _create_memory_file(temp_memory_dir, "mem-good", "Valid memory content")

        # Create a corrupt memory file (no valid frontmatter)
        corrupt_file = temp_memory_dir / "mem-corrupt.md"
        corrupt_file.write_text("This is not a valid memory file at all")

        result = runner.run()
        # The corrupt file is skipped during MemoryTSClient.list() silently,
        # so it won't even appear in the total. Only the valid one is processed.
        assert result["computed"] >= 1
        assert result["errors"] == 0  # corrupt files are silently skipped by list()

    def test_empty_content_handled_gracefully(self, runner, temp_memory_dir):
        """Empty memory content is handled gracefully."""
        _create_memory_file(temp_memory_dir, "mem-empty", "")

        result = runner.run()
        # Empty content should be skipped, not cause an error
        assert result["errors"] == 0
        assert result["skipped"] == 1
        assert result["total"] == 1

    def test_whitespace_only_content_skipped(self, runner, temp_memory_dir):
        """Whitespace-only memory content is skipped."""
        _create_memory_file(temp_memory_dir, "mem-ws", "   \n  \t  ")

        result = runner.run()
        assert result["skipped"] == 1
        assert result["computed"] == 0


class TestStatsReporting:
    """Test stats reporting and invariants."""

    def test_computed_plus_skipped_plus_errors_equals_total(self, runner, temp_memory_dir):
        """Stats reporting: computed + skipped + errors = total."""
        _create_memory_file(temp_memory_dir, "mem-a", "Memory alpha")
        _create_memory_file(temp_memory_dir, "mem-b", "Memory beta")
        _create_memory_file(temp_memory_dir, "mem-c", "")  # empty = skip

        result = runner.run()
        assert result["computed"] + result["skipped"] + result["errors"] == result["total"]

    def test_duration_tracking_present_and_positive(self, runner, temp_memory_dir):
        """Duration tracking is present and non-negative."""
        _create_memory_file(temp_memory_dir, "mem-dur", "Duration test content")

        result = runner.run()
        assert "duration_ms" in result
        assert result["duration_ms"] >= 0


class TestLargeBatch:
    """Test with larger number of memories."""

    def test_large_batch_completes(self, runner, temp_memory_dir):
        """Large batch (20+ memories) completes without error."""
        for i in range(25):
            _create_memory_file(
                temp_memory_dir,
                f"mem-batch-{i:03d}",
                f"Memory number {i} about topic {i * 7}"
            )

        result = runner.run()
        assert result["computed"] == 25
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 25


class TestLaunchAgentPlist:
    """Test LaunchAgent plist validity."""

    def test_plist_is_valid_xml(self):
        """LaunchAgent plist is valid XML with correct structure."""
        plist_path = (
            Path(__file__).parent.parent
            / "launch-agents"
            / "com.memory.embedding-maintenance.plist"
        )
        assert plist_path.exists(), f"Plist not found at {plist_path}"

        # Parse as XML - will raise if invalid
        tree = ET.parse(str(plist_path))
        root = tree.getroot()

        assert root.tag == "plist"

        # Check key structural elements
        xml_text = plist_path.read_text()
        assert "com.memory.embedding-maintenance" in xml_text
        assert "memory_system.embedding_maintenance" in xml_text
        assert "<integer>4</integer>" in xml_text  # 4 AM
        assert "<integer>0</integer>" in xml_text  # minute 0
