"""
Tests for Feature 51: Temporal Pattern Prediction
"""

import pytest
import json
import tempfile
import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from src.wild.temporal_predictor import TemporalPatternPredictor, TemporalPattern
from src.memory_ts_client import MemoryTSClient, Memory


@pytest.fixture
def predictor():
    """Create predictor with temp database"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    pred = TemporalPatternPredictor(db_path=db_path)
    yield pred

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def temp_memory_dir():
    """Create temporary memory directory"""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)


# ========================================
# INITIALIZATION TESTS
# ========================================

def test_predictor_initialization(predictor):
    """Test predictor initializes database correctly"""
    with sqlite3.connect(predictor.db_path) as conn:
        # Check tables exist
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'temporal_patterns' in table_names
        assert 'memory_access_log' in table_names


def test_predictor_creates_indexes(predictor):
    """Test predictor creates required indexes"""
    with sqlite3.connect(predictor.db_path) as conn:
        indexes = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='index'
        """).fetchall()

        index_names = [i[0] for i in indexes]
        assert 'idx_temporal_pattern_type' in index_names
        assert 'idx_temporal_trigger' in index_names
        assert 'idx_temporal_confidence' in index_names
        assert 'idx_access_memory' in index_names
        assert 'idx_access_temporal' in index_names


# ========================================
# ACCESS LOGGING TESTS
# ========================================

def test_log_memory_access_basic(predictor):
    """Test logging a basic memory access"""
    log_id = predictor.log_memory_access(
        memory_id='test_mem_1',
        access_type='search'
    )

    assert log_id is not None
    assert len(log_id) == 16  # MD5 hash truncated to 16 chars

    # Verify entry in database
    with sqlite3.connect(predictor.db_path) as conn:
        entry = conn.execute(
            "SELECT * FROM memory_access_log WHERE id = ?",
            (log_id,)
        ).fetchone()

        assert entry is not None
        assert entry[1] == 'test_mem_1'  # memory_id
        assert entry[3] == 'search'  # access_type


def test_log_memory_access_with_context(predictor):
    """Test logging access with context keywords"""
    log_id = predictor.log_memory_access(
        memory_id='test_mem_2',
        access_type='hook',
        context_keywords=['messaging', 'framework', 'Connection Lab'],
        session_id='test_session_123'
    )

    with sqlite3.connect(predictor.db_path) as conn:
        entry = conn.execute(
            "SELECT context_keywords, session_id FROM memory_access_log WHERE id = ?",
            (log_id,)
        ).fetchone()

        keywords = json.loads(entry[0])
        assert keywords == ['messaging', 'framework', 'Connection Lab']
        assert entry[1] == 'test_session_123'


def test_log_memory_access_temporal_data(predictor):
    """Test access log captures temporal data correctly"""
    now = datetime.now()

    log_id = predictor.log_memory_access(
        memory_id='test_mem_3',
        access_type='direct'
    )

    with sqlite3.connect(predictor.db_path) as conn:
        entry = conn.execute(
            "SELECT day_of_week, hour_of_day FROM memory_access_log WHERE id = ?",
            (log_id,)
        ).fetchone()

        assert entry[0] == now.weekday()  # 0=Monday
        assert entry[1] == now.hour


# ========================================
# PATTERN DETECTION TESTS
# ========================================

def test_detect_daily_pattern(predictor):
    """Test detection of daily pattern (same hour, multiple days)"""
    # Simulate 5 accesses at 9am on the SAME day (to create a weekly pattern)
    for i in range(5):
        log_id = predictor.log_memory_access(
            memory_id='daily_mem',
            access_type='search'
        )

        # Set all to Monday 9am to create a strong pattern
        with sqlite3.connect(predictor.db_path) as conn:
            conn.execute(
                "UPDATE memory_access_log SET day_of_week = 0, hour_of_day = 9 WHERE id = ?",
                (log_id,)
            )
            conn.commit()

    patterns = predictor.detect_patterns(min_occurrences=3)

    assert len(patterns) > 0
    # Should detect weekly pattern for Monday 9am
    assert any(p['pattern_type'] == 'weekly' for p in patterns)


def test_detect_weekly_pattern(predictor):
    """Test detection of weekly pattern (same day+hour, multiple weeks)"""
    # Simulate 4 accesses on Monday at 9am
    now = datetime.now()
    monday_hour = 9

    for i in range(4):
        log_id = predictor.log_memory_access(
            memory_id='weekly_mem',
            access_type='search'
        )

        # Force to Monday 9am
        with sqlite3.connect(predictor.db_path) as conn:
            conn.execute(
                "UPDATE memory_access_log SET day_of_week = 0, hour_of_day = ? WHERE id = ?",
                (monday_hour, log_id)
            )
            conn.commit()

    patterns = predictor.detect_patterns(min_occurrences=3)

    assert len(patterns) > 0
    weekly_pattern = next((p for p in patterns if p['pattern_type'] == 'weekly'), None)
    assert weekly_pattern is not None
    assert 'Monday' in weekly_pattern['trigger_condition']


def test_no_pattern_below_threshold(predictor):
    """Test no pattern when occurrences < threshold (min 3)"""
    # Only 2 accesses - below threshold
    predictor.log_memory_access(memory_id='rare_mem', access_type='search')
    predictor.log_memory_access(memory_id='rare_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)

    # Should not detect pattern for rare_mem
    assert not any('rare_mem' in str(p.get('memory_ids', [])) for p in patterns)


def test_pattern_confidence_calculation(predictor):
    """Test pattern confidence calculated correctly"""
    # Create 5 accesses
    for i in range(5):
        predictor.log_memory_access(memory_id='conf_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)

    assert len(patterns) > 0
    pattern = patterns[0]

    # Confidence = min(1.0, count / (count + 2))
    # With 5 occurrences: 5 / (5 + 2) = 0.714
    expected_confidence = 5 / (5 + 2)
    assert abs(pattern['confidence'] - expected_confidence) < 0.01


def test_overlapping_patterns(predictor):
    """Test overlapping patterns handled (Monday 9am AND daily 9am)"""
    # Create multiple accesses at 9am on different days
    for day in range(7):
        for week in range(3):
            log_id = predictor.log_memory_access(
                memory_id=f'overlap_mem_{day}',
                access_type='search'
            )

            with sqlite3.connect(predictor.db_path) as conn:
                conn.execute(
                    "UPDATE memory_access_log SET day_of_week = ?, hour_of_day = 9 WHERE id = ?",
                    (day, log_id)
                )
                conn.commit()

    patterns = predictor.detect_patterns(min_occurrences=3)

    # Should detect multiple patterns (weekly for specific days)
    assert len(patterns) >= 3


# ========================================
# PREDICTION TESTS
# ========================================

def test_predict_needs_at_correct_time(predictor):
    """Test predict needs at correct time (Monday 9am → pattern)"""
    # Create pattern for Monday 9am (need 8 occurrences for confidence > 0.7)
    for i in range(8):
        log_id = predictor.log_memory_access(
            memory_id='monday_mem',
            access_type='search'
        )

        with sqlite3.connect(predictor.db_path) as conn:
            conn.execute(
                "UPDATE memory_access_log SET day_of_week = 0, hour_of_day = 9 WHERE id = ?",
                (log_id,)
            )
            conn.commit()

    # Detect patterns
    predictor.detect_patterns(min_occurrences=3)

    # Predict for Monday 9am (Feb 16, 2026 is actually Monday)
    monday_9am = datetime(2026, 2, 16, 9, 0)  # Monday
    predictions = predictor.predict_needs(
        current_time=monday_9am,
        confidence_threshold=0.7
    )

    assert len(predictions) > 0
    assert 'Monday 9:00' in predictions[0]['trigger_condition']


def test_predict_filters_by_confidence(predictor):
    """Test filter by confidence threshold (only >0.7)"""
    # Create low-confidence pattern (only 3 occurrences)
    for i in range(3):
        predictor.log_memory_access(memory_id='low_conf_mem', access_type='search')

    predictor.detect_patterns(min_occurrences=3)

    # Query with high threshold
    predictions = predictor.predict_needs(confidence_threshold=0.9)

    # Should not return low-confidence pattern
    assert len(predictions) == 0


def test_no_predictions_when_no_patterns(predictor):
    """Test no predictions when no patterns exist"""
    predictions = predictor.predict_needs()

    assert len(predictions) == 0


def test_predictions_include_memory_ids(predictor):
    """Test predictions include correct memory_ids"""
    # Create pattern
    for i in range(4):
        log_id = predictor.log_memory_access(
            memory_id='id_test_mem',
            access_type='search'
        )

        with sqlite3.connect(predictor.db_path) as conn:
            conn.execute(
                "UPDATE memory_access_log SET day_of_week = 2, hour_of_day = 14 WHERE id = ?",
                (log_id,)
            )
            conn.commit()

    predictor.detect_patterns(min_occurrences=3)

    # Predict for Wednesday 2pm
    wednesday_2pm = datetime(2026, 2, 19, 14, 0)  # Wednesday
    predictions = predictor.predict_needs(
        current_time=wednesday_2pm,
        confidence_threshold=0.5
    )

    if predictions:
        assert 'id_test_mem' in predictions[0]['memory_ids']


# ========================================
# FEEDBACK LOOP TESTS
# ========================================

def test_confirm_prediction_increases_confidence(predictor):
    """Test confirm prediction increases confidence (+0.05)"""
    # Create pattern
    for i in range(4):
        predictor.log_memory_access(memory_id='confirm_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)
    pattern_id = patterns[0]['id']

    # Get initial confidence
    with sqlite3.connect(predictor.db_path) as conn:
        initial_conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    # Confirm prediction
    predictor.confirm_prediction(pattern_id)

    # Verify confidence increased
    with sqlite3.connect(predictor.db_path) as conn:
        new_conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    assert new_conf > initial_conf
    assert abs(new_conf - initial_conf - 0.05) < 0.01


def test_dismiss_prediction_decreases_confidence(predictor):
    """Test dismiss prediction decreases confidence (-0.1)"""
    # Create pattern
    for i in range(4):
        predictor.log_memory_access(memory_id='dismiss_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)
    pattern_id = patterns[0]['id']

    # Get initial confidence
    with sqlite3.connect(predictor.db_path) as conn:
        initial_conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    # Dismiss prediction
    predictor.dismiss_prediction(pattern_id)

    # Verify confidence decreased
    with sqlite3.connect(predictor.db_path) as conn:
        new_conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    assert new_conf < initial_conf
    assert abs(initial_conf - new_conf - 0.1) < 0.01


def test_confidence_clamped_to_bounds(predictor):
    """Test confidence clamped to [0.0, 1.0]"""
    # Create pattern with high confidence
    for i in range(10):
        predictor.log_memory_access(memory_id='clamp_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)
    pattern_id = patterns[0]['id']

    # Confirm many times to try to exceed 1.0
    for i in range(30):
        predictor.confirm_prediction(pattern_id)

    with sqlite3.connect(predictor.db_path) as conn:
        conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    assert conf <= 1.0


def test_multiple_dismissals_disable_pattern(predictor):
    """Test multiple dismissals disable pattern (confidence → 0)"""
    # Create pattern
    for i in range(4):
        predictor.log_memory_access(memory_id='disable_mem', access_type='search')

    patterns = predictor.detect_patterns(min_occurrences=3)
    pattern_id = patterns[0]['id']

    # Dismiss many times
    for i in range(20):
        predictor.dismiss_prediction(pattern_id)

    with sqlite3.connect(predictor.db_path) as conn:
        conf = conn.execute(
            "SELECT confidence FROM temporal_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()[0]

    assert conf == 0.0


# ========================================
# STATISTICS TESTS
# ========================================

def test_get_pattern_stats(predictor):
    """Test get pattern statistics"""
    # Create some patterns
    for i in range(5):
        predictor.log_memory_access(memory_id=f'stats_mem_{i}', access_type='search')

    predictor.detect_patterns(min_occurrences=3)

    stats = predictor.get_pattern_stats()

    assert 'total_patterns' in stats
    assert 'active_patterns' in stats
    assert 'total_accesses_logged' in stats
    assert 'patterns_by_type' in stats

    assert stats['total_accesses_logged'] == 5


# ========================================
# HOOK INTEGRATION TESTS
# ========================================

def _load_hook_module():
    """Load topic_resumption_detector with clean imports."""
    import sys
    import importlib
    from pathlib import Path
    src_path = str(Path(__file__).parent.parent.parent / 'src')
    hook_path = str(Path(__file__).parent.parent.parent / 'hooks')
    # Ensure src is at front of path so memory_ts_client resolves correctly
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    if hook_path not in sys.path:
        sys.path.insert(0, hook_path)
    # Force reload to pick up correct memory_ts_client
    if 'memory_ts_client' in sys.modules:
        importlib.reload(sys.modules['memory_ts_client'])
    if 'topic_resumption_detector' in sys.modules:
        importlib.reload(sys.modules['topic_resumption_detector'])
    else:
        import topic_resumption_detector
    return sys.modules['topic_resumption_detector']


def test_hook_phrase_detection():
    """Test hook detects all trigger phrases"""
    topic_resumption_detector = _load_hook_module()
    detect_topic_resumption = topic_resumption_detector.detect_topic_resumption

    test_cases = [
        "We discussed this before, didn't we?",
        "Didn't we talk about messaging frameworks?",
        "Previously we covered this topic",
        "Remember when we talked about hooks?",
        "Last time we discussed the build process",
    ]

    for message in test_cases:
        result = detect_topic_resumption(message)
        assert result is not None
        assert result['detected'] is True


def test_hook_ignores_non_trigger_messages():
    """Test hook ignores non-trigger messages"""
    topic_resumption_detector = _load_hook_module()
    detect_topic_resumption = topic_resumption_detector.detect_topic_resumption

    test_cases = [
        "Let's start a new project",
        "How does this work?",
        "Please help me with this bug",
    ]

    for message in test_cases:
        result = detect_topic_resumption(message)
        assert result is None


def test_hook_keyword_extraction():
    """Test hook extracts relevant topic words"""
    topic_resumption_detector = _load_hook_module()
    detect_topic_resumption = topic_resumption_detector.detect_topic_resumption

    message = "We discussed this before - the messaging framework for Connection Lab"
    result = detect_topic_resumption(message)

    assert result is not None
    keywords = result['context_keywords']

    # Should extract meaningful words
    assert 'messaging' in keywords
    assert 'framework' in keywords
    assert any('connection' in k.lower() for k in keywords)


def test_hook_removes_stopwords():
    """Test hook removes stopwords from keywords"""
    topic_resumption_detector = _load_hook_module()
    detect_topic_resumption = topic_resumption_detector.detect_topic_resumption

    message = "We discussed this before about the authentication system"
    result = detect_topic_resumption(message)

    assert result is not None
    keywords = result['context_keywords']

    # Should not include stopwords
    assert 'the' not in keywords
    assert 'this' not in keywords
    assert 'about' not in keywords


# ========================================
# MEMORY CLIENT INTEGRATION TESTS
# ========================================

@patch.dict(os.environ, {'ENABLE_TEMPORAL_LOGGING': '1'})
def test_memory_client_logs_get_access(temp_memory_dir):
    """Test MemoryTSClient logs get() access"""
    # Create predictor with temp db
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    # Patch the predictor to use our temp db
    with patch('src.wild.temporal_predictor.TemporalPatternPredictor') as mock_predictor_class:
        predictor = TemporalPatternPredictor(db_path=db_path)
        mock_predictor_class.return_value = predictor

        # Create a memory
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        memory = client.create(
            content="Test memory",
            project_id="LFI",
            tags=["test"],
            importance=0.8
        )

        # Clear any logs from create
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM memory_access_log")
            conn.commit()

        # Force re-init of predictor in client
        client._predictor = predictor

        # Get the memory (should log)
        retrieved = client.get(memory.id)

        # Verify access logged
        with sqlite3.connect(db_path) as conn:
            logs = conn.execute(
                "SELECT * FROM memory_access_log WHERE memory_id = ? AND access_type = 'direct'",
                (memory.id,)
            ).fetchall()

            assert len(logs) > 0

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@patch.dict(os.environ, {'ENABLE_TEMPORAL_LOGGING': '1'})
def test_memory_client_logs_search_access(temp_memory_dir):
    """Test MemoryTSClient logs search() access"""
    # Create predictor with temp db
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    # Patch the predictor to use our temp db
    with patch('src.wild.temporal_predictor.TemporalPatternPredictor') as mock_predictor_class:
        predictor = TemporalPatternPredictor(db_path=db_path)
        mock_predictor_class.return_value = predictor

        # Create a memory
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        memory = client.create(
            content="Test messaging framework",
            project_id="LFI",
            tags=["test"],
            importance=0.8
        )

        # Clear any logs from create
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM memory_access_log")
            conn.commit()

        # Force re-init of predictor in client
        client._predictor = predictor

        # Search for the memory (should log)
        results = client.search(content="messaging", project_id="LFI")

        # Verify access logged with context
        with sqlite3.connect(db_path) as conn:
            logs = conn.execute(
                "SELECT context_keywords FROM memory_access_log WHERE memory_id = ? AND access_type = 'search'",
                (memory.id,)
            ).fetchall()

            assert len(logs) > 0
            keywords = json.loads(logs[0][0])
            assert 'messaging' in keywords

    # Cleanup
    Path(db_path).unlink(missing_ok=True)
