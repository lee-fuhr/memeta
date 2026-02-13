"""
Comprehensive test suite for Features 33-42
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

# Feature 33: Sentiment
from src.wild.sentiment_tracker import analyze_sentiment, get_sentiment_trends

# Feature 34: Velocity
from src.wild.learning_velocity import calculate_velocity_metrics, _is_correction

# Feature 35: Personality
from src.wild.personality_drift import analyze_communication_style, detect_drift

# Feature 37: Conflict prediction
from src.wild.conflict_predictor import predict_conflicts, _calculate_conflict_confidence

# Feature 38-42: Integrations
from src.wild.integrations import (
    export_to_obsidian, export_to_roam, learn_email_pattern,
    _extract_meeting_insights
)

# Database
from src.wild.intelligence_db import IntelligenceDB


# ============================================================================
# Feature 33: Sentiment Tracking Tests
# ============================================================================

class TestSentimentTracking:
    def test_frustrated_detection(self):
        """Detects frustration keywords"""
        content = "This is annoying and doesn't work properly"
        sentiment, triggers = analyze_sentiment(content)
        assert sentiment == 'frustrated'
        assert triggers is not None

    def test_satisfied_detection(self):
        """Detects satisfaction keywords"""
        content = "Perfect! This works great, thank you"
        sentiment, triggers = analyze_sentiment(content)
        assert sentiment == 'satisfied'
        assert triggers is not None

    def test_neutral_default(self):
        """Defaults to neutral when no keywords"""
        content = "The system processes data"
        sentiment, triggers = analyze_sentiment(content)
        assert sentiment == 'neutral'
        assert triggers is None

    def test_database_logging(self):
        """Logs sentiment to database"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with IntelligenceDB(db_path) as db:
                log_id = db.log_sentiment(
                    session_id="test_session",
                    sentiment="frustrated",
                    trigger_words="annoying, broken",
                    context="Test context"
                )
                assert log_id > 0


# ============================================================================
# Feature 34: Learning Velocity Tests
# ============================================================================

class TestLearningVelocity:
    def test_is_correction_detection(self):
        """Identifies correction memories"""
        from src.memory_ts_client import Memory

        correction = Memory(
            id="test1",
            content="Don't do that, instead use this approach",
            importance=0.8,
            tags=["correction"],
            project_id="test"
        )
        assert _is_correction(correction) is True

        normal = Memory(
            id="test2",
            content="User prefers morning meetings",
            importance=0.7,
            tags=["preference"],
            project_id="test"
        )
        assert _is_correction(normal) is False

    def test_velocity_score_calculation(self):
        """Calculates velocity scores correctly"""
        # Use temp directory to avoid corrupt data in actual memory-ts
        with tempfile.TemporaryDirectory() as tmpdir:
            result = calculate_velocity_metrics(window_days=30, memory_dir=Path(tmpdir))
            assert result['velocity_score'] == 0.0
            assert result['status'] == 'no_data'


# ============================================================================
# Feature 35: Personality Drift Tests
# ============================================================================

class TestPersonalityDrift:
    def test_directness_scoring(self):
        """Scores directness correctly"""
        from src.memory_ts_client import Memory

        direct_mems = [
            Memory(id="1", content="Just do this. Don't use that.", importance=0.7,
                  tags=[], project_id="test"),
            Memory(id="2", content="Never use X. Always use Y.", importance=0.7,
                  tags=[], project_id="test")
        ]

        indirect_mems = [
            Memory(id="1", content="Perhaps we might consider using this approach",
                  importance=0.7, tags=[], project_id="test"),
            Memory(id="2", content="I think maybe we could try this", importance=0.7,
                  tags=[], project_id="test")
        ]

        direct_style = analyze_communication_style(direct_mems)
        indirect_style = analyze_communication_style(indirect_mems)

        assert direct_style['directness'] > indirect_style['directness']

    def test_verbosity_scoring(self):
        """Scores verbosity correctly"""
        from src.memory_ts_client import Memory

        concise = [Memory(id="1", content="Short text", importance=0.7,
                         tags=[], project_id="test")]
        verbose = [Memory(id="1", content=" ".join(["word"] * 150), importance=0.7,
                         tags=[], project_id="test")]

        concise_style = analyze_communication_style(concise)
        verbose_style = analyze_communication_style(verbose)

        assert verbose_style['verbosity'] > concise_style['verbosity']


# ============================================================================
# Feature 37: Conflict Prediction Tests
# ============================================================================

class TestConflictPrediction:
    def test_confidence_calculation(self):
        """Calculates conflict confidence"""
        similar_memory = {
            'id': 'test1',
            'content': 'User prefers morning meetings at 9am'
        }

        # High overlap, both have preferences
        new_content = "User prefers afternoon meetings at 2pm"
        confidence = _calculate_conflict_confidence(new_content, similar_memory)
        assert confidence >= 0.5  # Should be high due to preference keywords

    def test_no_conflict_prediction(self):
        """Predicts no conflict when memories are compatible"""
        # Use temp directory to avoid API issues
        with tempfile.TemporaryDirectory() as tmpdir:
            new_content = "The sky is blue"
            result = predict_conflicts(new_content, memory_dir=Path(tmpdir))
            assert result['conflict_predicted'] is False


# ============================================================================
# Feature 38-42: Integration Tests
# ============================================================================

class TestIntegrations:
    def test_roam_export_format(self):
        """Exports to Roam format correctly"""
        from src.memory_ts_client import Memory

        memories = [
            Memory(
                id="1",
                content="Test memory 1",
                importance=0.8,
                tags=["tag1"],
                project_id="test",
                created=datetime.now().isoformat()
            )
        ]

        roam_text = export_to_roam(memories)
        assert "## " in roam_text  # Date header
        assert "- Test memory 1" in roam_text
        assert "#memory" in roam_text

    def test_email_pattern_learning(self):
        """Learns email patterns"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            pattern_id = learn_email_pattern(
                "categorization",
                "from:client@x.com → Important",
                confidence=0.9,
                db_path=db_path
            )
            assert pattern_id > 0

    def test_meeting_insight_extraction(self):
        """Extracts insights from meeting transcript"""
        transcript = "We decided to launch next week. Action item: send proposal."
        insights = _extract_meeting_insights(transcript)
        assert len(insights) > 0
        assert any('decided' in i['content'].lower() for i in insights)


# ============================================================================
# Database Tests
# ============================================================================

class TestIntelligenceDB:
    def test_database_creation(self):
        """Creates database with all tables"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with IntelligenceDB(db_path) as db:
                cursor = db.conn.cursor()

                # Check all tables exist
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table'
                    ORDER BY name
                """)
                tables = [row[0] for row in cursor.fetchall()]

                expected_tables = [
                    'sentiment_patterns',
                    'learning_velocity',
                    'personality_drift',
                    'conflict_predictions',
                    'obsidian_sync_state',
                    'notion_sync_state',
                    'roam_sync_state',
                    'email_patterns',
                    'meeting_memories'
                ]

                for table in expected_tables:
                    assert table in tables

    def test_velocity_recording(self):
        """Records velocity metrics"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with IntelligenceDB(db_path) as db:
                record_id = db.record_velocity(
                    date="2026-02-12",
                    total_memories=100,
                    corrections=15,
                    velocity_score=85.0,
                    window_days=30
                )
                assert record_id > 0

                # Verify recorded
                history = db.get_velocity_trend(days=30)
                assert len(history) == 1
                assert history[0]['velocity_score'] == 85.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
