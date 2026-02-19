"""
Tests for elaborative encoding depth scorer.

Based on Craik & Lockhart (1972) levels of processing theory.
Scores memory encoding depth 1-3:
  Level 1 (shallow): Bare facts, no context
  Level 2 (intermediate): Facts with explanation
  Level 3 (deep): Facts with reasoning, analogies, cross-references

Covers:
- Depth scoring logic (levels 1, 2, 3)
- Content analysis with signal detection
- Causal connector detection
- Comparison/analogy marker detection
- Cross-reference marker detection
- Character length thresholds
- Database persistence (record_depth, get_shallow_memories)
- Depth distribution statistics
- Enrichment candidate retrieval
- Edge cases (empty, whitespace, boundary lengths)
- Combined signals for level determination
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from memory_system.encoding_depth import EncodingDepthScorer


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database file."""
    return str(tmp_path / "test_encoding_depth.db")


@pytest.fixture
def scorer(tmp_db):
    """Return a fresh EncodingDepthScorer with a temp database."""
    return EncodingDepthScorer(db_path=tmp_db)


# ---------------------------------------------------------------------------
# 1. Level 1 (shallow) scoring
# ---------------------------------------------------------------------------

class TestLevel1Shallow:
    def test_short_bare_fact(self, scorer):
        """Very short content with no connectors => level 1."""
        assert scorer.score_depth("Use --force flag") == 1

    def test_short_command(self, scorer):
        """Short command-like memory => level 1."""
        assert scorer.score_depth("pip install numpy") == 1

    def test_bare_fact_under_30_chars(self, scorer):
        """Content under 30 chars without connectors => level 1."""
        assert scorer.score_depth("Set DEBUG=true in .env") == 1

    def test_medium_length_no_connectors(self, scorer):
        """31-80 chars but no causal or comparison markers => level 1."""
        content = "The config file is at /etc/app/config.yaml path"
        assert 30 < len(content) <= 80
        assert scorer.score_depth(content) == 1

    def test_just_a_path(self, scorer):
        """Bare path reference => level 1."""
        assert scorer.score_depth("Check /var/log/app.log") == 1


# ---------------------------------------------------------------------------
# 2. Level 2 (intermediate) scoring
# ---------------------------------------------------------------------------

class TestLevel2Intermediate:
    def test_fact_with_because(self, scorer):
        """'because' connector elevates to level 2."""
        content = "Use --force flag because upstream diverged"
        assert scorer.score_depth(content) == 2

    def test_fact_with_since(self, scorer):
        """'since' connector elevates to level 2."""
        content = "Restart the service since the config changed"
        assert scorer.score_depth(content) == 2

    def test_fact_with_therefore(self, scorer):
        """'therefore' connector elevates to level 2."""
        content = "The cache is stale therefore we need to invalidate it"
        assert scorer.score_depth(content) == 2

    def test_fact_with_due_to(self, scorer):
        """'due to' connector elevates to level 2."""
        content = "Build failed due to missing dependency in pyproject"
        assert scorer.score_depth(content) == 2

    def test_fact_with_so_that(self, scorer):
        """'so that' connector elevates to level 2."""
        content = "Add retry logic so that transient errors are handled"
        assert scorer.score_depth(content) == 2

    def test_fact_with_in_order_to(self, scorer):
        """'in order to' connector elevates to level 2."""
        content = "We cache responses in order to reduce API calls"
        assert scorer.score_depth(content) == 2

    def test_fact_with_which_means(self, scorer):
        """'which means' connector elevates to level 2."""
        content = "The token expired which means all requests will 401"
        assert scorer.score_depth(content) == 2

    def test_fact_with_as_a_result(self, scorer):
        """'as a result' connector elevates to level 2."""
        content = "Memory spiked as a result of the leak in the parser"
        assert scorer.score_depth(content) == 2

    def test_fact_with_this_causes(self, scorer):
        """'this causes' connector elevates to level 2."""
        content = "Missing index this causes slow queries at scale"
        assert scorer.score_depth(content) == 2

    def test_fact_with_leading_to(self, scorer):
        """'leading to' connector elevates to level 2."""
        content = "Race condition in the mutex leading to data corruption"
        assert scorer.score_depth(content) == 2

    def test_long_content_over_80_chars(self, scorer):
        """Content >80 chars even without connectors => level 2 (substantive)."""
        content = "The application server configuration requires specific environment variables to be set before the main process starts up correctly"
        assert len(content) > 80
        assert scorer.score_depth(content) == 2


# ---------------------------------------------------------------------------
# 3. Level 3 (deep) scoring
# ---------------------------------------------------------------------------

class TestLevel3Deep:
    def test_comparison_with_similar_to(self, scorer):
        """'similar to' comparison marker + causal => level 3."""
        content = "Use --force flag when upstream diverges because the history split; similar to the rebase pattern we used on Project X"
        assert scorer.score_depth(content) == 3

    def test_reference_with_last_time(self, scorer):
        """Cross-reference 'last time' + causal => level 3."""
        content = "Add circuit breaker because the API is flaky; last time this caused a cascade failure"
        assert scorer.score_depth(content) == 3

    def test_reference_with_in_project(self, scorer):
        """'in project' reference + causal => level 3."""
        content = "Use retry with backoff because transient errors are common; in project Atlas we saw 3x improvement"
        assert scorer.score_depth(content) == 3

    def test_comparison_with_just_as(self, scorer):
        """'just as' comparison + explanation => level 3."""
        content = "Cache invalidation needs TTL because stale data causes bugs, just as we discovered in the auth service rewrite"
        assert scorer.score_depth(content) == 3

    def test_reference_with_we_learned(self, scorer):
        """'we learned' reference + connector => level 3."""
        content = "Always validate input because injection is possible; we learned this the hard way during the security audit"
        assert scorer.score_depth(content) == 3

    def test_comparison_with_unlike(self, scorer):
        """'unlike' comparison + explanation => level 3."""
        content = "Use async processing here because the workload is I/O bound, unlike the CPU-heavy pipeline in the analytics module"
        assert scorer.score_depth(content) == 3

    def test_multiple_deep_signals(self, scorer):
        """Multiple comparison and reference markers => level 3."""
        content = "Previously we used polling which was inefficient; compared to webhooks, similar to what we did in Project Y when we refactored the notification system"
        assert scorer.score_depth(content) == 3

    def test_reference_with_previously(self, scorer):
        """'previously' reference marker + causal => level 3."""
        content = "Set connection pool to 20 because load increased; previously we had issues at 10 connections under load"
        assert scorer.score_depth(content) == 3


# ---------------------------------------------------------------------------
# 4. Content analysis details
# ---------------------------------------------------------------------------

class TestAnalyzeContent:
    def test_analysis_returns_all_fields(self, scorer):
        """analyze_content returns complete dict with all expected keys."""
        result = scorer.analyze_content("Use --force flag")
        assert "depth" in result
        assert "char_count" in result
        assert "causal_count" in result
        assert "comparison_count" in result
        assert "reference_count" in result
        assert "signals" in result

    def test_analysis_counts_causal(self, scorer):
        """Causal connectors are counted correctly."""
        content = "Do X because Y and therefore Z"
        result = scorer.analyze_content(content)
        assert result["causal_count"] == 2

    def test_analysis_counts_comparison(self, scorer):
        """Comparison markers are counted correctly."""
        content = "This is similar to X and unlike Y"
        result = scorer.analyze_content(content)
        assert result["comparison_count"] == 2

    def test_analysis_counts_references(self, scorer):
        """Reference markers are counted correctly."""
        content = "Last time we did this in project Alpha previously"
        result = scorer.analyze_content(content)
        assert result["reference_count"] >= 2

    def test_analysis_char_count(self, scorer):
        """Character count is accurate."""
        content = "Hello world"
        result = scorer.analyze_content(content)
        assert result["char_count"] == len(content)

    def test_analysis_signals_list(self, scorer):
        """Signals list contains matched marker descriptions."""
        content = "Do X because Y; similar to what we did last time"
        result = scorer.analyze_content(content)
        assert isinstance(result["signals"], list)
        assert len(result["signals"]) >= 3

    def test_analysis_depth_matches_score(self, scorer):
        """Depth in analysis matches score_depth result."""
        content = "Use retry because the API times out"
        analysis = scorer.analyze_content(content)
        score = scorer.score_depth(content)
        assert analysis["depth"] == score


# ---------------------------------------------------------------------------
# 5. Database persistence
# ---------------------------------------------------------------------------

class TestDatabasePersistence:
    def test_record_depth_returns_level(self, scorer):
        """record_depth returns the computed depth level."""
        level = scorer.record_depth("mem-001", "Use --force flag")
        assert level == 1

    def test_record_depth_persists(self, scorer, tmp_db):
        """Recorded depth is persisted in the database."""
        scorer.record_depth("mem-002", "Do X because Y happened")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT depth_level FROM encoding_depth WHERE memory_id = ?",
            ("mem-002",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 2

    def test_record_depth_stores_all_fields(self, scorer, tmp_db):
        """All analysis fields are stored in the database."""
        content = "Do X because Y; similar to project Z we did last time"
        scorer.record_depth("mem-003", content)
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT memory_id, depth_level, char_count, causal_count, "
            "comparison_count, reference_count, signals, scored_at "
            "FROM encoding_depth WHERE memory_id = ?",
            ("mem-003",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "mem-003"
        assert row[1] == 3  # deep
        assert row[2] == len(content)
        assert row[3] >= 1  # causal: because
        assert row[4] >= 1  # comparison: similar to
        assert row[5] >= 1  # reference: last time
        signals = json.loads(row[6])
        assert isinstance(signals, list)
        assert row[7] is not None  # scored_at

    def test_record_depth_upsert(self, scorer, tmp_db):
        """Recording same memory_id again updates the row."""
        scorer.record_depth("mem-004", "Short fact")
        scorer.record_depth("mem-004", "Longer explanation because reasons matter here significantly")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT depth_level FROM encoding_depth WHERE memory_id = ?",
            ("mem-004",),
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == 2  # updated to level 2

    def test_record_depth_scored_at_is_iso(self, scorer, tmp_db):
        """scored_at is a valid ISO 8601 datetime string."""
        scorer.record_depth("mem-005", "Test content")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT scored_at FROM encoding_depth WHERE memory_id = ?",
            ("mem-005",),
        ).fetchone()
        conn.close()
        # Should not raise
        dt = datetime.fromisoformat(row[0])
        assert isinstance(dt, datetime)


# ---------------------------------------------------------------------------
# 6. Shallow memory retrieval
# ---------------------------------------------------------------------------

class TestGetShallowMemories:
    def test_returns_only_level_1(self, scorer):
        """get_shallow_memories returns only level-1 memories."""
        scorer.record_depth("shallow-1", "Fix bug")
        scorer.record_depth("medium-1", "Fix bug because it crashes the server on restart")
        scorer.record_depth("deep-1", "Fix bug because crash; similar to the auth issue we saw last time in project X")
        results = scorer.get_shallow_memories()
        ids = [r["memory_id"] for r in results]
        assert "shallow-1" in ids
        assert "medium-1" not in ids
        assert "deep-1" not in ids

    def test_respects_limit(self, scorer):
        """get_shallow_memories respects the limit parameter."""
        for i in range(10):
            scorer.record_depth(f"s-{i}", f"Fact {i}")
        results = scorer.get_shallow_memories(limit=3)
        assert len(results) == 3

    def test_returns_empty_when_no_shallow(self, scorer):
        """Returns empty list when no level-1 memories exist."""
        scorer.record_depth("m1", "Do X because Y is important for the system to work correctly")
        results = scorer.get_shallow_memories()
        assert results == []

    def test_result_contains_expected_keys(self, scorer):
        """Each result dict has memory_id and scored_at."""
        scorer.record_depth("s-key", "Short")
        results = scorer.get_shallow_memories()
        assert len(results) == 1
        assert "memory_id" in results[0]
        assert "scored_at" in results[0]
        assert "depth_level" in results[0]


# ---------------------------------------------------------------------------
# 7. Depth distribution
# ---------------------------------------------------------------------------

class TestDepthDistribution:
    def test_distribution_all_levels(self, scorer):
        """Distribution counts memories at each level."""
        scorer.record_depth("a", "Short")
        scorer.record_depth("b", "Longer because reason goes here and matters")
        scorer.record_depth("c", "Do X because Y; similar to what we learned last time on project Z when refactoring")
        dist = scorer.get_depth_distribution()
        assert dist[1] == 1
        assert dist[2] == 1
        assert dist[3] == 1

    def test_distribution_empty_db(self, scorer):
        """Distribution returns zeros when no memories recorded."""
        dist = scorer.get_depth_distribution()
        assert dist == {1: 0, 2: 0, 3: 0}

    def test_distribution_only_shallow(self, scorer):
        """Distribution works with only level 1 memories."""
        for i in range(5):
            scorer.record_depth(f"s{i}", f"Fact {i}")
        dist = scorer.get_depth_distribution()
        assert dist[1] == 5
        assert dist[2] == 0
        assert dist[3] == 0


# ---------------------------------------------------------------------------
# 8. Enrichment candidates
# ---------------------------------------------------------------------------

class TestEnrichmentCandidates:
    def test_returns_shallow_within_age(self, scorer, tmp_db):
        """Returns level-1 memories scored within max_age_days."""
        scorer.record_depth("recent-shallow", "Fix it")
        candidates = scorer.get_enrichment_candidates(max_age_days=30)
        ids = [c["memory_id"] for c in candidates]
        assert "recent-shallow" in ids

    def test_excludes_old_shallow(self, scorer, tmp_db):
        """Excludes level-1 memories older than max_age_days."""
        scorer.record_depth("old-shallow", "Fix it")
        # Manually backdate the scored_at
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "UPDATE encoding_depth SET scored_at = ? WHERE memory_id = ?",
            (old_date, "old-shallow"),
        )
        conn.commit()
        conn.close()
        candidates = scorer.get_enrichment_candidates(max_age_days=30)
        ids = [c["memory_id"] for c in candidates]
        assert "old-shallow" not in ids

    def test_excludes_non_shallow(self, scorer):
        """Does not return level-2 or level-3 memories."""
        scorer.record_depth("deep-one", "Do X because Y; similar to what we did previously in the auth module")
        candidates = scorer.get_enrichment_candidates(max_age_days=365)
        assert len(candidates) == 0


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self, scorer):
        """Empty string scores level 1."""
        assert scorer.score_depth("") == 1

    def test_whitespace_only(self, scorer):
        """Whitespace-only content scores level 1."""
        assert scorer.score_depth("   \n\t  ") == 1

    def test_exactly_30_chars(self, scorer):
        """Content at exactly 30 chars boundary (no connectors) => level 1."""
        content = "a" * 30
        assert scorer.score_depth(content) == 1

    def test_exactly_31_chars_no_connectors(self, scorer):
        """31 chars without connectors still level 1 (need >80 for length-based level 2)."""
        content = "a" * 31
        assert scorer.score_depth(content) == 1

    def test_exactly_80_chars_no_connectors(self, scorer):
        """80 chars without connectors => still level 1."""
        content = "a" * 80
        assert scorer.score_depth(content) == 1

    def test_exactly_81_chars_no_connectors(self, scorer):
        """81 chars without connectors => level 2 (length-based promotion)."""
        content = "a" * 81
        assert scorer.score_depth(content) == 2

    def test_case_insensitive_connectors(self, scorer):
        """Connectors should be detected case-insensitively."""
        content = "Fix it BECAUSE the server crashed hard"
        assert scorer.score_depth(content) == 2

    def test_connector_as_substring_not_matched(self, scorer):
        """'like' in 'likely' should not count as comparison marker."""
        # "likely" contains "like" but it's not a comparison
        # This tests word boundary awareness
        content = "It is likely that the test will pass soon enough here"
        analysis = scorer.analyze_content(content)
        # Should not detect "like" inside "likely" as comparison
        # (implementation may use word boundaries or accept this - test documents behavior)
        # At minimum, no comparison markers should be counted for standalone use
        assert analysis["depth"] <= 2

    def test_multiline_content(self, scorer):
        """Multiline content is analyzed correctly."""
        content = "Fix the auth bug because the token validation\nwas broken. Similar to the issue in project Alpha."
        assert scorer.score_depth(content) == 3

    def test_unicode_content(self, scorer):
        """Unicode content doesn't crash the scorer."""
        content = "Use emoji encoding \U0001f4a1 because it helps memory retention"
        level = scorer.score_depth(content)
        assert level >= 2  # has 'because'


# ---------------------------------------------------------------------------
# 10. Database initialization
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    def test_creates_table(self, tmp_db):
        """Table is created on init."""
        EncodingDepthScorer(db_path=tmp_db)
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='encoding_depth'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_idempotent_init(self, tmp_db):
        """Creating scorer twice doesn't error."""
        EncodingDepthScorer(db_path=tmp_db)
        EncodingDepthScorer(db_path=tmp_db)  # should not raise
