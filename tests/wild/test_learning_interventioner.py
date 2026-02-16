"""Tests for F64: Learning Intervention System"""

import pytest
import tempfile
import os

from memory_system.wild.learning_interventioner import LearningInterventioner, LearningIntervention


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def interventioner(temp_db):
    return LearningInterventioner(temp_db)


def test_interventioner_initialization(interventioner):
    assert interventioner is not None


def test_record_question(interventioner):
    count = interventioner.record_question("How do I use feature X?")
    assert count == 1


def test_record_question_increments(interventioner):
    interventioner.record_question("How do I use feature X?")
    count = interventioner.record_question("How do I use feature X?")
    assert count == 2


def test_detect_repeated_question_none(interventioner):
    intervention = interventioner.detect_repeated_question("New question?")
    assert intervention is None


def test_detect_repeated_question_exists(interventioner):
    interventioner.record_question("How do I use feature X?")
    intervention = interventioner.detect_repeated_question("How do I use feature X?")
    assert intervention is not None


def test_create_tutorial(interventioner):
    tutorial = interventioner.create_tutorial("Feature X")
    assert "Tutorial" in tutorial
    assert "Feature X" in tutorial


def test_create_reference(interventioner):
    reference = interventioner.create_reference("Feature X API")
    assert "Reference" in reference
    assert "Feature X API" in reference


def test_save_intervention(interventioner):
    intervention_id = interventioner.save_intervention(
        "How to use X?",
        "tutorial",
        "Tutorial content"
    )
    assert intervention_id is not None


def test_mark_helped(interventioner):
    intervention_id = interventioner.save_intervention(
        "How to use X?",
        "tutorial",
        "Content"
    )
    interventioner.mark_helped(intervention_id, True)


def test_get_interventions_empty(interventioner):
    interventions = interventioner.get_interventions(min_occurrences=3)
    assert interventions == []


def test_get_interventions_with_data(interventioner):
    for _ in range(5):
        interventioner.record_question("Repeated question?")
    
    interventions = interventioner.get_interventions(min_occurrences=3)
    assert len(interventions) == 1


def test_get_statistics(interventioner):
    interventioner.record_question("Q1")
    interventioner.record_question("Q2")
    
    stats = interventioner.get_statistics()
    assert stats["total_questions"] >= 2
