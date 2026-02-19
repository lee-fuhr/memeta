"""
Tests for Frustration Archaeology feature.

Tests the FrustrationArchaeologist which analyzes historical frustration
events to surface recurring patterns and generate actionable reports.
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from memory_system.wild.frustration_archaeology import (
    FrustrationArchaeologist,
    FrustrationPattern,
    STOPWORDS,
)


# === Fixtures ===


@pytest.fixture
def db_path():
    """Create a temp database with frustration tables."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS frustration_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            severity REAL NOT NULL,
            evidence TEXT NOT NULL,
            intervention TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS frustration_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            combined_score REAL NOT NULL,
            peak_time TEXT NOT NULL,
            intervention_suggested INTEGER NOT NULL,
            intervention_text TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def archaeologist(db_path):
    """Create an archaeologist with temp database."""
    return FrustrationArchaeologist(db_path=db_path)


def _insert_event(db_path, session_id, combined_score, peak_time, intervention_text=None):
    """Helper: insert a frustration event."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO frustration_events
        (session_id, combined_score, peak_time, intervention_suggested, intervention_text)
        VALUES (?, ?, ?, 1, ?)
    """, (session_id, combined_score, peak_time.isoformat(), intervention_text))
    conn.commit()
    conn.close()


def _insert_signal(db_path, session_id, signal_type, severity, evidence, timestamp=None):
    """Helper: insert a frustration signal."""
    if timestamp is None:
        timestamp = datetime.now()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO frustration_signals
        (session_id, signal_type, severity, evidence, intervention, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, signal_type, severity, evidence,
          f"Intervention for {signal_type}", timestamp.isoformat()))
    conn.commit()
    conn.close()


# === Tests ===


class TestAnalyzeEmptyDB:
    """Tests for analyze() on empty database."""

    def test_empty_db_returns_empty_list(self, archaeologist):
        """analyze() on empty DB returns empty list."""
        result = archaeologist.analyze(days=90)
        assert result == []

    def test_empty_db_returns_list_type(self, archaeologist):
        """analyze() always returns a list."""
        result = archaeologist.analyze(days=90)
        assert isinstance(result, list)


class TestAnalyzeSingleEvent:
    """Tests for analyze() with a single event."""

    def test_single_event_returns_one_pattern(self, archaeologist, db_path):
        """analyze() on single event returns 1 pattern."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        patterns = archaeologist.analyze(days=90)
        assert len(patterns) == 1

    def test_single_event_pattern_has_correct_count(self, archaeologist, db_path):
        """Pattern has correct event_count for single event."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.75, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        patterns = archaeologist.analyze(days=90)
        assert patterns[0].event_count == 1

    def test_single_event_pattern_has_correct_severity(self, archaeologist, db_path):
        """Pattern has correct avg_severity matching the single event's combined_score."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.85, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        patterns = archaeologist.analyze(days=90)
        assert patterns[0].avg_severity == 0.85


class TestAnalyzeGrouping:
    """Tests for grouping events by signal type and evidence."""

    def test_groups_by_signal_type(self, archaeologist, db_path):
        """analyze() groups events by signal_type."""
        now = datetime.now()

        # Two events with different signal types
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        _insert_event(db_path, 'sess-002', 0.7, now - timedelta(hours=1))
        _insert_signal(db_path, 'sess-002', 'topic_cycling', 0.8,
                       "Returned to 'deploy' 4x over 90 min", now - timedelta(hours=1))

        patterns = archaeologist.analyze(days=90)
        signal_types = {p.signal_type for p in patterns}
        assert 'repeated_correction' in signal_types
        assert 'topic_cycling' in signal_types

    def test_mixed_signal_types_produce_multiple_patterns(self, archaeologist, db_path):
        """Mixed signal types produce at least 2 patterns."""
        now = datetime.now()

        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x", now)

        _insert_event(db_path, 'sess-002', 0.7, now)
        _insert_signal(db_path, 'sess-002', 'negative_sentiment', 0.8,
                       "Found 3 frustration indicators", now)

        _insert_event(db_path, 'sess-003', 0.75, now)
        _insert_signal(db_path, 'sess-003', 'high_velocity', 0.85,
                       "7 corrections in 15 min", now)

        patterns = archaeologist.analyze(days=90)
        assert len(patterns) >= 3

    def test_subclusters_by_evidence_similar(self, archaeologist, db_path):
        """Events with similar evidence cluster together."""
        now = datetime.now()

        # Two events with very similar evidence (about hooks)
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook configuration' 3x in 30 min", now)

        _insert_event(db_path, 'sess-002', 0.75, now - timedelta(hours=2))
        _insert_signal(db_path, 'sess-002', 'repeated_correction', 0.85,
                       "Corrected 'hook configuration' 4x in 30 min", now - timedelta(hours=2))

        patterns = archaeologist.analyze(days=90)

        # Should cluster into 1 pattern (both about hook configuration)
        rc_patterns = [p for p in patterns if p.signal_type == 'repeated_correction']
        assert len(rc_patterns) == 1
        assert rc_patterns[0].event_count == 2

    def test_subclusters_by_evidence_dissimilar(self, archaeologist, db_path):
        """Events with dissimilar evidence stay in separate clusters."""
        now = datetime.now()

        # Two events with completely different evidence
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'webflow css styling' 3x in 30 min", now)

        _insert_event(db_path, 'sess-002', 0.75, now - timedelta(hours=2))
        _insert_signal(db_path, 'sess-002', 'repeated_correction', 0.85,
                       "Corrected 'database migration schema' 4x in 30 min", now - timedelta(hours=2))

        patterns = archaeologist.analyze(days=90)

        # Should produce 2 separate patterns (different evidence)
        rc_patterns = [p for p in patterns if p.signal_type == 'repeated_correction']
        assert len(rc_patterns) == 2


class TestDateRangeFiltering:
    """Tests for date range filtering."""

    def test_events_outside_date_range_excluded(self, archaeologist, db_path):
        """Events outside the date range are excluded from analysis."""
        now = datetime.now()

        # One event within range
        _insert_event(db_path, 'sess-recent', 0.8, now - timedelta(days=5))
        _insert_signal(db_path, 'sess-recent', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now - timedelta(days=5))

        # One event outside range (200 days ago)
        _insert_event(db_path, 'sess-old', 0.7, now - timedelta(days=200))
        _insert_signal(db_path, 'sess-old', 'repeated_correction', 0.8,
                       "Corrected 'css' 4x in 30 min", now - timedelta(days=200))

        patterns = archaeologist.analyze(days=90)

        # Only the recent event should be included
        total_events = sum(p.event_count for p in patterns)
        assert total_events == 1


class TestPatternAttributes:
    """Tests for individual pattern attribute correctness."""

    def test_pattern_recommendation_matches_signal_type(self, archaeologist, db_path):
        """Pattern recommendation comes from RECOMMENDATIONS dict for the signal type."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'topic_cycling', 0.9,
                       "Returned to 'deploy' 4x over 90 min", now)

        patterns = archaeologist.analyze(days=90)
        assert patterns[0].recommendation == FrustrationArchaeologist.RECOMMENDATIONS['topic_cycling']

    def test_pattern_date_range_covers_event_dates(self, archaeologist, db_path):
        """Pattern date_range covers the actual event peak_times."""
        now = datetime.now()
        five_days_ago = now - timedelta(days=5)
        ten_days_ago = now - timedelta(days=10)

        # Two events with same evidence, different dates
        _insert_event(db_path, 'sess-001', 0.8, five_days_ago)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook config' 3x in 30 min", five_days_ago)

        _insert_event(db_path, 'sess-002', 0.75, ten_days_ago)
        _insert_signal(db_path, 'sess-002', 'repeated_correction', 0.85,
                       "Corrected 'hook config' 4x in 30 min", ten_days_ago)

        patterns = archaeologist.analyze(days=90)
        assert len(patterns) == 1

        # Date range should contain both months' abbreviations
        date_range = patterns[0].date_range
        assert ten_days_ago.strftime("%b") in date_range or ten_days_ago.strftime("%-d") in date_range

    def test_pattern_avg_severity_is_average(self, archaeologist, db_path):
        """Pattern avg_severity is the mean of combined_scores."""
        now = datetime.now()

        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook config' 3x in 30 min", now)

        _insert_event(db_path, 'sess-002', 0.6, now - timedelta(hours=2))
        _insert_signal(db_path, 'sess-002', 'repeated_correction', 0.7,
                       "Corrected 'hook config' 4x in 30 min", now - timedelta(hours=2))

        patterns = archaeologist.analyze(days=90)
        assert len(patterns) == 1
        assert patterns[0].avg_severity == 0.7  # (0.8 + 0.6) / 2

    def test_pattern_event_ids_populated(self, archaeologist, db_path):
        """Pattern event_ids contains string IDs of all events in cluster."""
        now = datetime.now()

        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'negative_sentiment', 0.9,
                       "Found 3 frustration indicators", now)

        patterns = archaeologist.analyze(days=90)
        assert len(patterns[0].event_ids) == 1
        assert isinstance(patterns[0].event_ids[0], str)


class TestSortOrder:
    """Tests for result ordering."""

    def test_most_common_pattern_first(self, archaeologist, db_path):
        """Patterns sorted by event_count descending - most common first."""
        now = datetime.now()

        # 1 event for negative_sentiment
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'negative_sentiment', 0.9,
                       "Found 3 frustration indicators in message", now)

        # 3 events for repeated_correction (same evidence to cluster together)
        for i in range(3):
            session_id = f'sess-rc-{i}'
            t = now - timedelta(hours=i)
            _insert_event(db_path, session_id, 0.75, t)
            _insert_signal(db_path, session_id, 'repeated_correction', 0.85,
                           "Corrected 'hook config' 3x in 30 min", t)

        patterns = archaeologist.analyze(days=90)
        assert len(patterns) >= 2

        # First pattern should have the highest event_count
        assert patterns[0].event_count >= patterns[-1].event_count


class TestGenerateReport:
    """Tests for report generation."""

    def test_report_produces_valid_markdown(self, archaeologist, db_path):
        """generate_report() produces valid markdown with header."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        patterns = archaeologist.analyze(days=90)
        report = archaeologist.generate_report(patterns)

        assert report.startswith("# Frustration archaeology")
        assert "## Pattern 1:" in report

    def test_report_includes_all_patterns(self, archaeologist, db_path):
        """generate_report() includes all patterns in the list."""
        now = datetime.now()

        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'repeated_correction', 0.9,
                       "Corrected 'hook' 3x in 30 min", now)

        _insert_event(db_path, 'sess-002', 0.7, now)
        _insert_signal(db_path, 'sess-002', 'topic_cycling', 0.8,
                       "Returned to 'deploy' 4x over 90 min", now)

        patterns = archaeologist.analyze(days=90)
        report = archaeologist.generate_report(patterns)

        assert "## Pattern 1:" in report
        assert "## Pattern 2:" in report

    def test_report_empty_patterns_returns_header_only(self, archaeologist):
        """generate_report() on empty patterns returns header with no-data message."""
        report = archaeologist.generate_report([])

        assert report.startswith("# Frustration archaeology")
        assert "No frustration patterns detected" in report
        assert "## Pattern" not in report

    def test_report_contains_severity(self, archaeologist, db_path):
        """Report includes severity formatted to 1 decimal place."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.853, now)
        _insert_signal(db_path, 'sess-001', 'high_velocity', 0.9,
                       "7 corrections in 15 min", now)

        patterns = archaeologist.analyze(days=90)
        report = archaeologist.generate_report(patterns)

        assert "0.9/1.0" in report

    def test_report_contains_recommendation(self, archaeologist, db_path):
        """Report includes the recommendation text."""
        now = datetime.now()
        _insert_event(db_path, 'sess-001', 0.8, now)
        _insert_signal(db_path, 'sess-001', 'high_velocity', 0.9,
                       "7 corrections in 15 min", now)

        patterns = archaeologist.analyze(days=90)
        report = archaeologist.generate_report(patterns)

        assert "Recommendation" in report
        assert "reference document" in report


class TestKeywordExtraction:
    """Tests for internal keyword extraction."""

    def test_extract_keywords_removes_stopwords(self, archaeologist):
        """_extract_keywords removes common stopwords."""
        keywords = archaeologist._extract_keywords("the hook is broken and not working")
        assert 'the' not in keywords
        assert 'and' not in keywords
        assert 'hook' in keywords
        assert 'broken' in keywords

    def test_extract_keywords_empty_string(self, archaeologist):
        """_extract_keywords on empty string returns empty set."""
        keywords = archaeologist._extract_keywords("")
        assert keywords == set()

    def test_extract_keywords_short_words_removed(self, archaeologist):
        """_extract_keywords removes words shorter than 3 characters."""
        keywords = archaeologist._extract_keywords("go to db in vm")
        assert 'go' not in keywords
        assert 'to' not in keywords
        assert 'db' not in keywords
        assert 'in' not in keywords
        assert 'vm' not in keywords
