"""Tests for Feature 130: Confidence Calibration."""

import sqlite3

import pytest

from memory_system.confidence_calibration import (
    CalibrationBin,
    CalibrationEvent,
    detect_implicit_usage,
    get_calibration_stats,
    log_calibration_event,
)


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_calibration.db")


# --- log_calibration_event ---


def test_log_event_returns_row_id(db_path):
    row_id = log_calibration_event(db_path, "mem-1", 0.8, True, "retrieval")
    assert isinstance(row_id, int)
    assert row_id >= 1


def test_log_event_stores_all_fields(db_path):
    log_calibration_event(db_path, "mem-42", 0.75, False, "surfaced")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM confidence_calibration_log WHERE id = 1").fetchone()
    conn.close()

    assert row["memory_id"] == "mem-42"
    assert row["predicted_confidence"] == pytest.approx(0.75)
    assert row["actual_outcome"] == 0  # False stored as 0
    assert row["signal_type"] == "surfaced"
    assert row["timestamp"]  # non-empty ISO string


def test_log_event_multiple_increment_ids(db_path):
    id1 = log_calibration_event(db_path, "mem-1", 0.5, True, "retrieval")
    id2 = log_calibration_event(db_path, "mem-2", 0.6, False, "injected")
    id3 = log_calibration_event(db_path, "mem-3", 0.7, True, "surfaced")
    assert id1 < id2 < id3


# --- get_calibration_stats ---


def test_stats_correct_bin_assignment(db_path):
    log_calibration_event(db_path, "mem-1", 0.55, True, "retrieval")
    stats = get_calibration_stats(db_path)
    assert "0.5-0.6" in stats
    assert stats["0.5-0.6"].sample_count == 1


def test_stats_correct_hit_rate(db_path):
    # 2 out of 3 correct in the same bin
    log_calibration_event(db_path, "mem-1", 0.71, True, "retrieval")
    log_calibration_event(db_path, "mem-2", 0.75, True, "surfaced")
    log_calibration_event(db_path, "mem-3", 0.79, False, "injected")
    stats = get_calibration_stats(db_path)
    bin_data = stats["0.7-0.8"]
    assert bin_data.actual_hit_rate == pytest.approx(2.0 / 3.0)
    assert bin_data.sample_count == 3


def test_stats_multiple_bins_populated(db_path):
    log_calibration_event(db_path, "mem-1", 0.15, True, "retrieval")
    log_calibration_event(db_path, "mem-2", 0.55, False, "surfaced")
    log_calibration_event(db_path, "mem-3", 0.95, True, "injected")
    stats = get_calibration_stats(db_path)
    assert "0.1-0.2" in stats
    assert "0.5-0.6" in stats
    assert "0.9-1.0" in stats
    assert len(stats) == 3


def test_stats_empty_database(db_path):
    stats = get_calibration_stats(db_path)
    assert stats == {}


def test_stats_single_event(db_path):
    log_calibration_event(db_path, "mem-1", 0.42, True, "retrieval")
    stats = get_calibration_stats(db_path)
    assert len(stats) == 1
    bin_data = stats["0.4-0.5"]
    assert bin_data.predicted_avg == pytest.approx(0.42)
    assert bin_data.actual_hit_rate == pytest.approx(1.0)
    assert bin_data.sample_count == 1


# --- detect_implicit_usage ---


def test_detect_high_overlap_returns_true():
    surfaced = "The client prefers weekly meetings on Tuesday morning"
    response = "I scheduled weekly meetings on Tuesday morning as the client prefers"
    assert detect_implicit_usage(surfaced, response) is True


def test_detect_low_overlap_returns_false():
    surfaced = "The client prefers weekly meetings on Tuesday morning"
    response = "Let me check the database for recent entries"
    assert detect_implicit_usage(surfaced, response) is False


def test_detect_handles_empty_strings():
    assert detect_implicit_usage("", "some response") is False
    assert detect_implicit_usage("some content", "") is False
    assert detect_implicit_usage("", "") is False
