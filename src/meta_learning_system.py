"""
Features 48-50: Meta-Learning System

48. A/B testing memory strategies
49. Cross-system learning
50. Dream mode (overnight consolidation)

System improves itself through experimentation and learning.
"""

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Callable

from .intelligence_db import IntelligenceDB
from .memory_ts_client import MemoryTSClient
from .pattern_detector import PatternDetector
from .llm_extractor import extract_with_llm


@dataclass
class ABTestResult:
    """A/B test experiment result"""
    test_name: str
    strategy_a_name: str
    strategy_b_name: str
    started_at: str
    ended_at: Optional[str] = None
    sample_size: int = 0
    strategy_a_performance: float = 0.0
    strategy_b_performance: float = 0.0
    winner: Optional[str] = None
    adopted: bool = False


class MemoryABTesting:
    """
    Feature 48: A/B test memory strategies

    Experiment with different approaches:
    - Semantic vs hybrid search
    - Different importance scoring algorithms
    - Extraction prompt variants
    - Pattern detection thresholds

    Measure: recall accuracy, user corrections, satisfaction
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize A/B testing system"""
        self.db = IntelligenceDB(db_path)

    def start_test(
        self,
        test_name: str,
        strategy_a_name: str,
        strategy_b_name: str,
        sample_size: int = 100
    ) -> int:
        """
        Start new A/B test

        Args:
            test_name: Name of experiment
            strategy_a_name: Name of strategy A
            strategy_b_name: Name of strategy B
            sample_size: Number of samples to collect

        Returns:
            Test ID
        """
        cursor = self.db.conn.cursor()

        cursor.execute("""
            INSERT INTO ab_tests
            (test_name, strategy_a_name, strategy_b_name, started_at, sample_size)
            VALUES (?, ?, ?, ?, ?)
        """, (
            test_name,
            strategy_a_name,
            strategy_b_name,
            datetime.now().isoformat(),
            sample_size
        ))

        test_id = cursor.lastrowid
        self.db.conn.commit()

        return test_id

    def record_performance(
        self,
        test_id: int,
        strategy_a_performance: float,
        strategy_b_performance: float
    ):
        """
        Record performance metrics for both strategies

        Args:
            test_id: Test ID
            strategy_a_performance: Performance score for A (0.0-1.0)
            strategy_b_performance: Performance score for B (0.0-1.0)
        """
        cursor = self.db.conn.cursor()

        # Determine winner
        if abs(strategy_a_performance - strategy_b_performance) < 0.05:
            winner = "tie"
        elif strategy_a_performance > strategy_b_performance:
            winner = "a"
        else:
            winner = "b"

        cursor.execute("""
            UPDATE ab_tests
            SET strategy_a_performance = ?,
                strategy_b_performance = ?,
                winner = ?,
                ended_at = ?
            WHERE id = ?
        """, (
            strategy_a_performance,
            strategy_b_performance,
            winner,
            datetime.now().isoformat(),
            test_id
        ))

        self.db.conn.commit()

    def adopt_winner(self, test_id: int):
        """Mark winning strategy as adopted"""
        cursor = self.db.conn.cursor()

        cursor.execute("""
            UPDATE ab_tests
            SET adopted = 1
            WHERE id = ?
        """, (test_id,))

        self.db.conn.commit()

    def get_active_tests(self) -> List[Dict]:
        """Get currently running tests"""
        cursor = self.db.conn.cursor()

        cursor.execute("""
            SELECT * FROM ab_tests
            WHERE ended_at IS NULL
            ORDER BY started_at DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_test_results(self, test_id: int) -> Optional[Dict]:
        """Get results for a specific test"""
        cursor = self.db.conn.cursor()

        cursor.execute("SELECT * FROM ab_tests WHERE id = ?", (test_id,))
        result = cursor.fetchone()

        return dict(result) if result else None


class CrossSystemLearning:
    """
    Feature 49: Cross-system learning

    Import best practices from other AI assistants:
    - Ben's Kit patterns
    - Other memory-ts users
    - Open source examples

    Privacy-aware: only import patterns, not data.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize cross-system learning"""
        self.db = IntelligenceDB(db_path)
        self.memory_client = MemoryTSClient()

    def import_pattern(
        self,
        source_system: str,
        pattern_type: str,
        pattern_description: str,
        save_to_memory_ts: bool = True
    ) -> int:
        """
        Import pattern from another system

        Args:
            source_system: Where pattern came from (e.g., "Ben's Kit")
            pattern_type: Category (e.g., "extraction", "search", "workflow")
            pattern_description: What the pattern is
            save_to_memory_ts: Also save as memory

        Returns:
            Import ID
        """
        cursor = self.db.conn.cursor()

        cursor.execute("""
            INSERT INTO cross_system_imports
            (source_system, pattern_type, pattern_description, imported_at)
            VALUES (?, ?, ?, ?)
        """, (
            source_system,
            pattern_type,
            pattern_description,
            datetime.now().isoformat()
        ))

        import_id = cursor.lastrowid
        self.db.conn.commit()

        # Save to memory-ts
        if save_to_memory_ts:
            try:
                self.memory_client.create(
                    content=f"Learned from {source_system}: {pattern_description}",
                    tags=['#cross-system-learning', f'#source-{source_system.lower().replace(" ", "-")}'],
                    project_id="LFI",
                    importance=0.7
                )
            except Exception as e:
                print(f"Warning: Failed to save to memory-ts: {e}")

        return import_id

    def mark_adapted(self, import_id: int, adaptation_notes: str):
        """Mark pattern as adapted to our system"""
        cursor = self.db.conn.cursor()

        cursor.execute("""
            UPDATE cross_system_imports
            SET adapted = 1, adaptation_notes = ?
            WHERE id = ?
        """, (adaptation_notes, import_id))

        self.db.conn.commit()

    def rate_effectiveness(self, import_id: int, score: float):
        """Rate how well an imported pattern works (0.0-1.0)"""
        cursor = self.db.conn.cursor()

        cursor.execute("""
            UPDATE cross_system_imports
            SET effectiveness_score = ?
            WHERE id = ?
        """, (score, import_id))

        self.db.conn.commit()

    def get_effective_patterns(self, min_score: float = 0.7) -> List[Dict]:
        """Get patterns that work well"""
        cursor = self.db.conn.cursor()

        cursor.execute("""
            SELECT * FROM cross_system_imports
            WHERE effectiveness_score >= ?
            ORDER BY effectiveness_score DESC
        """, (min_score,))

        return [dict(row) for row in cursor.fetchall()]


class DreamMode:
    """
    Feature 50: Dream mode - Overnight memory consolidation

    Extends nightly_optimizer.py with:
    - Re-process today's sessions while idle
    - Find deeper patterns across ALL memories
    - Synthesize non-obvious connections
    - Strengthen important memories
    - Morning insights report
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize dream mode"""
        self.db = IntelligenceDB(db_path)
        self.memory_client = MemoryTSClient()
        self.pattern_detector = PatternDetector()

    def consolidate_overnight(
        self,
        lookback_days: int = 1,
        save_insights: bool = True
    ) -> Dict:
        """
        Overnight memory consolidation

        Args:
            lookback_days: How many days to analyze
            save_insights: Save to intelligence DB

        Returns:
            Consolidation results
        """
        start_time = datetime.now()

        # Get recent memories
        cutoff = datetime.now() - timedelta(days=lookback_days)

        try:
            recent_memories = self.memory_client.search(
                query="*",  # All memories
                min_timestamp=cutoff.isoformat()
            )
        except Exception:
            recent_memories = []

        if not recent_memories:
            return {
                'memories_analyzed': 0,
                'patterns_found': [],
                'deep_insights': "No recent memories to analyze",
                'new_connections': 0
            }

        # Detect patterns across memories
        patterns = []
        try:
            for memory in recent_memories[:50]:  # Limit to avoid timeout
                pattern_matches = self.pattern_detector.find_patterns(
                    memory.get('content', ''),
                    memory.get('project_id', 'LFI')
                )
                patterns.extend(pattern_matches)
        except Exception as e:
            print(f"Warning: Pattern detection failed: {e}")

        # Deduplicate patterns
        unique_patterns = list({p['pattern']: p for p in patterns}.values())

        # LLM synthesis: find non-obvious connections
        deep_insights = ""
        if len(recent_memories) >= 5:
            try:
                memory_summary = "\n".join([
                    f"- {m.get('content', '')[:100]}"
                    for m in recent_memories[:20]
                ])

                prompt = f"""Analyze these recent memories and find non-obvious patterns or connections:

{memory_summary}

What surprising insights emerge? What am I learning without realizing it?
What connections exist between seemingly unrelated memories?

Provide 3-5 key insights."""

                deep_insights = extract_with_llm(prompt, project_id="LFI")
            except Exception as e:
                deep_insights = f"LLM synthesis unavailable: {e}"

        # Count new connections (approximation)
        new_connections = len(unique_patterns)

        # Save to intelligence DB
        if save_insights:
            cursor = self.db.conn.cursor()

            cursor.execute("""
                INSERT INTO dream_insights
                (run_date, memories_analyzed, patterns_found, deep_insights, new_connections, runtime_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().date().isoformat(),
                len(recent_memories),
                json.dumps([p['pattern'] for p in unique_patterns]),
                deep_insights,
                new_connections,
                (datetime.now() - start_time).total_seconds()
            ))

            self.db.conn.commit()

        return {
            'memories_analyzed': len(recent_memories),
            'patterns_found': [p['pattern'] for p in unique_patterns],
            'deep_insights': deep_insights,
            'new_connections': new_connections,
            'runtime_seconds': (datetime.now() - start_time).total_seconds()
        }

    def get_morning_report(self) -> str:
        """
        Generate morning insights report from last night's consolidation

        Returns:
            Markdown-formatted report
        """
        cursor = self.db.conn.cursor()

        # Get last night's dream insights
        cursor.execute("""
            SELECT * FROM dream_insights
            ORDER BY run_date DESC
            LIMIT 1
        """)

        result = cursor.fetchone()

        if not result:
            return "No overnight consolidation run yet."

        data = dict(result)

        report = f"""# 🌙 Overnight Memory Consolidation

**Date:** {data['run_date']}
**Memories analyzed:** {data['memories_analyzed']}
**New connections found:** {data['new_connections']}
**Runtime:** {data['runtime_seconds']:.1f}s

## Patterns Detected

{chr(10).join(f"- {p}" for p in json.loads(data['patterns_found'])[:10])}

## Deep Insights

{data['deep_insights']}

---
*Dream mode ran while you slept*
"""

        return report

    def close(self):
        """Close database connection"""
        self.db.close()
