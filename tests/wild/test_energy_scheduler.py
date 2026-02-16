"""Tests for F53: Energy-Aware Scheduling"""

import pytest
import tempfile
import os
from datetime import datetime

from memory_system.wild.energy_scheduler import EnergyScheduler, EnergyPattern, TaskComplexity


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def scheduler(temp_db):
    """Create EnergyScheduler with temp database"""
    return EnergyScheduler(temp_db)


def test_scheduler_initialization(scheduler):
    """Test scheduler initializes correctly"""
    assert scheduler is not None
    assert scheduler.db is not None


def test_default_tasks_loaded(scheduler):
    """Test default task complexities are loaded"""
    tasks = scheduler.get_task_complexities()

    assert len(tasks) > 0
    task_types = [t.task_type for t in tasks]
    assert "deep_work" in task_types
    assert "admin" in task_types


def test_record_energy_level(scheduler):
    """Test recording energy level"""
    scheduler.record_energy_level(hour=9, level="high")

    patterns = scheduler.get_energy_patterns(hour=9)

    assert len(patterns) == 1
    assert patterns[0].hour_of_day == 9
    assert patterns[0].energy_level == "high"
    assert patterns[0].sample_count == 1


def test_record_energy_level_with_day(scheduler):
    """Test recording energy level with day of week"""
    scheduler.record_energy_level(hour=9, level="high", day_of_week=0)  # Monday

    patterns = scheduler.get_energy_patterns(hour=9)

    assert len(patterns) == 1
    assert patterns[0].day_of_week == 0


def test_record_energy_level_updates_pattern(scheduler):
    """Test that recording multiple times updates pattern"""
    scheduler.record_energy_level(hour=9, level="high")
    scheduler.record_energy_level(hour=9, level="high")

    patterns = scheduler.get_energy_patterns(hour=9)

    assert len(patterns) == 1
    assert patterns[0].sample_count == 2
    assert patterns[0].confidence > 0.5


def test_record_energy_invalid_hour(scheduler):
    """Test validation of hour parameter"""
    with pytest.raises(ValueError):
        scheduler.record_energy_level(hour=25, level="high")


def test_record_energy_invalid_level(scheduler):
    """Test validation of level parameter"""
    with pytest.raises(ValueError):
        scheduler.record_energy_level(hour=9, level="very_high")


def test_record_energy_invalid_day(scheduler):
    """Test validation of day_of_week parameter"""
    with pytest.raises(ValueError):
        scheduler.record_energy_level(hour=9, level="high", day_of_week=7)


def test_get_current_energy_prediction_unknown(scheduler):
    """Test prediction returns unknown when no data"""
    prediction = scheduler.get_current_energy_prediction()

    assert prediction == "unknown"


def test_get_current_energy_prediction_with_data(scheduler):
    """Test prediction uses recorded data"""
    now = datetime.now()
    hour = now.hour

    # Record multiple samples to build confidence
    for _ in range(3):
        scheduler.record_energy_level(hour=hour, level="high")

    prediction = scheduler.get_current_energy_prediction()

    assert prediction == "high"


def test_suggest_task_for_current_time_default(scheduler):
    """Test task suggestion with no data (defaults to medium)"""
    tasks = scheduler.suggest_task_for_current_time()

    # Should suggest medium-energy tasks
    assert len(tasks) > 0
    assert "meetings" in tasks or "code_review" in tasks


def test_suggest_task_for_current_time_high_energy(scheduler):
    """Test task suggestion for high energy time"""
    now = datetime.now()
    hour = now.hour

    # Build high energy pattern
    for _ in range(3):
        scheduler.record_energy_level(hour=hour, level="high")

    tasks = scheduler.suggest_task_for_current_time()

    assert len(tasks) > 0
    assert "deep_work" in tasks or "writing" in tasks or "learning" in tasks


def test_suggest_task_for_current_time_low_energy(scheduler):
    """Test task suggestion for low energy time"""
    now = datetime.now()
    hour = now.hour

    # Build low energy pattern
    for _ in range(3):
        scheduler.record_energy_level(hour=hour, level="low")

    tasks = scheduler.suggest_task_for_current_time()

    assert len(tasks) > 0
    assert "admin" in tasks


def test_get_energy_patterns_all(scheduler):
    """Test getting all energy patterns"""
    scheduler.record_energy_level(hour=9, level="high")
    scheduler.record_energy_level(hour=14, level="medium")
    scheduler.record_energy_level(hour=16, level="low")

    patterns = scheduler.get_energy_patterns()

    assert len(patterns) == 3
    assert all(isinstance(p, EnergyPattern) for p in patterns)


def test_get_energy_patterns_filtered(scheduler):
    """Test getting energy patterns for specific hour"""
    scheduler.record_energy_level(hour=9, level="high")
    scheduler.record_energy_level(hour=14, level="medium")

    patterns = scheduler.get_energy_patterns(hour=9)

    assert len(patterns) == 1
    assert patterns[0].hour_of_day == 9


def test_get_task_complexities(scheduler):
    """Test getting task complexity definitions"""
    complexities = scheduler.get_task_complexities()

    assert len(complexities) > 0
    assert all(isinstance(c, TaskComplexity) for c in complexities)

    # Check structure
    deep_work = next((c for c in complexities if c.task_type == "deep_work"), None)
    assert deep_work is not None
    assert deep_work.cognitive_load == "high"
    assert deep_work.optimal_energy == "high"
    assert isinstance(deep_work.examples, list)
    assert len(deep_work.examples) > 0


def test_energy_confidence_increases_with_samples(scheduler):
    """Test that confidence increases with more samples"""
    # Record once
    scheduler.record_energy_level(hour=9, level="high")
    patterns = scheduler.get_energy_patterns(hour=9)
    initial_confidence = patterns[0].confidence

    # Record again
    scheduler.record_energy_level(hour=9, level="high")
    patterns = scheduler.get_energy_patterns(hour=9)
    second_confidence = patterns[0].confidence

    assert second_confidence > initial_confidence


def test_energy_confidence_capped_at_one(scheduler):
    """Test that confidence doesn't exceed 1.0"""
    # Record many times
    for _ in range(20):
        scheduler.record_energy_level(hour=9, level="high")

    patterns = scheduler.get_energy_patterns(hour=9)

    assert patterns[0].confidence <= 1.0
