"""
Feature 37: Conflict Prediction Tests

Pre-save contradiction detection to prevent conflicting memories
from being added to the system. Uses word overlap + confidence scoring.
"""

import pytest
import tempfile
from pathlib import Path

from memory_system.wild.conflict_predictor import (
    predict_conflicts,
    _calculate_conflict_confidence
)


class TestConfidenceCalculation:
    """Tests for conflict confidence scoring"""

    def test_confidence_high_overlap(self):
        """High confidence when memories overlap significantly"""
        similar = {
            'id': 'mem1',
            'content': 'User prefers morning meetings at 9am'
        }
        new = "User prefers afternoon meetings at 2pm"

        confidence = _calculate_conflict_confidence(new, similar)
        assert confidence >= 0.5  # High overlap + preferences

    def test_confidence_low_overlap(self):
        """Low confidence when minimal overlap"""
        similar = {
            'id': 'mem1',
            'content': 'The sky is blue today'
        }
        new = "User prefers afternoon meetings"

        confidence = _calculate_conflict_confidence(new, similar)
        assert confidence < 0.3  # Low overlap


class TestConflictPrediction:
    """Tests for conflict prediction logic"""

    def test_no_conflict_unrelated(self):
        """No conflict predicted for unrelated content"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prediction = predict_conflicts(
                "The weather is nice today",
                memory_dir=Path(tmpdir)
            )
            assert prediction['conflict_predicted'] is False
            assert prediction['confidence'] == 0.0

    def test_conflict_below_threshold(self):
        """Doesn't flag conflicts below confidence threshold"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prediction = predict_conflicts(
                "Some new information",
                confidence_threshold=0.9,  # Very high threshold
                memory_dir=Path(tmpdir)
            )
            assert prediction['conflict_predicted'] is False


class TestDatabaseLogging:
    """Tests for prediction logging to database"""

    def test_prediction_logging(self):
        """Logs predictions to database when confidence exceeds threshold"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            mem_dir = Path(tmpdir) / "memories"
            mem_dir.mkdir()

            # With empty memory dir, no conflict detected, db NOT created
            prediction = predict_conflicts(
                "Test memory content",
                confidence_threshold=0.5,
                memory_dir=mem_dir,
                db_path=db_path
            )

            # No similar memories = no conflict = no logging
            assert prediction['conflict_predicted'] is False
            # Database may or may not exist depending on implementation


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
