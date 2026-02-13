"""
Tests for Feature 61: A/B Testing Memory Strategies

Basic tests for initialization and data structures.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile
import sqlite3
import time
import random

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


def test_run_experiment_lifecycle(tester):
    """Test complete experiment lifecycle: create, run, analyze"""
    strategy_a = Strategy(
        id='high_threshold',
        name='High Dedup Threshold',
        description='0.9 threshold for deduplication',
        parameters={'threshold': 0.9}
    )

    strategy_b = Strategy(
        id='low_threshold',
        name='Low Dedup Threshold',
        description='0.7 threshold for deduplication',
        parameters={'threshold': 0.7}
    )

    # Create experiment
    experiment = tester.create_experiment(
        name='Dedup Threshold Test',
        description='Test optimal deduplication threshold',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='precision',
        target_samples=20
    )

    assert experiment.status == ExperimentStatus.PLANNED

    # Mock test function - strategy_a performs better
    def test_func(strategy, session):
        if strategy.id == 'high_threshold':
            return {'precision': 0.85, 'recall': 0.75}
        else:
            return {'precision': 0.70, 'recall': 0.80}

    # Create mock sessions
    sessions = [{'id': f'session_{i}'} for i in range(25)]

    # Run experiment
    tester.run_experiment(experiment.id, test_func, sessions)

    # Check experiment completed
    updated = tester._get_experiment(experiment.id)
    assert updated.status == ExperimentStatus.COMPLETED
    assert updated.started_at is not None
    assert updated.completed_at is not None


def test_analyze_results_determines_winner(tester):
    """Test that analyze_results correctly identifies winning strategy"""
    strategy_a = Strategy(
        id='strategy_high',
        name='High Performer',
        description='Better strategy',
        parameters={'param': 'a'}
    )

    strategy_b = Strategy(
        id='strategy_low',
        name='Low Performer',
        description='Worse strategy',
        parameters={'param': 'b'}
    )

    experiment = tester.create_experiment(
        name='Performance Test',
        description='Test which performs better',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='accuracy',
        target_samples=30
    )

    # Mock test function - A consistently better than B
    def test_func(strategy, session):
        if strategy.id == 'strategy_high':
            return {'accuracy': 0.90}  # High performance
        else:
            return {'accuracy': 0.60}  # Lower performance

    sessions = [{'id': f'session_{i}'} for i in range(35)]
    tester.run_experiment(experiment.id, test_func, sessions)

    # Analyze
    analysis = tester.analyze_results(experiment.id)

    assert analysis['winner'] == 'strategy_a'
    assert analysis['winning_strategy'] == 'High Performer'
    assert analysis['strategy_a']['mean'] > analysis['strategy_b']['mean']
    assert 'improvement_pct' in analysis
    assert 'confidence' in analysis
    assert 'effect_size' in analysis


def test_auto_adoption_high_confidence(tester):
    """Test that high confidence results trigger auto-adoption"""
    strategy_a = Strategy(id='winner', name='Winner', description='', parameters={})
    strategy_b = Strategy(id='loser', name='Loser', description='', parameters={})

    experiment = tester.create_experiment(
        name='Auto Adopt Test',
        description='Should auto-adopt',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='score',
        target_samples=50
    )

    # Large sample (30+) with large effect size (>0.8) triggers high confidence
    # Add variance to avoid zero std deviation
    def test_func(strategy, session):
        session_num = int(session['id'].split('_')[1])
        if strategy.id == 'winner':
            # High scores with small variance
            return {'score': 0.95 + (session_num % 5) * 0.01}
        else:
            # Low scores with small variance
            return {'score': 0.20 + (session_num % 5) * 0.01}

    sessions = [{'id': f's_{i}'} for i in range(50)]
    tester.run_experiment(experiment.id, test_func, sessions)

    analysis = tester.analyze_results(experiment.id)

    # Should auto-adopt with high confidence (Cohen's d > 0.8, n >= 30)
    assert analysis['adopted'] is True
    updated = tester._get_experiment(experiment.id)
    assert updated.status == ExperimentStatus.ADOPTED
    assert updated.adopted_at is not None


def test_insufficient_data_handling(tester):
    """Test handling of experiments with no results"""
    strategy_a = Strategy(id='a', name='A', description='', parameters={})
    strategy_b = Strategy(id='b', name='B', description='', parameters={})

    experiment = tester.create_experiment(
        name='Empty Test',
        description='No data',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='metric',
        target_samples=10
    )

    # Analyze without running
    analysis = tester.analyze_results(experiment.id)

    assert 'error' in analysis
    assert analysis['error'] == 'Insufficient data'


def test_get_experiment_history(tester):
    """Test retrieving completed experiment history"""
    # Create and complete an experiment
    strategy_a = Strategy(id='hist_a', name='A', description='', parameters={})
    strategy_b = Strategy(id='hist_b', name='B', description='', parameters={})

    experiment = tester.create_experiment(
        name='Historical Test',
        description='For history',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='value',
        target_samples=15
    )

    def test_func(strategy, session):
        return {'value': 0.5}

    sessions = [{'id': f's_{i}'} for i in range(15)]
    tester.run_experiment(experiment.id, test_func, sessions)
    tester.analyze_results(experiment.id)

    # Get history
    history = tester.get_experiment_history(days=30)

    assert len(history) > 0
    assert any(h['id'] == experiment.id for h in history)

    hist_entry = next(h for h in history if h['id'] == experiment.id)
    assert 'name' in hist_entry
    assert 'winner' in hist_entry
    assert 'confidence' in hist_entry
    assert 'completed_at' in hist_entry
    assert 'adopted' in hist_entry


def test_variant_assignment_balanced(tester):
    """Test that both variants run on all sessions"""
    strategy_a = Strategy(id='var_a', name='Variant A', description='', parameters={})
    strategy_b = Strategy(id='var_b', name='Variant B', description='', parameters={})

    experiment = tester.create_experiment(
        name='Balance Test',
        description='Check balanced execution',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='metric',
        target_samples=10
    )

    call_count = {'var_a': 0, 'var_b': 0}

    def test_func(strategy, session):
        call_count[strategy.id] += 1
        return {'metric': 0.5}

    sessions = [{'id': f's_{i}'} for i in range(10)]
    tester.run_experiment(experiment.id, test_func, sessions)

    # Both strategies should run on all 10 sessions
    assert call_count['var_a'] == 10
    assert call_count['var_b'] == 10


def test_multiple_metrics_recorded(tester):
    """Test that multiple metrics are recorded per result"""
    strategy_a = Strategy(id='multi_a', name='A', description='', parameters={})
    strategy_b = Strategy(id='multi_b', name='B', description='', parameters={})

    experiment = tester.create_experiment(
        name='Multi-Metric Test',
        description='Multiple metrics per session',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='primary',
        target_samples=5
    )

    def test_func(strategy, session):
        return {
            'primary': 0.8,
            'secondary': 0.6,
            'tertiary': 0.7
        }

    sessions = [{'id': f's_{i}'} for i in range(5)]
    tester.run_experiment(experiment.id, test_func, sessions)

    # Check all metrics were saved
    with sqlite3.connect(tester.db_path) as conn:
        metrics = conn.execute("""
            SELECT DISTINCT metric_name FROM ab_results
            WHERE experiment_id = ?
        """, (experiment.id,)).fetchall()

        metric_names = [m[0] for m in metrics]
        assert 'primary' in metric_names
        assert 'secondary' in metric_names
        assert 'tertiary' in metric_names


def test_result_persistence(tester):
    """Test that results are properly persisted to database"""
    strategy_a = Strategy(id='persist_a', name='A', description='', parameters={})
    strategy_b = Strategy(id='persist_b', name='B', description='', parameters={})

    experiment = tester.create_experiment(
        name='Persistence Test',
        description='Check DB persistence',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='score',
        target_samples=3
    )

    def test_func(strategy, session):
        return {'score': 0.75}

    sessions = [{'id': f's_{i}'} for i in range(3)]
    tester.run_experiment(experiment.id, test_func, sessions)

    # Verify results in database
    with sqlite3.connect(tester.db_path) as conn:
        results = conn.execute("""
            SELECT strategy_id, session_id, metric_name, metric_value
            FROM ab_results
            WHERE experiment_id = ?
            ORDER BY strategy_id, session_id
        """, (experiment.id,)).fetchall()

        # Should have 6 results (2 strategies * 3 sessions)
        assert len(results) == 6

        # Check strategy IDs are correct
        strategy_ids = [r[0] for r in results]
        assert strategy_ids.count('persist_a') == 3
        assert strategy_ids.count('persist_b') == 3


def test_active_experiments_filter(tester):
    """Test that get_active_experiments only returns planned/running experiments"""
    # Create planned experiment
    strategy_a1 = Strategy(id='active_a1', name='S1', description='', parameters={})
    strategy_b1 = Strategy(id='active_b1', name='S2', description='', parameters={})
    planned = tester.create_experiment(
        name='Planned',
        description='',
        strategy_a=strategy_a1,
        strategy_b=strategy_b1,
        success_metric='m',
        target_samples=5
    )

    # Delay to ensure different timestamp for experiment ID (format uses seconds)
    time.sleep(1.1)

    # Create and complete another
    strategy_a2 = Strategy(id='active_a2', name='S3', description='', parameters={})
    strategy_b2 = Strategy(id='active_b2', name='S4', description='', parameters={})
    completed = tester.create_experiment(
        name='Completed',
        description='',
        strategy_a=strategy_a2,
        strategy_b=strategy_b2,
        success_metric='m',
        target_samples=5
    )

    def test_func(s, sess):
        return {'m': 0.5}

    tester.run_experiment(completed.id, test_func, [{'id': 's1'}])

    # Get active
    active = tester.get_active_experiments()

    # Only planned should be active
    assert len(active) == 1
    assert active[0].id == planned.id
    assert active[0].status in [ExperimentStatus.PLANNED, ExperimentStatus.RUNNING]


def test_winner_determination_strategy_b(tester):
    """Test that strategy_b can win when it performs better"""
    strategy_a = Strategy(id='weak', name='Weak', description='', parameters={})
    strategy_b = Strategy(id='strong', name='Strong', description='', parameters={})

    experiment = tester.create_experiment(
        name='B Wins Test',
        description='Strategy B should win',
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        success_metric='performance',
        target_samples=20
    )

    def test_func(strategy, session):
        if strategy.id == 'weak':
            return {'performance': 0.40}
        else:
            return {'performance': 0.85}

    sessions = [{'id': f's_{i}'} for i in range(25)]
    tester.run_experiment(experiment.id, test_func, sessions)

    analysis = tester.analyze_results(experiment.id)

    assert analysis['winner'] == 'strategy_b'
    assert analysis['winning_strategy'] == 'Strong'
    assert analysis['strategy_b']['mean'] > analysis['strategy_a']['mean']
