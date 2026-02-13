"""
Quick tests for F29-F32 automation features
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from automation.alerts import SmartAlerts
from automation.search import MemoryAwareSearch, SearchQuery
from automation.summarization import AutoSummarization, TopicSummary
from automation.quality import QualityScoring
from memory_ts_client import Memory


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


# F29: Smart Alerts Tests

def test_f29_create_alert(temp_db):
    """Test creating an alert."""
    alerts = SmartAlerts(db_path=temp_db)

    alert = alerts.create_alert(
        alert_type="contradiction",
        severity="high",
        title="Test Alert",
        message="Test message",
        memory_ids=["mem_001"]
    )

    assert alert.alert_id > 0
    assert alert.title == "Test Alert"
    assert alert.severity == "high"


def test_f29_get_pending_alerts(temp_db):
    """Test getting pending alerts."""
    alerts = SmartAlerts(db_path=temp_db)

    alerts.create_alert("test", "high", "Alert 1", "msg", ["mem_001"])
    alerts.create_alert("test", "low", "Alert 2", "msg", ["mem_002"])

    pending = alerts.get_unread_alerts()

    assert len(pending) == 2


def test_f29_mark_delivered(temp_db):
    """Test marking alert as delivered."""
    alerts = SmartAlerts(db_path=temp_db)
    
    alert = alerts.create_alert("test", "medium", "Test", "msg", ["mem_001"])
    
    alerts.dismiss_alert(alert.alert_id)

    pending = alerts.get_unread_alerts()
    assert len(pending) == 0


# F30: Memory-Aware Search Tests

def test_f30_search_query_dataclass():
    """Test SearchQuery dataclass."""
    query = SearchQuery(
        text_query="test",
        min_importance=0.7,
        limit=10
    )
    
    assert query.text_query == "test"
    assert query.min_importance == 0.7


def test_f30_parse_natural_query():
    """Test parsing natural language query."""
    search = MemoryAwareSearch()
    
    query = search.parse_natural_query("Find important memories from last week")
    
    assert query.text_query is not None
    assert query.date_start is not None  # Should parse "last week"
    assert query.min_importance == 0.7  # Should parse "important"


# F31: Auto-Summarization Tests

def test_f31_summarize_empty_memories():
    """Test summarizing with no memories."""
    summarizer = AutoSummarization()
    
    summary = summarizer.summarize_topic("test", [])
    
    assert summary.topic == "test"
    assert summary.memory_count == 0
    assert "No memories" in summary.narrative


def test_f31_topic_summary_dataclass():
    """Test TopicSummary dataclass."""
    summary = TopicSummary(
        summary_id=None,
        topic="test",
        narrative="Test narrative",
        timeline=[],
        key_insights=["insight 1"],
        memory_count=5,
        created_at=datetime.now(),
        memory_ids=["mem_001"]
    )

    assert summary.topic == "test"
    assert len(summary.key_insights) == 1


# F32: Quality Scoring Tests

def test_f32_assess_high_quality_memory():
    """Test assessing a high-quality memory."""
    scorer = QualityScoring()
    
    memory = Memory(
        id="mem_001",
        content="Always verify tests pass before claiming completion.",
        importance=0.8,
        project_id="LFI",
        tags=[]
    )
    
    assessment = scorer.assess_memory(memory)
    
    assert assessment.score > 0.7
    assert len(assessment.issues) == 0


def test_f32_assess_low_quality_memory():
    """Test assessing a low-quality memory."""
    scorer = QualityScoring()
    
    memory = Memory(
        id="mem_002",
        content="maybe do stuff",  # Vague, short, no capitals, incomplete
        importance=0.3,
        project_id="LFI",
        tags=[]
    )
    
    assessment = scorer.assess_memory(memory)

    assert assessment.score < 0.8  # Low quality should score below 0.8
    assert len(assessment.issues) > 0


def test_f32_find_low_quality():
    """Test finding low-quality memories in batch."""
    scorer = QualityScoring()
    
    memories = [
        Memory("m1", "High quality memory with specific details.", 0.8, [], "LFI"),
        Memory("m2", "bad", 0.3, [], "LFI"),  # Low quality
        Memory("m3", "Another well-formed memory with clear action.", 0.9, [], "LFI"),
    ]
    
    low_quality = scorer.find_low_quality(memories, threshold=0.8)
    
    assert len(low_quality) == 1
    assert low_quality[0].memory_id == "m2"


def test_f32_quality_score_dataclass():
    """Test QualityScore dataclass."""
    from automation.quality import QualityScore
    
    score = QualityScore(
        memory_id="mem_001",
        score=0.85,
        issues=[],
        suggestions=[]
    )
    
    assert score.memory_id == "mem_001"
    assert score.score == 0.85
