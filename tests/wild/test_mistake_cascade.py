"""Tests for F65: Mistake Compounding Detector"""

import pytest
import tempfile
import os

from src.wild.mistake_cascade import MistakeCascadeDetector, MistakeCascade


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def detector(temp_db):
    return MistakeCascadeDetector(temp_db)


def test_detector_initialization(detector):
    assert detector is not None


def test_record_cascade(detector):
    cascade_id = detector.record_cascade("root123", ["err1", "err2"])
    assert cascade_id is not None


def test_record_cascade_with_cost(detector):
    cascade_id = detector.record_cascade("root123", ["err1", "err2"], total_cost="2 hours")
    assert cascade_id is not None


def test_detect_cascade_by_root(detector):
    detector.record_cascade("root123", ["err1", "err2"])
    cascade = detector.detect_cascade("root123")
    assert cascade is not None
    assert cascade.root_mistake_id == "root123"


def test_detect_cascade_by_downstream(detector):
    detector.record_cascade("root123", ["err1", "err2"])
    cascade = detector.detect_cascade("err1")
    assert cascade is not None
    assert cascade.root_mistake_id == "root123"


def test_detect_cascade_none(detector):
    cascade = detector.detect_cascade("nonexistent")
    assert cascade is None


def test_analyze_root_cause(detector):
    detector.record_cascade("root123", ["err1", "err2"])
    root = detector.analyze_root_cause("err1")
    assert root == "root123"


def test_analyze_root_cause_none(detector):
    root = detector.analyze_root_cause("nonexistent")
    assert root is None


def test_suggest_prevention(detector):
    cascade_id = detector.record_cascade("root123", ["err1", "err2"])
    strategy = detector.suggest_prevention(cascade_id)
    assert len(strategy) > 0


def test_get_cascades_empty(detector):
    cascades = detector.get_cascades(min_depth=2)
    assert cascades == []


def test_get_cascades_with_data(detector):
    detector.record_cascade("root1", ["err1", "err2"])
    detector.record_cascade("root2", ["err3"])
    
    cascades = detector.get_cascades(min_depth=2)
    assert len(cascades) == 1  # Only one with depth >= 2


def test_get_statistics(detector):
    detector.record_cascade("root1", ["err1", "err2"])
    detector.record_cascade("root2", ["err3", "err4", "err5"])
    
    stats = detector.get_statistics()
    assert stats["total_cascades"] == 2
    assert stats["max_depth"] == 3
    assert "by_depth" in stats
