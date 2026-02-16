"""
Feature 34: Learning Velocity Tests

Measures correction rate over time, tracks learning efficiency,
estimates ROI on memory system investment.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from memory_system.wild.learning_velocity import (
    calculate_velocity_metrics,
    get_velocity_trend,
    get_correction_breakdown,
    get_roi_estimate,
    _is_correction
)

from memory_system.memory_ts_client import Memory


class TestCorrectionDetection:
    """Tests for correction identification logic"""

    def test_is_correction_with_tag(self):
        """Detects corrections via tags"""
        mem = Memory(
            id="test1",
            content="Use approach B instead",
            importance=0.8,
            tags=["correction"],
            project_id="test"
        )
        assert _is_correction(mem) is True

    def test_is_correction_with_content(self):
        """Detects corrections via content phrases"""
        mem = Memory(
            id="test2",
            content="Don't use that method, it's wrong",
            importance=0.7,
            tags=[],
            project_id="test"
        )
        assert _is_correction(mem) is True

    def test_not_correction(self):
        """Non-corrections return False"""
        mem = Memory(
            id="test3",
            content="User prefers morning meetings",
            importance=0.7,
            tags=["preference"],
            project_id="test"
        )
        assert _is_correction(mem) is False


class TestVelocityCalculation:
    """Tests for velocity metric calculation"""

    def test_velocity_with_no_data(self):
        """Handles empty memory directory gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = calculate_velocity_metrics(
                window_days=30,
                memory_dir=Path(tmpdir)
            )
            assert result['status'] == 'no_data'
            assert result['velocity_score'] == 0.0

    def test_correction_breakdown_empty(self):
        """Handles empty corrections"""
        with tempfile.TemporaryDirectory() as tmpdir:
            breakdown = get_correction_breakdown(
                window_days=30,
                memory_dir=Path(tmpdir)
            )
            assert breakdown['total'] == 0
            assert breakdown['by_category'] == {}


class TestVelocityTrend:
    """Tests for velocity trend detection"""

    def test_velocity_trend_insufficient_data(self):
        """Trend detection handles insufficient data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            trend = get_velocity_trend(days=90, db_path=db_path)
            assert trend['trend'] == 'insufficient_data'


class TestROIEstimation:
    """Tests for ROI estimation logic"""

    def test_roi_estimate_no_data(self):
        """ROI estimate handles no data gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            roi = get_roi_estimate(days=90, db_path=db_path)
            assert roi['roi'] == 'unknown'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
