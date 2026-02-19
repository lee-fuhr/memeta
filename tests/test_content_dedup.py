"""
Tests for the content hash deduplication module.

Covers:
- Exact hash computation (SHA-256 of raw content)
- Normalized hash computation (lowercase, strip punctuation, collapse whitespace)
- Semantic hash computation (quantized embedding buckets)
- Duplicate checking at all three levels
- Memory registration and lookup
- Duplicate group detection
- Dedup statistics tracking
- Edge cases (empty content, None embedding, unicode, very long content)
- Dedup event logging
- Database schema initialization
"""

import sqlite3
import time

import numpy as np
import pytest

from memory_system.content_dedup import ContentDedup


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database file."""
    return str(tmp_path / "test_dedup.db")


@pytest.fixture
def dedup(tmp_db):
    """Return a fresh ContentDedup instance."""
    return ContentDedup(db_path=tmp_db)


# ---------------------------------------------------------------------------
# 1. Exact hash computation
# ---------------------------------------------------------------------------

class TestExactHash:
    def test_deterministic(self, dedup):
        h1 = dedup.compute_exact_hash("hello world")
        h2 = dedup.compute_exact_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self, dedup):
        h1 = dedup.compute_exact_hash("hello world")
        h2 = dedup.compute_exact_hash("hello worlds")
        assert h1 != h2

    def test_case_sensitive(self, dedup):
        h1 = dedup.compute_exact_hash("Hello World")
        h2 = dedup.compute_exact_hash("hello world")
        assert h1 != h2

    def test_whitespace_sensitive(self, dedup):
        h1 = dedup.compute_exact_hash("hello  world")
        h2 = dedup.compute_exact_hash("hello world")
        assert h1 != h2

    def test_returns_hex_string(self, dedup):
        h = dedup.compute_exact_hash("test")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_content(self, dedup):
        h = dedup.compute_exact_hash("")
        assert isinstance(h, str)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# 2. Normalized hash computation
# ---------------------------------------------------------------------------

class TestNormalizedHash:
    def test_case_insensitive(self, dedup):
        h1 = dedup.compute_normalized_hash("Hello World")
        h2 = dedup.compute_normalized_hash("hello world")
        assert h1 == h2

    def test_punctuation_stripped(self, dedup):
        h1 = dedup.compute_normalized_hash("Hello, World!")
        h2 = dedup.compute_normalized_hash("Hello World")
        assert h1 == h2

    def test_whitespace_collapsed(self, dedup):
        h1 = dedup.compute_normalized_hash("hello   world")
        h2 = dedup.compute_normalized_hash("hello world")
        assert h1 == h2

    def test_tabs_and_newlines_collapsed(self, dedup):
        h1 = dedup.compute_normalized_hash("hello\t\nworld")
        h2 = dedup.compute_normalized_hash("hello world")
        assert h1 == h2

    def test_combined_normalization(self, dedup):
        h1 = dedup.compute_normalized_hash("  Hello,  World!  How's it going?  ")
        h2 = dedup.compute_normalized_hash("hello world hows it going")
        assert h1 == h2

    def test_different_content_different_hash(self, dedup):
        h1 = dedup.compute_normalized_hash("hello world")
        h2 = dedup.compute_normalized_hash("goodbye world")
        assert h1 != h2

    def test_returns_hex_string(self, dedup):
        h = dedup.compute_normalized_hash("test")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_unicode_content(self, dedup):
        h = dedup.compute_normalized_hash("cafe\u0301 resume\u0301")
        assert isinstance(h, str)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# 3. Semantic hash computation
# ---------------------------------------------------------------------------

class TestSemanticHash:
    def test_deterministic(self, dedup):
        emb = [0.1, 0.5, -0.3, 0.8, 0.0]
        h1 = dedup.compute_semantic_hash(emb)
        h2 = dedup.compute_semantic_hash(emb)
        assert h1 == h2

    def test_similar_embeddings_same_hash(self, dedup):
        """Very close embeddings should quantize to the same buckets."""
        emb1 = [0.1, 0.5, -0.3, 0.8, 0.0] * 20
        emb2 = [0.1001, 0.5001, -0.2999, 0.8001, 0.0001] * 20
        h1 = dedup.compute_semantic_hash(emb1)
        h2 = dedup.compute_semantic_hash(emb2)
        assert h1 == h2

    def test_different_embeddings_different_hash(self, dedup):
        rng = np.random.RandomState(42)
        emb1 = rng.randn(128).tolist()
        emb2 = rng.randn(128).tolist()
        h1 = dedup.compute_semantic_hash(emb1)
        h2 = dedup.compute_semantic_hash(emb2)
        assert h1 != h2

    def test_returns_hex_string(self, dedup):
        emb = [0.1, 0.2, 0.3]
        h = dedup.compute_semantic_hash(emb)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_custom_n_bins(self, dedup):
        emb = [0.1, 0.5, -0.3, 0.8, 0.0] * 20
        h32 = dedup.compute_semantic_hash(emb, n_bins=32)
        h128 = dedup.compute_semantic_hash(emb, n_bins=128)
        # Different bin counts should generally produce different hashes
        # (not guaranteed but very likely with different granularity)
        assert isinstance(h32, str)
        assert isinstance(h128, str)

    def test_negative_values_handled(self, dedup):
        emb = [-1.0, -0.5, 0.0, 0.5, 1.0]
        h = dedup.compute_semantic_hash(emb)
        assert isinstance(h, str)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# 4. Memory registration
# ---------------------------------------------------------------------------

class TestRegisterMemory:
    def test_register_without_embedding(self, dedup):
        dedup.register_memory("mem-001", "Hello world")
        # Should not raise

    def test_register_with_embedding(self, dedup):
        emb = [0.1, 0.2, 0.3]
        dedup.register_memory("mem-001", "Hello world", embedding=emb)
        # Should not raise

    def test_register_stores_hashes_in_db(self, dedup, tmp_db):
        dedup.register_memory("mem-001", "Hello world")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT exact_hash, normalized_hash, semantic_hash FROM content_hashes WHERE memory_id = ?",
            ("mem-001",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # exact_hash
        assert row[1] is not None  # normalized_hash
        assert row[2] is None      # semantic_hash (no embedding)

    def test_register_with_embedding_stores_semantic_hash(self, dedup, tmp_db):
        emb = [0.1, 0.2, 0.3]
        dedup.register_memory("mem-001", "Hello world", embedding=emb)
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT semantic_hash FROM content_hashes WHERE memory_id = ?",
            ("mem-001",),
        ).fetchone()
        conn.close()
        assert row[0] is not None

    def test_register_duplicate_memory_id_replaces(self, dedup, tmp_db):
        dedup.register_memory("mem-001", "Version 1")
        dedup.register_memory("mem-001", "Version 2")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM content_hashes WHERE memory_id = ?",
            ("mem-001",),
        ).fetchone()
        conn.close()
        assert rows[0] == 1


# ---------------------------------------------------------------------------
# 5. Duplicate checking
# ---------------------------------------------------------------------------

class TestCheckDuplicate:
    def test_no_duplicate_on_empty_db(self, dedup):
        result = dedup.check_duplicate("Hello world")
        assert result["is_duplicate"] is False
        assert result["match_level"] is None
        assert result["matched_memory_id"] is None

    def test_exact_duplicate(self, dedup):
        dedup.register_memory("mem-001", "Hello world")
        result = dedup.check_duplicate("Hello world")
        assert result["is_duplicate"] is True
        assert result["match_level"] == "exact"
        assert result["matched_memory_id"] == "mem-001"
        assert result["confidence"] == 1.0

    def test_normalized_duplicate(self, dedup):
        dedup.register_memory("mem-001", "Hello, World!")
        result = dedup.check_duplicate("hello world")
        assert result["is_duplicate"] is True
        assert result["match_level"] == "normalized"
        assert result["matched_memory_id"] == "mem-001"
        assert result["confidence"] >= 0.8

    def test_semantic_duplicate(self, dedup):
        emb = [0.1, 0.5, -0.3, 0.8, 0.0] * 20
        dedup.register_memory("mem-001", "The sky is blue", embedding=emb)
        emb_similar = [0.1001, 0.5001, -0.2999, 0.8001, 0.0001] * 20
        result = dedup.check_duplicate("The sky appears blue", embedding=emb_similar)
        assert result["is_duplicate"] is True
        assert result["match_level"] == "semantic"
        assert result["matched_memory_id"] == "mem-001"
        assert result["confidence"] >= 0.5

    def test_no_semantic_check_without_embedding(self, dedup):
        emb = [0.1, 0.5, -0.3]
        dedup.register_memory("mem-001", "Original content", embedding=emb)
        # Different content, no embedding provided for check
        result = dedup.check_duplicate("Completely different text")
        assert result["is_duplicate"] is False

    def test_exact_match_takes_priority(self, dedup):
        """If content is an exact match, should return 'exact' not 'normalized'."""
        dedup.register_memory("mem-001", "Hello world")
        result = dedup.check_duplicate("Hello world")
        assert result["match_level"] == "exact"

    def test_logs_dedup_event(self, dedup, tmp_db):
        dedup.register_memory("mem-001", "Hello world")
        dedup.check_duplicate("Hello world")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT COUNT(*) FROM dedup_events").fetchone()
        conn.close()
        assert row[0] == 1

    def test_no_event_on_non_duplicate(self, dedup, tmp_db):
        dedup.register_memory("mem-001", "Hello world")
        dedup.check_duplicate("Completely different")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT COUNT(*) FROM dedup_events").fetchone()
        conn.close()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# 6. Duplicate groups
# ---------------------------------------------------------------------------

class TestDuplicateGroups:
    def test_no_groups_when_unique(self, dedup):
        dedup.register_memory("mem-001", "First content")
        dedup.register_memory("mem-002", "Second content")
        groups = dedup.get_duplicate_groups()
        assert groups == []

    def test_groups_by_normalized_hash(self, dedup):
        dedup.register_memory("mem-001", "Hello World")
        dedup.register_memory("mem-002", "hello world")
        dedup.register_memory("mem-003", "HELLO WORLD!")
        groups = dedup.get_duplicate_groups()
        assert len(groups) == 1
        assert sorted(groups[0]) == ["mem-001", "mem-002", "mem-003"]

    def test_multiple_groups(self, dedup):
        dedup.register_memory("mem-001", "Hello World")
        dedup.register_memory("mem-002", "hello world")
        dedup.register_memory("mem-003", "Goodbye World")
        dedup.register_memory("mem-004", "goodbye world!")
        groups = dedup.get_duplicate_groups()
        assert len(groups) == 2


# ---------------------------------------------------------------------------
# 7. Dedup statistics
# ---------------------------------------------------------------------------

class TestDedupStats:
    def test_empty_stats(self, dedup):
        stats = dedup.get_dedup_stats()
        assert stats["total_registered"] == 0
        assert stats["exact_dupes_found"] == 0
        assert stats["normalized_dupes_found"] == 0
        assert stats["semantic_dupes_found"] == 0

    def test_stats_after_registration(self, dedup):
        dedup.register_memory("mem-001", "Hello world")
        dedup.register_memory("mem-002", "Other content")
        stats = dedup.get_dedup_stats()
        assert stats["total_registered"] == 2

    def test_stats_count_exact_dupes(self, dedup):
        dedup.register_memory("mem-001", "Hello world")
        dedup.check_duplicate("Hello world")
        stats = dedup.get_dedup_stats()
        assert stats["exact_dupes_found"] == 1

    def test_stats_count_normalized_dupes(self, dedup):
        dedup.register_memory("mem-001", "Hello, World!")
        dedup.check_duplicate("hello world")
        stats = dedup.get_dedup_stats()
        assert stats["normalized_dupes_found"] == 1

    def test_stats_count_semantic_dupes(self, dedup):
        emb = [0.1, 0.5, -0.3, 0.8, 0.0] * 20
        dedup.register_memory("mem-001", "content", embedding=emb)
        emb_similar = [0.1001, 0.5001, -0.2999, 0.8001, 0.0001] * 20
        dedup.check_duplicate("other content", embedding=emb_similar)
        stats = dedup.get_dedup_stats()
        assert stats["semantic_dupes_found"] == 1


# ---------------------------------------------------------------------------
# 8. Database schema and persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_schema_created_on_init(self, tmp_db):
        ContentDedup(db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "content_hashes" in tables
        assert "dedup_events" in tables

    def test_data_persists_across_instances(self, tmp_db):
        d1 = ContentDedup(db_path=tmp_db)
        d1.register_memory("mem-001", "Hello world")
        d2 = ContentDedup(db_path=tmp_db)
        result = d2.check_duplicate("Hello world")
        assert result["is_duplicate"] is True
        assert result["matched_memory_id"] == "mem-001"

    def test_multiple_instances_share_data(self, tmp_db):
        d1 = ContentDedup(db_path=tmp_db)
        d1.register_memory("mem-001", "Hello world")
        d2 = ContentDedup(db_path=tmp_db)
        stats = d2.get_dedup_stats()
        assert stats["total_registered"] == 1


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_long_content(self, dedup):
        content = "word " * 100000
        h = dedup.compute_exact_hash(content)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_unicode_content_exact(self, dedup):
        h = dedup.compute_exact_hash("caf\u00e9 r\u00e9sum\u00e9 \u00fc\u00f1\u00ee\u00e7\u00f8\u00f0\u00ea")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_empty_string_registration(self, dedup):
        dedup.register_memory("mem-001", "")
        result = dedup.check_duplicate("")
        assert result["is_duplicate"] is True

    def test_single_dimension_embedding(self, dedup):
        h = dedup.compute_semantic_hash([0.5])
        assert isinstance(h, str)
        assert len(h) == 64

    def test_high_dimensional_embedding(self, dedup):
        rng = np.random.RandomState(99)
        emb = rng.randn(1536).tolist()  # OpenAI-size embedding
        h = dedup.compute_semantic_hash(emb)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_check_duplicate_returns_correct_keys(self, dedup):
        result = dedup.check_duplicate("anything")
        expected_keys = {"is_duplicate", "match_level", "matched_memory_id", "confidence"}
        assert set(result.keys()) == expected_keys
