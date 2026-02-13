"""
Tests for Feature 61: A/B Testing Memory Strategies

Basic tests for initialization and data structures.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import sqlite3

from src.wild.ab_tester import (
    MemoryStrategyTester,
    Strategy,
    Experiment,
    ExperimentStatus,
    ExperimentResult
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def tester(temp_db):
    """Create tester with temp database"""
    return MemoryStrategyTester(db_path=temp_db)


def test_tester_initialization(tester):
    """Test tester initializes database correctly"""
    with sqlite3.connect(tester.db_path) as conn:
        # Check tables exist
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'ab_experiments' in table_names
        assert 'ab_strategies' in table_names
        assert 'ab_results' in table_names


def test_create_experiment(tester):
    """Test creating a new A/B experiment"""
    strategy_a = Strategy(
        id='semantic_search',
        name='Semantic Search',
        description='Use embeddings for semantic matching',
        parameters={'model': 'all-MiniLM-L6-v2', 'top_k': 10}
    )

    strategy_b = Strategy(
        id='keyword_search',
        name='Keyword Search',
        description='Use BM25 for keyword matching',
        parameters={'threshold': 0.7}
    )

    experiment = tester.create_experiment(
        name='Search Strategy Comparison',
        description='Compare semantic vs keyword search',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='recall_accuracy',
        target_samples=50
    )

    assert experiment.id.startswith('exp_')
    assert experiment.name == 'Search Strategy Comparison'
    assert experiment.status == ExperimentStatus.PLANNED
    assert experiment.target_samples == 50
    assert experiment.strategy_a.id == 'semantic_search'
    assert experiment.strategy_b.id == 'keyword_search'


def test_get_active_experiments(tester):
    """Test retrieving active experiments"""
    experiments = tester.get_active_experiments()

    assert isinstance(experiments, list)
    # Empty DB means no active experiments
    assert len(experiments) == 0


def test_constants(tester):
    """Test class constants are set correctly"""
    assert tester.SIGNIFICANCE_THRESHOLD == 0.05
    assert tester.ADOPTION_CONFIDENCE == 0.95
    assert tester.DEFAULT_SAMPLE_SIZE == 50
