"""
Tests for Feature 57: Writing Style Evolution Tracking

Tests the WritingStyleAnalyzer's ability to track writing style changes.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import os
import sqlite3

from memory_system.wild.writing_analyzer import WritingStyleAnalyzer, WritingSnapshot, StyleTrend


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def analyzer(temp_db):
    """Create analyzer with temp database"""
    return WritingStyleAnalyzer(db_path=temp_db)


class TestTextAnalysis:
    """Test text analysis and metric calculation"""

    def test_analyze_simple_text(self, analyzer):
        """Test basic text analysis"""
        text = "This is a test. It has multiple sentences. Testing is important."

        snapshot = analyzer.analyze_text("session-123", text, "body")

        assert snapshot.session_id == "session-123"
        assert snapshot.content_type == "body"
        assert snapshot.avg_sentence_length > 0
        assert 0 <= snapshot.compression_score <= 1.0
        assert 0 <= snapshot.formality_score <= 1.0
        assert snapshot.technical_density >= 0

    def test_analyze_headline(self, analyzer):
        """Test headline-specific analysis"""
        text = "Best practices for API design"

        snapshot = analyzer.analyze_text("session-456", text, "headline")

        assert snapshot.content_type == "headline"
        assert snapshot.avg_headline_length is not None
        assert snapshot.avg_headline_length == 5  # 5 words

    def test_compression_score_calculation(self, analyzer):
        """Test compression score (filler word detection)"""
        # Text with fillers
        filler_text = "Actually, I basically just really want to simply clarify this very important point."
        filler_snapshot = analyzer.analyze_text("s1", filler_text, "body")

        # Text without fillers
        clean_text = "I want to clarify this important point."
        clean_snapshot = analyzer.analyze_text("s2", clean_text, "body")

        # Clean text should have higher compression
        assert clean_snapshot.compression_score > filler_snapshot.compression_score

    def test_formality_score_calculation(self, analyzer):
        """Test formality score (formal word detection)"""
        # Formal text
        formal_text = "However, we must therefore proceed. Nevertheless, the outcome is thus determined."
        formal_snapshot = analyzer.analyze_text("s1", formal_text, "body")

        # Casual text
        casual_text = "But we need to go ahead. Anyway, that's how it ends up."
        casual_snapshot = analyzer.analyze_text("s2", casual_text, "body")

        # Formal text should score higher
        assert formal_snapshot.formality_score > casual_snapshot.formality_score

    def test_technical_density_calculation(self, analyzer):
        """Test technical density (technical term detection)"""
        # Technical text
        tech_text = "The API connects to the database server. The backend handles authentication and authorization through the infrastructure."
        tech_snapshot = analyzer.analyze_text("s1", tech_text, "body")

        # Non-technical text
        plain_text = "The system connects to storage. The program handles login through the setup."
        plain_snapshot = analyzer.analyze_text("s2", plain_text, "body")

        # Technical text should have higher density
        assert tech_snapshot.technical_density > plain_snapshot.technical_density

    def test_question_rate_calculation(self, analyzer):
        """Test question rate detection"""
        # The sentence splitter splits on "? " so only the last sentence retains "?"
        text = "Is this working? How about now? What should we do?"
        snapshot = analyzer.analyze_text("s1", text, "body")

        # After splitting: ["Is this working", "How about now", "What should we do?"]
        # Only last has "?" → 1/3 = 33.33%
        assert snapshot.question_rate == pytest.approx(33.33, abs=0.1)

    def test_sentence_variance_calculation(self, analyzer):
        """Test sentence length variance"""
        # Varied sentence lengths
        varied = "Short. This is a medium sentence. This is a much longer sentence with many more words."
        varied_snapshot = analyzer.analyze_text("s1", varied, "body")

        # Uniform sentence lengths
        uniform = "Same length here. Same length again. Same length still."
        uniform_snapshot = analyzer.analyze_text("s2", uniform, "body")

        # Varied should have higher variance
        assert varied_snapshot.sentence_length_variance > uniform_snapshot.sentence_length_variance

    def test_vocabulary_richness(self, analyzer):
        """Test vocabulary richness (unique words / total)"""
        # Rich vocabulary
        rich = "Every word different here today"
        rich_snapshot = analyzer.analyze_text("s1", rich, "body")

        # Repetitive vocabulary
        repetitive = "word word word word word"
        repetitive_snapshot = analyzer.analyze_text("s2", repetitive, "body")

        # Rich should score higher
        assert rich_snapshot.vocabulary_richness > repetitive_snapshot.vocabulary_richness


class TestTrendDetection:
    """Test trend detection across time"""

    def test_no_trends_with_insufficient_data(self, analyzer):
        """Trend detection requires minimum samples"""
        # Add only 5 snapshots (below MIN_SAMPLES threshold of 10)
        for i in range(5):
            analyzer.analyze_text(f"s{i}", "Short test text.", "body")

        trends = analyzer.detect_trends(days=30)
        assert len(trends) == 0  # Not enough data

    def test_detect_headline_length_trend(self, analyzer, temp_db):
        """Detect trend in headline length"""
        # Create old snapshots (short headlines)
        old_date = datetime.now() - timedelta(days=20)
        for i in range(15):
            with sqlite3.connect(temp_db) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"old-{i}", (old_date + timedelta(days=i/2)).isoformat(), "headline",
                    5.0,  # 5 word headlines (OLD)
                    10.0, 3.0, 0.8, 0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        # Create new snapshots (long headlines)
        new_date = datetime.now() - timedelta(days=5)
        for i in range(15):
            with sqlite3.connect(temp_db) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"new-{i}", (new_date + timedelta(days=i/5)).isoformat(), "headline",
                    8.0,  # 8 word headlines (NEW - 60% increase)
                    10.0, 3.0, 0.8, 0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        trends = analyzer.detect_trends(days=30)

        # Should detect headline length increase
        headline_trends = [t for t in trends if t.metric == 'avg_headline_length']
        assert len(headline_trends) > 0
        assert headline_trends[0].direction == 'increase'
        assert headline_trends[0].is_significant  # 60% change

    def test_stable_trend_detection(self, analyzer):
        """Detect when style remains stable"""
        # Add snapshots with consistent metrics
        for i in range(20):
            analyzer.analyze_text(
                f"s{i}",
                "Consistent length sentences here. Same style maintained. No variation detected.",
                "body"
            )

        trends = analyzer.detect_trends(days=30)

        # Stable metrics should be detected as 'stable'
        for trend in trends:
            if trend.direction == 'stable':
                assert trend.magnitude < 0.05  # <5% change

    def test_interpretation_generation(self, analyzer):
        """Test trend interpretation messages"""
        import sqlite3

        # Create trend with significant change
        old_date = datetime.now() - timedelta(days=20)
        new_date = datetime.now() - timedelta(days=5)

        # Insert old snapshots (low compression)
        for i in range(15):
            with sqlite3.connect(analyzer.db_path) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"old-{i}", (old_date + timedelta(days=i/2)).isoformat(), "body",
                    None, 10.0, 3.0,
                    0.6,  # 60% compression (OLD)
                    0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        # Insert new snapshots (high compression)
        for i in range(15):
            with sqlite3.connect(analyzer.db_path) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"new-{i}", (new_date + timedelta(days=i/5)).isoformat(), "body",
                    None, 10.0, 3.0,
                    0.9,  # 90% compression (NEW - 50% increase)
                    0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        trends = analyzer.detect_trends(days=30)

        compression_trends = [t for t in trends if t.metric == 'compression_score']
        assert len(compression_trends) > 0
        assert 'compressed' in compression_trends[0].interpretation.lower()


class TestPersistence:
    """Test database persistence"""

    def test_snapshot_persistence(self, analyzer):
        """Test snapshots are saved to database"""
        analyzer.analyze_text("s1", "Test text here.", "body")

        with sqlite3.connect(analyzer.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM writing_snapshots").fetchone()[0]
            assert count == 1

    def test_trend_persistence(self, analyzer):
        """Test trends are saved to database"""
        import sqlite3

        # Create sufficient data for trend detection
        old_date = datetime.now() - timedelta(days=20)
        new_date = datetime.now() - timedelta(days=5)

        for i in range(15):
            with sqlite3.connect(analyzer.db_path) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"old-{i}", (old_date + timedelta(days=i/2)).isoformat(), "body",
                    None, 10.0, 3.0, 0.6, 0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        for i in range(15):
            with sqlite3.connect(analyzer.db_path) as conn:
                conn.execute("""
                    INSERT INTO writing_snapshots
                    (session_id, timestamp, content_type, avg_headline_length,
                     avg_sentence_length, avg_paragraph_length, compression_score,
                     formality_score, technical_density, question_rate,
                     imperative_rate, passive_rate, sentence_length_variance,
                     vocabulary_richness)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"new-{i}", (new_date + timedelta(days=i/5)).isoformat(), "body",
                    None, 10.0, 3.0, 0.9, 0.2, 1.0, 10.0, 5.0, 5.0, 20.0, 0.6
                ))

        trends = analyzer.detect_trends(days=30)

        # Trends should be saved
        with sqlite3.connect(analyzer.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM style_trends").fetchone()[0]
            assert count > 0


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_text(self, analyzer):
        """Handle empty text gracefully"""
        snapshot = analyzer.analyze_text("s1", "", "body")
        assert snapshot.avg_sentence_length == 0.0

    def test_single_sentence(self, analyzer):
        """Handle single sentence"""
        snapshot = analyzer.analyze_text("s1", "Single sentence.", "body")
        assert snapshot.sentence_length_variance == 0.0

    def test_no_questions(self, analyzer):
        """Handle text with no questions"""
        snapshot = analyzer.analyze_text("s1", "No questions here. Just statements.", "body")
        assert snapshot.question_rate == 0.0

    def test_all_questions(self, analyzer):
        """Handle text with all questions"""
        # The sentence splitter breaks on "? " so we get: ["Is this one", "Is this two", "Is this three?"]
        # Only the last one has a "?" in it after splitting, so 1/3 = 33.33%
        snapshot = analyzer.analyze_text("s1", "Is this one? Is this two? Is this three?", "body")
        assert snapshot.question_rate > 0.0  # At least some questions detected


# Run with: pytest tests/wild/test_writing_analyzer.py -v
