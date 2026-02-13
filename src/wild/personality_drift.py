"""
Feature 35: Personality drift detection

Track communication style evolution over time.
Detect intentional changes vs unintentional drift.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import sys
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

from wild.intelligence_db import IntelligenceDB
from memory_ts_client import MemoryTSClient


def analyze_communication_style(memories: List, sample_size: int = 100) -> Dict:
    """
    Analyze communication style from recent memories

    Returns directness, verbosity, and formality scores (0.0-1.0)
    """
    if not memories:
        return {'directness': 0.5, 'verbosity': 0.5, 'formality': 0.5, 'sample_size': 0}

    sample = memories[:sample_size] if len(memories) > sample_size else memories

    directness_score = _calculate_directness(sample)
    verbosity_score = _calculate_verbosity(sample)
    formality_score = _calculate_formality(sample)

    return {
        'directness': directness_score,
        'verbosity': verbosity_score,
        'formality': formality_score,
        'sample_size': len(sample)
    }


def _calculate_directness(memories: List) -> float:
    """
    Calculate directness score (0.0 = indirect, 1.0 = very direct)

    Direct indicators: imperatives, short sentences, lack of qualifiers
    """
    total_score = 0
    count = 0

    for mem in memories:
        content = mem.content if hasattr(mem, 'content') else str(mem)
        score = 0.5  # Baseline

        # Direct language indicators
        if any(word in content.lower() for word in ['just', 'simply', 'only', 'directly']):
            score += 0.1
        if any(phrase in content.lower() for phrase in ['don\'t', 'never', 'always', 'must']):
            score += 0.15

        # Indirect language (reduces score)
        if any(word in content.lower() for word in ['perhaps', 'might', 'maybe', 'possibly', 'could']):
            score -= 0.1
        if any(phrase in content.lower() for phrase in ['i think', 'in my opinion', 'sort of']):
            score -= 0.15

        total_score += max(0, min(1, score))
        count += 1

    return total_score / count if count > 0 else 0.5


def _calculate_verbosity(memories: List) -> float:
    """
    Calculate verbosity score (0.0 = concise, 1.0 = verbose)

    Based on average word count per memory
    """
    word_counts = []
    for mem in memories:
        content = mem.content if hasattr(mem, 'content') else str(mem)
        word_counts.append(len(content.split()))

    if not word_counts:
        return 0.5

    avg_words = sum(word_counts) / len(word_counts)

    # Scale: <20 words = very concise (0.0), >100 words = very verbose (1.0)
    if avg_words < 20:
        return 0.0
    elif avg_words > 100:
        return 1.0
    else:
        return (avg_words - 20) / 80


def _calculate_formality(memories: List) -> float:
    """
    Calculate formality score (0.0 = casual, 1.0 = formal)
    """
    total_score = 0
    count = 0

    for mem in memories:
        content = mem.content if hasattr(mem, 'content') else str(mem)
        score = 0.5  # Baseline

        # Casual indicators (reduce score)
        if any(word in content.lower() for word in ['gonna', 'wanna', 'yeah', 'ok', 'cool']):
            score -= 0.2
        if re.search(r'[!]{2,}', content):  # Multiple exclamation marks
            score -= 0.1

        # Formal indicators (increase score)
        if any(word in content for word in ['Therefore', 'Furthermore', 'Additionally', 'Consequently']):
            score += 0.2
        if len([s for s in content.split('.') if len(s.strip()) > 50]) > 2:  # Long sentences
            score += 0.1

        total_score += max(0, min(1, score))
        count += 1

    return total_score / count if count > 0 else 0.5


def record_personality_snapshot(window_days: int = 30,
                                memory_dir: Optional[Path] = None,
                                db_path: Optional[Path] = None) -> Dict:
    """
    Take a personality snapshot and save to database

    Args:
        window_days: Days of memories to analyze
        memory_dir: Optional memory-ts path
        db_path: Optional database path

    Returns:
        Personality snapshot dict
    """
    client = MemoryTSClient(memory_dir)
    all_memories = client.search()

    cutoff = datetime.now() - timedelta(days=window_days)
    recent = [m for m in all_memories if datetime.fromisoformat(m.created) > cutoff]

    metrics = analyze_communication_style(recent, sample_size=100)

    date = datetime.now().strftime('%Y-%m-%d')

    with IntelligenceDB(db_path) as db:
        db.record_personality_snapshot(
            date=date,
            directness=metrics['directness'],
            verbosity=metrics['verbosity'],
            formality=metrics['formality'],
            sample_size=metrics['sample_size']
        )

    metrics['date'] = date
    return metrics


def detect_drift(days: int = 180, db_path: Optional[Path] = None) -> Dict:
    """
    Detect personality drift over time

    Returns drift magnitude and whether it appears intentional
    """
    with IntelligenceDB(db_path) as db:
        history = db.get_personality_evolution(days=days)

    if len(history) < 2:
        return {
            'drift_detected': False,
            'message': 'Insufficient data (need at least 2 snapshots)'
        }

    # Compare recent vs baseline
    baseline = history[0]  # Oldest
    recent = history[-1]   # Newest

    directness_drift = recent['directness_score'] - baseline['directness_score']
    verbosity_drift = recent['verbosity_score'] - baseline['verbosity_score']
    formality_drift = recent['formality_score'] - baseline['formality_score']

    # Calculate magnitude (Euclidean distance in 3D space)
    magnitude = (directness_drift**2 + verbosity_drift**2 + formality_drift**2)**0.5

    # Determine if intentional (steady progression) or drift (erratic)
    midpoint_count = max(1, len(history) // 2)
    midpoint_avg = {
        'directness': sum(h['directness_score'] for h in history[:midpoint_count]) / midpoint_count,
        'verbosity': sum(h['verbosity_score'] for h in history[:midpoint_count]) / midpoint_count,
        'formality': sum(h['formality_score'] for h in history[:midpoint_count]) / midpoint_count
    }

    # If midpoint is between baseline and recent, it's intentional progression
    directness_linear = (baseline['directness_score'] < midpoint_avg['directness'] < recent['directness_score'] or
                         baseline['directness_score'] > midpoint_avg['directness'] > recent['directness_score'])

    is_intentional = directness_linear and magnitude > 0.1

    return {
        'drift_detected': magnitude > 0.1,
        'magnitude': magnitude,
        'is_intentional': is_intentional,
        'directness_change': directness_drift,
        'verbosity_change': verbosity_drift,
        'formality_change': formality_drift,
        'baseline_date': baseline['date'],
        'recent_date': recent['date'],
        'datapoints': len(history)
    }
