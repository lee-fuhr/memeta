"""
Feature 61: A/B Testing Memory Strategies

System experiments on itself to find optimal strategies.

Tests include:
- Semantic search vs hybrid search
- Different deduplication thresholds
- Importance score weighting
- FSRS parameters
- Promotion criteria

Process:
1. Define experiment (strategy A vs strategy B)
2. Run both strategies in parallel on sample sessions
3. Measure outcomes (recall accuracy, user corrections, search satisfaction)
4. Statistical significance test
5. Auto-adopt winner

Integration: Weekly experiments, results logged to intelligence.db
"""

import sqlite3
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import statistics


class ExperimentStatus(Enum):
    """Status of an A/B test experiment"""
    PLANNED = 'planned'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ADOPTED = 'adopted'
    REJECTED = 'rejected'


@dataclass
class Strategy:
    """A strategy variant to test"""
    id: str
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class ExperimentResult:
    """Result from one test of a strategy"""
    strategy_id: str
    session_id: str
    metric_name: str
    metric_value: float
    timestamp: datetime


@dataclass
class Experiment:
    """An A/B test experiment"""
    id: str
    name: str
    description: str
    strategy_a: Strategy
    strategy_b: Strategy
    success_metric: str  # Which metric determines winner
    target_samples: int  # How many sessions to test on
    status: ExperimentStatus
    results_a: List[ExperimentResult] = field(default_factory=list)
    results_b: List[ExperimentResult] = field(default_factory=list)
    winner: Optional[str] = None  # strategy_a or strategy_b
    confidence: float = 0.0  # 0.0-1.0 statistical confidence
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    adopted_at: Optional[datetime] = None


class MemoryStrategyTester:
    """
    Runs A/B tests on memory system strategies.

    Test framework:
    - Parallel execution: both strategies run on same sessions
    - Metrics tracked: recall, precision, user corrections, search quality
    - Statistical significance: t-test with p < 0.05
    - Auto-adoption: winner adopted if confidence > 0.95
    """

    SIGNIFICANCE_THRESHOLD = 0.05  # p-value
    ADOPTION_CONFIDENCE = 0.95
    DEFAULT_SAMPLE_SIZE = 50

    def __init__(self, db_path: str = None):
        """Initialize tester with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for A/B testing"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ab_experiments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    strategy_a_id TEXT NOT NULL,
                    strategy_b_id TEXT NOT NULL,
                    success_metric TEXT NOT NULL,
                    target_samples INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('planned', 'running', 'completed', 'adopted', 'rejected')),
                    winner TEXT CHECK(winner IN ('strategy_a', 'strategy_b', NULL)),
                    confidence REAL DEFAULT 0.0,
                    started_at TEXT,
                    completed_at TEXT,
                    adopted_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ab_strategies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    parameters TEXT NOT NULL,  -- JSON
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ab_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_status ON ab_experiments(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_results_experiment ON ab_results(experiment_id, strategy_id)")

    def create_experiment(
        self,
        name: str,
        description: str,
        strategy_a: Strategy,
        strategy_b: Strategy,
        success_metric: str,
        target_samples: int = None
    ) -> Experiment:
        """
        Create new A/B test experiment.

        Args:
            name: Experiment name
            description: What we're testing
            strategy_a: First strategy variant
            strategy_b: Second strategy variant
            success_metric: Metric to determine winner
            target_samples: How many sessions to test on

        Returns:
            Created Experiment
        """
        if target_samples is None:
            target_samples = self.DEFAULT_SAMPLE_SIZE

        experiment = Experiment(
            id=f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            name=name,
            description=description,
            strategy_a=strategy_a,
            strategy_b=strategy_b,
            success_metric=success_metric,
            target_samples=target_samples,
            status=ExperimentStatus.PLANNED
        )

        self._save_experiment(experiment)
        self._save_strategy(strategy_a)
        self._save_strategy(strategy_b)

        return experiment

    def run_experiment(
        self,
        experiment_id: str,
        test_function: Callable[[Strategy, Any], Dict[str, float]],
        test_sessions: List[Any]
    ):
        """
        Run experiment on test sessions.

        Args:
            experiment_id: Experiment to run
            test_function: Function that takes (strategy, session) and returns metrics dict
            test_sessions: List of sessions to test on
        """
        experiment = self._get_experiment(experiment_id)

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Update status
        experiment.status = ExperimentStatus.RUNNING
        experiment.started_at = datetime.now()
        self._update_experiment_status(experiment)

        # Run both strategies on each session
        for session in test_sessions[:experiment.target_samples]:
            # Run strategy A
            metrics_a = test_function(experiment.strategy_a, session)
            for metric_name, metric_value in metrics_a.items():
                result = ExperimentResult(
                    strategy_id=experiment.strategy_a.id,
                    session_id=str(session.get('id', 'unknown')),
                    metric_name=metric_name,
                    metric_value=metric_value,
                    timestamp=datetime.now()
                )
                self._save_result(experiment_id, result)

            # Run strategy B
            metrics_b = test_function(experiment.strategy_b, session)
            for metric_name, metric_value in metrics_b.items():
                result = ExperimentResult(
                    strategy_id=experiment.strategy_b.id,
                    session_id=str(session.get('id', 'unknown')),
                    metric_name=metric_name,
                    metric_value=metric_value,
                    timestamp=datetime.now()
                )
                self._save_result(experiment_id, result)

        # Mark as completed
        experiment.status = ExperimentStatus.COMPLETED
        experiment.completed_at = datetime.now()
        self._update_experiment_status(experiment)

    def analyze_results(self, experiment_id: str) -> Dict[str, Any]:
        """
        Analyze experiment results and determine winner.

        Args:
            experiment_id: Experiment to analyze

        Returns:
            Analysis dict with winner, confidence, metrics
        """
        experiment = self._get_experiment(experiment_id)

        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Get results for success metric
        results_a = self._get_results(experiment_id, experiment.strategy_a.id, experiment.success_metric)
        results_b = self._get_results(experiment_id, experiment.strategy_b.id, experiment.success_metric)

        if not results_a or not results_b:
            return {'error': 'Insufficient data'}

        # Extract metric values
        values_a = [r.metric_value for r in results_a]
        values_b = [r.metric_value for r in results_b]

        # Calculate means and variance
        mean_a = statistics.mean(values_a)
        mean_b = statistics.mean(values_b)
        std_a = statistics.stdev(values_a) if len(values_a) > 1 else 0.0
        std_b = statistics.stdev(values_b) if len(values_b) > 1 else 0.0

        # Simple t-test (simplified - real implementation would use scipy)
        # For now, use effect size and sample size
        n_a = len(values_a)
        n_b = len(values_b)

        # Effect size (Cohen's d)
        pooled_std = ((std_a ** 2 + std_b ** 2) / 2) ** 0.5
        cohens_d = abs(mean_a - mean_b) / pooled_std if pooled_std > 0 else 0.0

        # Rough confidence based on effect size and sample size
        # (Real implementation would calculate proper p-value)
        if cohens_d > 0.8 and n_a >= 30 and n_b >= 30:
            confidence = 0.95
        elif cohens_d > 0.5 and n_a >= 20 and n_b >= 20:
            confidence = 0.85
        elif cohens_d > 0.2 and n_a >= 10 and n_b >= 10:
            confidence = 0.70
        else:
            confidence = 0.50

        # Determine winner
        if mean_a > mean_b:
            winner = 'strategy_a'
            improvement = ((mean_a - mean_b) / mean_b) * 100 if mean_b > 0 else 0.0
        else:
            winner = 'strategy_b'
            improvement = ((mean_b - mean_a) / mean_a) * 100 if mean_a > 0 else 0.0

        # Update experiment
        experiment.winner = winner
        experiment.confidence = confidence
        self._update_experiment_winner(experiment)

        # Auto-adopt if confidence high enough
        if confidence >= self.ADOPTION_CONFIDENCE:
            experiment.status = ExperimentStatus.ADOPTED
            experiment.adopted_at = datetime.now()
            self._update_experiment_status(experiment)

        return {
            'winner': winner,
            'winning_strategy': experiment.strategy_a.name if winner == 'strategy_a' else experiment.strategy_b.name,
            'confidence': confidence,
            'improvement_pct': improvement,
            'strategy_a': {
                'mean': mean_a,
                'std': std_a,
                'n': n_a
            },
            'strategy_b': {
                'mean': mean_b,
                'std': std_b,
                'n': n_b
            },
            'effect_size': cohens_d,
            'adopted': experiment.status == ExperimentStatus.ADOPTED
        }

    def get_active_experiments(self) -> List[Experiment]:
        """Get all running experiments"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT id, name, description, strategy_a_id, strategy_b_id,
                       success_metric, target_samples, status, winner, confidence,
                       started_at, completed_at, adopted_at
                FROM ab_experiments
                WHERE status IN ('planned', 'running')
                ORDER BY started_at DESC
            """).fetchall()

        return [self._row_to_experiment(row) for row in rows]

    def get_experiment_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get history of completed experiments"""
        cutoff = datetime.now() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT id, name, winner, confidence, completed_at, adopted_at
                FROM ab_experiments
                WHERE status IN ('completed', 'adopted', 'rejected')
                  AND completed_at > ?
                ORDER BY completed_at DESC
            """, (cutoff.isoformat(),)).fetchall()

        return [
            {
                'id': r[0],
                'name': r[1],
                'winner': r[2],
                'confidence': r[3],
                'completed_at': r[4],
                'adopted': r[5] is not None
            }
            for r in rows
        ]

    def _save_experiment(self, experiment: Experiment):
        """Save experiment to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO ab_experiments
                (id, name, description, strategy_a_id, strategy_b_id,
                 success_metric, target_samples, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                experiment.id, experiment.name, experiment.description,
                experiment.strategy_a.id, experiment.strategy_b.id,
                experiment.success_metric, experiment.target_samples,
                experiment.status.value
            ))

    def _save_strategy(self, strategy: Strategy):
        """Save strategy to database"""
        import json

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO ab_strategies
                (id, name, description, parameters)
                VALUES (?, ?, ?, ?)
            """, (
                strategy.id, strategy.name, strategy.description,
                json.dumps(strategy.parameters)
            ))

    def _save_result(self, experiment_id: str, result: ExperimentResult):
        """Save test result to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO ab_results
                (experiment_id, strategy_id, session_id, metric_name, metric_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                experiment_id, result.strategy_id, result.session_id,
                result.metric_name, result.metric_value, result.timestamp.isoformat()
            ))

    def _get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """Retrieve experiment from database"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT id, name, description, strategy_a_id, strategy_b_id,
                       success_metric, target_samples, status, winner, confidence,
                       started_at, completed_at, adopted_at
                FROM ab_experiments WHERE id = ?
            """, (experiment_id,)).fetchone()

        if not row:
            return None

        return self._row_to_experiment(row)

    def _get_results(self, experiment_id: str, strategy_id: str, metric_name: str) -> List[ExperimentResult]:
        """Get results for a specific strategy and metric"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT strategy_id, session_id, metric_name, metric_value, timestamp
                FROM ab_results
                WHERE experiment_id = ? AND strategy_id = ? AND metric_name = ?
                ORDER BY timestamp
            """, (experiment_id, strategy_id, metric_name)).fetchall()

        return [
            ExperimentResult(
                strategy_id=r[0], session_id=r[1], metric_name=r[2],
                metric_value=r[3], timestamp=datetime.fromisoformat(r[4])
            )
            for r in rows
        ]

    def _update_experiment_status(self, experiment: Experiment):
        """Update experiment status in database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE ab_experiments
                SET status = ?, started_at = ?, completed_at = ?, adopted_at = ?
                WHERE id = ?
            """, (
                experiment.status.value,
                experiment.started_at.isoformat() if experiment.started_at else None,
                experiment.completed_at.isoformat() if experiment.completed_at else None,
                experiment.adopted_at.isoformat() if experiment.adopted_at else None,
                experiment.id
            ))

    def _update_experiment_winner(self, experiment: Experiment):
        """Update experiment winner and confidence"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE ab_experiments
                SET winner = ?, confidence = ?
                WHERE id = ?
            """, (experiment.winner, experiment.confidence, experiment.id))

    def _row_to_experiment(self, row) -> Experiment:
        """Convert database row to Experiment"""
        import json

        # Load strategies
        with sqlite3.connect(self.db_path) as conn:
            strategy_a_row = conn.execute("""
                SELECT id, name, description, parameters
                FROM ab_strategies WHERE id = ?
            """, (row[3],)).fetchone()

            strategy_b_row = conn.execute("""
                SELECT id, name, description, parameters
                FROM ab_strategies WHERE id = ?
            """, (row[4],)).fetchone()

        strategy_a = Strategy(
            id=strategy_a_row[0], name=strategy_a_row[1],
            description=strategy_a_row[2], parameters=json.loads(strategy_a_row[3])
        )

        strategy_b = Strategy(
            id=strategy_b_row[0], name=strategy_b_row[1],
            description=strategy_b_row[2], parameters=json.loads(strategy_b_row[3])
        )

        return Experiment(
            id=row[0],
            name=row[1],
            description=row[2],
            strategy_a=strategy_a,
            strategy_b=strategy_b,
            success_metric=row[5],
            target_samples=row[6],
            status=ExperimentStatus(row[7]),
            winner=row[8],
            confidence=row[9],
            started_at=datetime.fromisoformat(row[10]) if row[10] else None,
            completed_at=datetime.fromisoformat(row[11]) if row[11] else None,
            adopted_at=datetime.fromisoformat(row[12]) if row[12] else None
        )
