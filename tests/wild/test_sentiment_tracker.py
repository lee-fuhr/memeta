"""
Tests for sentiment_tracker.py (Feature 33)
"""

import pytest
from memory_system.wild.sentiment_tracker import (
    analyze_sentiment,
    get_sentiment_trends,
    get_sentiment_timeline,
    should_trigger_optimization
)


def test_analyze_sentiment_frustrated():
    """Test frustration detection"""
    content = "This is annoying and doesn't work. It's a mistake."
    sentiment, triggers = analyze_sentiment(content)

    assert sentiment == 'frustrated'
    assert triggers is not None
    assert 'annoying' in triggers or 'mistake' in triggers


def test_analyze_sentiment_satisfied():
    """Test satisfaction detection"""
    content = "This is perfect! Great work, exactly what I wanted."
    sentiment, triggers = analyze_sentiment(content)

    assert sentiment == 'satisfied'
    assert triggers is not None
    assert 'perfect' in triggers or 'great' in triggers


def test_analyze_sentiment_neutral():
    """Test neutral sentiment"""
    content = "The system processes the data correctly."
    sentiment, triggers = analyze_sentiment(content)

    assert sentiment == 'neutral'
    assert triggers is None


def test_sentiment_trends_empty():
    """Test trends with no data"""
    trends = get_sentiment_trends(days=30)

    assert trends['total'] == 0
    assert trends['frustration_rate'] == 0.0
    assert trends['trend'] == 'neutral'


def test_should_trigger_optimization():
    """Test optimization trigger logic"""
    # High frustration should trigger
    result = should_trigger_optimization(threshold=0.2)
    assert 'should_optimize' in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
