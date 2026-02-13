"""
Tests for Feature 75: Dream Synthesis (Hidden Connections)

Basic tests for initialization and core functionality.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import sqlite3

from src.wild.dream_synthesizer import (
    DreamSynthesizer,
    MemoryNode,
    Connection,
    Synthesis
)


@pytest.fixture
def temp_dbs():
    """Create temporary databases for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        intelligence_db = f.name

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        memory_db = f.name

    yield intelligence_db, memory_db

    # Cleanup
    Path(intelligence_db).unlink(missing_ok=True)
    Path(memory_db).unlink(missing_ok=True)


@pytest.fixture
def synthesizer(temp_dbs):
    """Create synthesizer with temp databases"""
    intelligence_db, memory_db = temp_dbs
    return DreamSynthesizer(db_path=intelligence_db, memory_db_path=memory_db)


def test_synthesizer_initialization(synthesizer):
    """Test synthesizer initializes correctly"""
    assert synthesizer.db_path is not None
    assert synthesizer.memory_db_path is not None
    assert synthesizer.SEMANTIC_THRESHOLD == 0.6
    assert synthesizer.MIN_SUPPORT == 3
    assert synthesizer.MAX_MEMORIES == 1000


def test_constants(synthesizer):
    """Test discovery thresholds are set correctly"""
    assert synthesizer.SEMANTIC_THRESHOLD == 0.6
    assert synthesizer.MIN_SUPPORT == 3
    assert synthesizer.MAX_MEMORIES == 1000
    assert synthesizer.NOVELTY_THRESHOLD == 0.5
    assert synthesizer.TEMPORAL_WINDOW == timedelta(days=7)


def test_get_morning_briefing(synthesizer):
    """Test getting morning briefing"""
    # With empty DB, should return empty list
    briefing = synthesizer.get_morning_briefing(limit=5)

    assert isinstance(briefing, list)
    assert len(briefing) == 0


def test_data_structures():
    """Test data structure creation"""
    # Test MemoryNode
    node = MemoryNode(
        id='mem1',
        content='Test memory',
        project='ProjectA',
        tags=['#test'],
        importance=0.8,
        created_at=datetime.now()
    )

    assert node.id == 'mem1'
    assert node.importance == 0.8

    # Test Connection
    connection = Connection(
        memory_ids=['mem1', 'mem2'],
        connection_type='semantic',
        strength=0.75,
        evidence='Both discuss testing',
        insight='Testing pattern emerges'
    )

    assert connection.connection_type == 'semantic'
    assert connection.strength == 0.75

    # Test Synthesis
    synthesis = Synthesis(
        id='syn1',
        title='Test Synthesis',
        insight='Test insight',
        supporting_memories=['mem1'],
        connections=[connection],
        novelty_score=0.8,
        confidence=0.9,
        projects_spanned=['ProjectA'],
        created_at=datetime.now()
    )

    assert synthesis.novelty_score == 0.8
    assert synthesis.confidence == 0.9
    assert len(synthesis.projects_spanned) == 1
