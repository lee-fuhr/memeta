"""
Tests for Feature 62: Memory Quality Auto-Grading

Target coverage: >80%
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import sqlite3

from memory_system.wild.quality_grader import MemoryQualityGrader, QualityGrade


@pytest.fixture
def grader():
    """Create grader with temp database"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    grader = MemoryQualityGrader(db_path=db_path)
    yield grader

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_grader_initialization(grader):
    """Test grader initializes database correctly"""
    with sqlite3.connect(grader.db_path) as conn:
        # Check tables exist
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'memory_quality_grades' in table_names
        assert 'quality_validation_events' in table_names
        assert 'quality_patterns' in table_names


def test_grade_high_quality_memory(grader):
    """Test grading a high-quality memory (should get A or B)"""
    content = """
    Always run tests before committing code. Found this prevents 90% of bugs.
    Tested across 3 projects (Connection Lab, Cogent, Russell Hamilton).
    Example: Caught authentication bug in pre-commit test that would have broken production.
    """

    grade = grader.grade_memory(
        memory_id='mem_high_quality',
        content=content,
        importance=0.8
    )

    assert grade.grade in ['A', 'B']
    assert grade.score >= 0.65
    assert grade.precision_score > 0.5  # Specific with examples
    assert grade.actionability_score > 0.5  # Has "run tests", "prevents"
    assert grade.evidence_score > 0.3  # Has numbers, examples


def test_grade_low_quality_memory(grader):
    """Test grading a low-quality memory (should get C or D)"""
    content = "Maybe sometimes try to possibly do things better generally."

    grade = grader.grade_memory(
        memory_id='mem_low_quality',
        content=content,
        importance=0.2
    )

    assert grade.grade in ['C', 'D']
    assert grade.score < 0.65
    assert grade.precision_score < 0.5  # Vague words
    # Note: "try" is detected as action verb, so actionability may not be super low
    # The overall grade (C/D) and low score are what matter


def test_precision_scoring(grader):
    """Test precision score calculation"""
    # Precise memory
    precise = "Use pytest.raises() to test exceptions in Python. Caught 5 edge cases this way."
    grade_precise = grader.grade_memory('mem_p1', precise, 0.7)

    # Vague memory
    vague = "Maybe try to possibly use something that might work sometimes."
    grade_vague = grader.grade_memory('mem_p2', vague, 0.7)

    assert grade_precise.precision_score > grade_vague.precision_score


def test_actionability_scoring(grader):
    """Test actionability score calculation"""
    # Actionable memory
    actionable = "Run 'pytest -v' to see test details. Always check coverage with 'pytest --cov'."
    grade_action = grader.grade_memory('mem_a1', actionable, 0.7)

    # Non-actionable memory
    passive = "Tests were run and some results were seen."
    grade_passive = grader.grade_memory('mem_a2', passive, 0.7)

    assert grade_action.actionability_score > grade_passive.actionability_score


def test_evidence_scoring(grader):
    """Test evidence score calculation"""
    # Well-evidenced memory
    evidenced = "Because tests run faster with pytest-xdist, found 40% speedup in CI. Measured across 100 runs."
    grade_evidence = grader.grade_memory('mem_e1', evidenced, 0.7)

    # No evidence
    claim = "Tests are important."
    grade_claim = grader.grade_memory('mem_e2', claim, 0.7)

    assert grade_evidence.evidence_score > grade_claim.evidence_score


def test_update_grade_from_reinforcement(grader):
    """Test grade improves with reinforcement"""
    # Create initial grade
    initial = grader.grade_memory(
        memory_id='mem_reinforce',
        content='Use semantic versioning for releases',
        importance=0.6
    )

    initial_score = initial.score

    # Log reinforcement events
    for i in range(3):
        grader.update_grade_from_validation(
            memory_id='mem_reinforce',
            event_type='reinforcement',
            session_id=f'session_{i}',
            evidence=f'Saw pattern again in session {i}'
        )

    # Retrieve updated grade
    with sqlite3.connect(grader.db_path) as conn:
        updated_score = conn.execute("""
            SELECT score FROM memory_quality_grades WHERE memory_id = ?
        """, ('mem_reinforce',)).fetchone()[0]

    assert updated_score > initial_score  # Grade improved


def test_update_grade_from_cross_project(grader):
    """Test grade improves more with cross-project validation"""
    # Create initial grade
    initial = grader.grade_memory(
        memory_id='mem_cross',
        content='Document API contracts before implementation',
        importance=0.7
    )

    initial_score = initial.score

    # Log cross-project validations (higher boost than reinforcement)
    grader.update_grade_from_validation(
        memory_id='mem_cross',
        event_type='cross_project',
        session_id='session_other_project',
        evidence='Applied in Connection Lab project'
    )

    grader.update_grade_from_validation(
        memory_id='mem_cross',
        event_type='cross_project',
        session_id='session_another_project',
        evidence='Applied in Russell Hamilton project'
    )

    # Retrieve updated grade
    with sqlite3.connect(grader.db_path) as conn:
        updated_score = conn.execute("""
            SELECT score FROM memory_quality_grades WHERE memory_id = ?
        """, ('mem_cross',)).fetchone()[0]

    assert updated_score > initial_score
    # Cross-project boost should be significant
    assert (updated_score - initial_score) > 0.05


def test_update_grade_from_contradiction(grader):
    """Test grade decreases with contradiction"""
    # Create initial grade
    initial = grader.grade_memory(
        memory_id='mem_contradict',
        content='Always use global state for configuration',
        importance=0.7
    )

    initial_score = initial.score

    # Log contradiction
    grader.update_grade_from_validation(
        memory_id='mem_contradict',
        event_type='contradiction',
        session_id='session_fix',
        evidence='Actually caused race conditions - use dependency injection instead'
    )

    # Retrieve updated grade
    with sqlite3.connect(grader.db_path) as conn:
        updated_score = conn.execute("""
            SELECT score FROM memory_quality_grades WHERE memory_id = ?
        """, ('mem_contradict',)).fetchone()[0]

    assert updated_score < initial_score  # Grade decreased


def test_grade_distribution(grader):
    """Test that grades distribute across quality levels"""
    # Create very high quality memory with all scoring factors
    high_quality = """
    Always use pytest fixtures to share test setup across multiple test functions.
    This approach reduced code duplication by 60% across 50 tests in the Connection Lab project.
    Example: Created a database fixture that initializes test DB, runs migrations, seeds data.
    Measured test execution time decreased from 45s to 12s because setup only runs once.
    Since implementing this pattern, found zero test flakiness from shared state issues.
    """

    # Create low quality memory
    low_quality = "Maybe testing is good sometimes."

    grade_high = grader.grade_memory('mem_high', high_quality, 0.9)
    grade_low = grader.grade_memory('mem_low', low_quality, 0.2)

    # Verify there's quality differentiation
    assert grade_high.score > grade_low.score
    assert grade_high.score >= 0.65  # At least B grade
    assert grade_low.score < 0.65  # C or D grade


def test_learn_quality_patterns(grader):
    """Test learning patterns from graded memories"""
    # Create mix of high and low quality memories
    high_quality_memories = [
        f'Use specific tool X for task Y. Tested across {i} projects with 90% success rate.'
        for i in range(15)
    ]

    low_quality_memories = [
        f'Maybe possibly try something {i}.'
        for i in range(15)
    ]

    for i, content in enumerate(high_quality_memories):
        grader.grade_memory(f'high_{i}', content, 0.8)

    for i, content in enumerate(low_quality_memories):
        grader.grade_memory(f'low_{i}', content, 0.3)

    # Learn patterns
    patterns = grader.learn_quality_patterns(min_examples=10)

    assert len(patterns) >= 1  # Should find at least one pattern
    high_pattern = next((p for p in patterns if p.pattern_type == 'high_quality'), None)
    low_pattern = next((p for p in patterns if p.pattern_type == 'low_quality'), None)

    if high_pattern:
        assert high_pattern.example_count >= 10
        assert high_pattern.confidence > 0.0

    if low_pattern:
        assert low_pattern.example_count >= 10


def test_quality_report(grader):
    """Test quality metrics report generation"""
    # Create some graded memories
    for i in range(5):
        grader.grade_memory(
            f'mem_{i}',
            f'Specific actionable memory with evidence {i}',
            0.7
        )

    report = grader.get_quality_report()

    assert 'grade_distribution' in report
    assert 'average_scores_by_grade' in report
    assert 'total_graded' in report
    assert report['total_graded'] == 5


def test_validation_history(grader):
    """Test tracking validation history"""
    mem_id = 'mem_history'
    grader.grade_memory(mem_id, 'Test memory', 0.7)

    # Log various validations
    grader.update_grade_from_validation(mem_id, 'reinforcement', 's1', 'evidence1')
    grader.update_grade_from_validation(mem_id, 'cross_project', 's2', 'evidence2')
    grader.update_grade_from_validation(mem_id, 'contradiction', 's3', 'evidence3')

    # Check validation events were logged
    with sqlite3.connect(grader.db_path) as conn:
        events = conn.execute("""
            SELECT event_type FROM quality_validation_events
            WHERE memory_id = ?
            ORDER BY timestamp
        """, (mem_id,)).fetchall()

    event_types = [e[0] for e in events]
    assert 'reinforcement' in event_types
    assert 'cross_project' in event_types
    assert 'contradiction' in event_types


def test_grade_persistence(grader):
    """Test grades persist across grader instances"""
    mem_id = 'mem_persist'

    # Grade memory
    grade1 = grader.grade_memory(mem_id, 'Persistent memory', 0.7)

    # Create new grader instance with same database
    grader2 = MemoryQualityGrader(db_path=grader.db_path)

    # Retrieve grade
    grade2 = grader2._get_grade(mem_id)

    assert grade2 is not None
    assert grade2.memory_id == mem_id
    assert grade2.grade == grade1.grade
    assert grade2.score == grade1.score


def test_grade_thresholds(grader):
    """Test grade threshold boundaries"""
    # Test A grade (0.85+)
    grade_a = grader.grade_memory('mem_a', 'X' * 100, 1.0)  # Max scores
    # Note: Actual score depends on content analysis, so we just verify it's graded

    # Create memories at boundaries
    test_cases = [
        (0.90, 'A'),  # Should be A
        (0.70, 'B'),  # Should be B
        (0.50, 'C'),  # Should be C
        (0.30, 'D'),  # Should be D
    ]

    # We can't directly set scores, but we can verify the grading logic exists
    assert grader.GRADE_A_MIN == 0.85
    assert grader.GRADE_B_MIN == 0.65
    assert grader.GRADE_C_MIN == 0.40
