"""Tests for F60: Context Decay Prediction"""

import pytest
import tempfile
import os
from datetime import datetime

from src.wild.decay_predictor import DecayPredictor, DecayPrediction


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def predictor(temp_db):
    return DecayPredictor(temp_db)


def test_predictor_initialization(predictor):
    assert predictor is not None


def test_predict_decay(predictor):
    decay_date = predictor.predict_decay("mem123", reason="project_inactive")
    assert isinstance(decay_date, datetime)


def test_predict_decay_updates_existing(predictor):
    predictor.predict_decay("mem123", reason="project_inactive", days_until_stale=30)
    predictor.predict_decay("mem123", reason="superseded", days_until_stale=7)
    
    prediction = predictor.get_prediction("mem123")
    assert prediction.reason == "superseded"


def test_get_memories_becoming_stale_empty(predictor):
    memories = predictor.get_memories_becoming_stale(days_ahead=7)
    assert memories == []


def test_get_memories_becoming_stale_with_data(predictor):
    predictor.predict_decay("mem123", days_until_stale=5)
    predictor.predict_decay("mem456", days_until_stale=10)
    
    memories = predictor.get_memories_becoming_stale(days_ahead=7)
    assert len(memories) == 1  # Only one within 7 days


def test_refresh_memory(predictor):
    predictor.predict_decay("mem123", days_until_stale=5)
    predictor.refresh_memory("mem123")
    
    prediction = predictor.get_prediction("mem123")
    assert prediction.reviewed_at is not None


def test_refresh_memory_excludes_from_stale(predictor):
    predictor.predict_decay("mem123", days_until_stale=5)
    predictor.refresh_memory("mem123")
    
    memories = predictor.get_memories_becoming_stale(days_ahead=7)
    assert len(memories) == 0


def test_get_prediction_none(predictor):
    prediction = predictor.get_prediction("nonexistent")
    assert prediction is None


def test_get_prediction_exists(predictor):
    predictor.predict_decay("mem123")
    prediction = predictor.get_prediction("mem123")
    assert prediction is not None
    assert prediction.memory_id == "mem123"


def test_get_statistics(predictor):
    predictor.predict_decay("mem1", reason="project_inactive")
    predictor.predict_decay("mem2", reason="superseded")
    predictor.refresh_memory("mem1")
    
    stats = predictor.get_statistics()
    assert stats["total_predictions"] == 2
    assert stats["reviewed"] == 1
    assert stats["unreviewed"] == 1
    assert "by_reason" in stats
