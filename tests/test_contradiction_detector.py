"""
Tests for contradiction_detector.py
"""

import pytest
from memory_system.contradiction_detector import (
    check_contradictions,
    find_similar_memories,
    check_contradiction,
    ContradictionResult
)


def test_find_similar_memories():
    """Test finding similar memories by word overlap"""
    new_memory = "I prefer morning meetings at 9am"

    existing = [
        {'id': '1', 'content': 'I prefer afternoon meetings at 2pm'},
        {'id': '2', 'content': 'Client wants bold colorful design'},
        {'id': '3', 'content': 'Morning standup meetings work best'},
        {'id': '4', 'content': 'Use Python for all scripts'},
    ]

    similar = find_similar_memories(new_memory, existing, top_n=3)

    # Should find the two memories about meetings
    assert len(similar) > 0
    assert similar[0]['id'] in ['1', '3']  # Most similar should be about meetings


def test_check_contradictions_no_existing():
    """Test contradiction check with no existing memories"""
    result = check_contradictions("I prefer morning meetings", [])

    assert result.contradicts is False
    assert result.action == "save"
    assert result.contradicted_memory is None


def test_check_contradictions_compatible():
    """Test contradiction check with compatible memories"""
    new_memory = "I prefer morning meetings"

    existing = [
        {'id': '1', 'content': 'I like coffee in the morning'},
        {'id': '2', 'content': 'Morning is my most productive time'},
    ]

    result = check_contradictions(new_memory, existing)

    # These should be compatible (not contradictory)
    assert result.contradicts is False
    assert result.action == "save"


def test_contradiction_result_dataclass():
    """Test ContradictionResult dataclass"""
    result = ContradictionResult(
        contradicts=True,
        contradicted_memory={'id': '123', 'content': 'Old preference'},
        action="replace"
    )

    assert result.contradicts is True
    assert result.action == "replace"
    assert result.contradicted_memory['id'] == '123'


def test_find_similar_memories_empty():
    """Test with empty inputs"""
    assert find_similar_memories("", [{'id': '1', 'content': 'test'}]) == []
    assert find_similar_memories("test", []) == []


def test_find_similar_memories_no_overlap():
    """Test when there's no word overlap"""
    new_memory = "Python programming language"
    existing = [{'id': '1', 'content': 'xyz abc def'}]

    similar = find_similar_memories(new_memory, existing)
    assert len(similar) == 0  # No overlap, should return empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
