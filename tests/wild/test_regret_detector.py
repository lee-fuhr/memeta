"""Tests for F58: Decision Regret Detection"""

import pytest
import tempfile
import os

from memory_system.wild.regret_detector import RegretDetector, DecisionOutcome, RegretPattern


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def detector(temp_db):
    return RegretDetector(temp_db)


def test_detector_initialization(detector):
    assert detector is not None


def test_record_decision(detector):
    decision_id = detector.record_decision("Use framework X")
    assert decision_id is not None


def test_record_decision_with_outcome(detector):
    decision_id = detector.record_decision("Use framework X", outcome="good")
    assert decision_id is not None


def test_record_decision_invalid_outcome(detector):
    with pytest.raises(ValueError):
        detector.record_decision("Test", outcome="maybe")


def test_mark_regret(detector):
    decision_id = detector.record_decision("Use framework X")
    detector.mark_regret(decision_id)


def test_detect_regret_pattern_none(detector):
    detector.record_decision("Use framework X")
    pattern = detector.detect_regret_pattern("Use framework X")
    assert pattern is None  # Only 1 occurrence


def test_detect_regret_pattern_exists(detector):
    d1 = detector.record_decision("Use framework X")
    d2 = detector.record_decision("Use framework X again")
    detector.mark_regret(d1)
    
    pattern = detector.detect_regret_pattern("Use framework X")
    assert pattern is not None
    assert pattern.occurrence_count == 2


def test_warn_about_decision_none(detector):
    warning = detector.warn_about_decision("New decision")
    assert warning is None


def test_warn_about_decision_exists(detector):
    d1 = detector.record_decision("Use framework X")
    d2 = detector.record_decision("Use framework X")
    detector.mark_regret(d1)
    
    warning = detector.warn_about_decision("Use framework X")
    assert warning is not None
    assert "WARNING" in warning


def test_get_decision_history_empty(detector):
    history = detector.get_decision_history()
    assert history == []


def test_get_decision_history_with_data(detector):
    detector.record_decision("Decision 1")
    detector.record_decision("Decision 2")
    
    history = detector.get_decision_history()
    assert len(history) == 2


def test_get_decision_history_regrets_only(detector):
    d1 = detector.record_decision("Decision 1")
    d2 = detector.record_decision("Decision 2")
    detector.mark_regret(d1)
    
    history = detector.get_decision_history(include_regrets_only=True)
    assert len(history) == 1


def test_get_regret_statistics(detector):
    d1 = detector.record_decision("Decision 1")
    detector.record_decision("Decision 2")
    detector.mark_regret(d1)
    
    stats = detector.get_regret_statistics()
    assert stats["total_decisions"] == 2
    assert stats["regrets"] == 1
    assert stats["regret_rate"] == 0.5
