"""
Feature 35: Personality Drift Tests

Tracks communication style evolution (directness, verbosity, formality),
detects drift over time, records snapshots for historical analysis.
"""

import pytest
import tempfile
from pathlib import Path

from src.wild.personality_drift import (
    analyze_communication_style,
    record_personality_snapshot,
    detect_drift,
    _calculate_directness,
    _calculate_verbosity,
    _calculate_formality
)

from src.memory_ts_client import Memory


class TestDirectnessScoring:
    """Tests for directness calculation"""

    def test_directness_high(self):
        """High directness detected"""
        memories = [
            Memory(id="1", content="Just do X. Don't use Y.", importance=0.7,
                  tags=[], project_id="test"),
            Memory(id="2", content="Never use A. Always use B.", importance=0.7,
                  tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['directness'] > 0.5

    def test_directness_low(self):
        """Low directness (indirect) detected"""
        memories = [
            Memory(id="1", content="Perhaps we might consider trying this",
                  importance=0.7, tags=[], project_id="test"),
            Memory(id="2", content="I think maybe we could possibly use that",
                  importance=0.7, tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['directness'] < 0.5


class TestVerbosityScoring:
    """Tests for verbosity calculation"""

    def test_verbosity_concise(self):
        """Concise style (low verbosity)"""
        memories = [
            Memory(id="1", content="Short.", importance=0.7,
                  tags=[], project_id="test"),
            Memory(id="2", content="Brief text.", importance=0.7,
                  tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['verbosity'] < 0.3

    def test_verbosity_verbose(self):
        """Verbose style detected"""
        long_text = " ".join(["word"] * 120)
        memories = [
            Memory(id="1", content=long_text, importance=0.7,
                  tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['verbosity'] > 0.7


class TestFormalityScoring:
    """Tests for formality calculation"""

    def test_formality_casual(self):
        """Casual style detected"""
        memories = [
            Memory(id="1", content="Yeah gonna do that! Cool!!", importance=0.7,
                  tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['formality'] < 0.5

    def test_formality_formal(self):
        """Formal style detected"""
        memories = [
            Memory(id="1", content="Therefore, one must carefully consider this matter. Furthermore, additional analysis reveals significant implications.",
                  importance=0.7, tags=[], project_id="test")
        ]
        result = analyze_communication_style(memories)
        assert result['formality'] > 0.5


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_memories(self):
        """Handles empty memory list"""
        result = analyze_communication_style([])
        assert result['directness'] == 0.5  # Default
        assert result['verbosity'] == 0.5
        assert result['formality'] == 0.5
        assert result['sample_size'] == 0


class TestSnapshotRecording:
    """Tests for personality snapshot persistence"""

    def test_snapshot_recording(self):
        """Records personality snapshot to database"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            mem_dir = Path(tmpdir) / "memories"
            mem_dir.mkdir()

            snapshot = record_personality_snapshot(
                window_days=30,
                memory_dir=mem_dir,
                db_path=db_path
            )

            assert 'directness' in snapshot
            assert 'verbosity' in snapshot
            assert 'formality' in snapshot
            assert 'date' in snapshot


class TestDriftDetection:
    """Tests for drift detection over time"""

    def test_drift_detection_insufficient_data(self):
        """Drift detection handles insufficient history"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            drift = detect_drift(days=180, db_path=db_path)
            assert drift['drift_detected'] is False
            assert 'message' in drift


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
