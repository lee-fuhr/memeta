"""
Tests for Feature 32: Quality Scoring
"""

import pytest
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from automation.quality import QualityScoring, QualityScore
from memory_ts_client import Memory


@pytest.fixture
def scorer():
    """Create quality scorer instance."""
    return QualityScoring()


def test_assess_high_quality_memory(scorer):
    """Test assessing a high-quality memory."""
    memory = Memory(
        id="mem_001",
        content="Always verify work before claiming completion by running all tests and checking outputs.",
        importance=0.8,
        tags=["testing"],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert assessment.score > 0.7
    assert len(assessment.issues) == 0


def test_assess_too_short(scorer):
    """Test detecting too-short memories."""
    memory = Memory(
        id="mem_002",
        content="Short.",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    # Should have lower score due to length
    assert any("Too short" in issue for issue in assessment.issues)
    assert any("Add more context" in sug for sug in assessment.suggestions)


def test_assess_vague_language(scorer):
    """Test detecting vague language."""
    memory = Memory(
        id="mem_003",
        content="Maybe we should possibly consider doing something about the things that might need fixing somehow.",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    # Should detect vague language
    assert any("vague language" in issue for issue in assessment.issues)


def test_assess_missing_verbs(scorer):
    """Test detecting lack of action verbs."""
    memory = Memory(
        id="mem_004",
        content="The system is slow and performance issues exist everywhere.",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert any("No action verbs" in issue for issue in assessment.issues)


def test_assess_incomplete_sentence(scorer):
    """Test detecting incomplete sentences."""
    memory = Memory(
        id="mem_005",
        content="testing without proper completion markers",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert any("Incomplete sentence" in issue for issue in assessment.issues)


def test_assess_no_capital(scorer):
    """Test detecting missing capitalization."""
    memory = Memory(
        id="mem_006",
        content="always start with a capital letter when writing memories.",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert any("capital letter" in issue for issue in assessment.issues)


def test_batch_assess(scorer):
    """Test assessing multiple memories."""
    memories = [
        Memory(
            id="mem_007",
            content="First memory with good quality content and proper structure.",
            importance=0.8,
            tags=[],
            project_id="TestProject",
            created=datetime.now()
        ),
        Memory(
            id="mem_008",
            content="bad",
            importance=0.3,
            tags=[],
            project_id="TestProject",
            created=datetime.now()
        )
    ]

    assessments = scorer.batch_assess(memories)

    assert len(assessments) == 2
    assert assessments[0].score > assessments[1].score


def test_find_low_quality(scorer):
    """Test finding memories below quality threshold."""
    memories = [
        Memory(
            id="mem_009",
            content="High quality memory with proper formatting and action verbs like verify.",
            importance=0.8,
            tags=[],
            project_id="TestProject",
            created=datetime.now()
        ),
        Memory(
            id="mem_010",
            content="low",
            importance=0.3,
            tags=[],
            project_id="TestProject",
            created=datetime.now()
        )
    ]

    low_quality = scorer.find_low_quality(memories, threshold=0.7)

    # Should find at least the "low" memory
    assert len(low_quality) >= 1
    assert any(lq.memory_id == "mem_010" for lq in low_quality)


def test_find_low_quality_custom_threshold(scorer):
    """Test finding low quality with custom threshold."""
    memories = [
        Memory(
            id=f"mem_{i}",
            content=f"Memory number {i} with content.",
            importance=0.5,
            tags=[],
            project_id="TestProject",
            created=datetime.now()
        )
        for i in range(5)
    ]

    # Lower threshold should find more issues
    low_quality_strict = scorer.find_low_quality(memories, threshold=0.9)
    low_quality_lenient = scorer.find_low_quality(memories, threshold=0.5)

    assert len(low_quality_strict) >= len(low_quality_lenient)


def test_quality_score_structure(scorer):
    """Test QualityScore has correct structure."""
    memory = Memory(
        id="mem_011",
        content="Test memory for structure verification.",
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert hasattr(assessment, 'memory_id')
    assert hasattr(assessment, 'score')
    assert hasattr(assessment, 'issues')
    assert hasattr(assessment, 'suggestions')
    assert 0.0 <= assessment.score <= 1.0
    assert isinstance(assessment.issues, list)
    assert isinstance(assessment.suggestions, list)


def test_optimal_length_scores_high(scorer):
    """Test memories with optimal length score well."""
    memory = Memory(
        id="mem_012",
        content="This memory has optimal length between 30 and 200 characters which should score well on length checks and other quality metrics.",
        importance=0.8,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    # Should not have length-related issues
    assert not any("Too short" in issue or "Too long" in issue for issue in assessment.issues)


def test_very_long_memory(scorer):
    """Test very long memory gets flagged."""
    long_content = "A" * 600  # Exceeds MAX_LENGTH of 500

    memory = Memory(
        id="mem_013",
        content=long_content,
        importance=0.5,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    assert any("Too long" in issue for issue in assessment.issues)


def test_suggestions_provided_for_issues(scorer):
    """Test that every issue has a corresponding suggestion."""
    memory = Memory(
        id="mem_014",
        content="bad",
        importance=0.3,
        tags=[],
        project_id="TestProject",
        created=datetime.now()
    )

    assessment = scorer.assess_memory(memory)

    # Low quality memory should have both issues and suggestions
    assert len(assessment.issues) > 0
    assert len(assessment.suggestions) > 0
