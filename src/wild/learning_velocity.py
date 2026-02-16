"""
Feature 34: Learning velocity metrics

Measure how fast the system improves by tracking correction rates over time.
Lower correction rate = better system performance.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

from memory_system.wild.intelligence_db import IntelligenceDB
from memory_system.memory_ts_client import MemoryTSClient


def calculate_velocity_metrics(window_days: int = 30,
                               memory_dir: Optional[Path] = None,
                               db_path: Optional[Path] = None) -> Dict:
    """
    Calculate learning velocity for a time window

    Args:
        window_days: Number of days to analyze
        memory_dir: Optional path to memory-ts directory
        db_path: Optional path to intelligence database

    Returns:
        Dict with velocity metrics
    """
    client = MemoryTSClient(memory_dir)
    all_memories = client.search()  # Returns all memories when no filters

    cutoff = datetime.now() - timedelta(days=window_days)

    # Filter to recent memories
    recent = [
        m for m in all_memories
        if datetime.fromisoformat(m.created) > cutoff
    ]

    if not recent:
        return {
            'total_memories': 0,
            'corrections': 0,
            'correction_rate': 0.0,
            'velocity_score': 0.0,
            'status': 'no_data',
            'window_days': window_days
        }

    # Count corrections (memories with 'correction' or 'mistake' tags/categories)
    corrections = sum(1 for m in recent if _is_correction(m))

    correction_rate = corrections / len(recent)

    # Velocity score: inverse of correction rate (lower corrections = higher velocity)
    # Scale 0-100 where 100 = no corrections, 0 = all corrections
    velocity_score = max(0, (1.0 - correction_rate) * 100)

    # Status assessment
    if correction_rate < 0.1:
        status = 'excellent'  # <10% corrections
    elif correction_rate < 0.2:
        status = 'good'       # 10-20% corrections
    elif correction_rate < 0.3:
        status = 'fair'       # 20-30% corrections
    else:
        status = 'needs_improvement'  # >30% corrections

    metrics = {
        'total_memories': len(recent),
        'corrections': corrections,
        'correction_rate': correction_rate,
        'velocity_score': velocity_score,
        'status': status,
        'window_days': window_days,
        'date': datetime.now().strftime('%Y-%m-%d')
    }

    # Save to database
    with IntelligenceDB(db_path) as db:
        db.record_velocity(
            date=metrics['date'],
            total_memories=metrics['total_memories'],
            corrections=metrics['corrections'],
            velocity_score=metrics['velocity_score'],
            window_days=window_days
        )

    return metrics


def _is_correction(memory) -> bool:
    """Check if memory represents a correction"""
    # Check tags
    if hasattr(memory, 'tags'):
        correction_tags = {'correction', 'mistake', 'error', 'wrong', 'fix', 'redo'}
        if any(tag.lower() in correction_tags for tag in memory.tags):
            return True

    # Check content
    content_lower = memory.content.lower()
    correction_phrases = [
        'don\'t do', 'stop doing', 'instead of', 'not ', 'wrong',
        'mistake', 'error', 'incorrect', 'should have', 'missed',
        'overlooked', 'forgot to', 'failed to'
    ]
    return any(phrase in content_lower for phrase in correction_phrases)


def get_velocity_trend(days: int = 90, db_path: Optional[Path] = None) -> Dict:
    """
    Analyze velocity trend over extended period

    Args:
        days: Number of days to analyze
        db_path: Optional database path

    Returns:
        Dict with trend analysis
    """
    with IntelligenceDB(db_path) as db:
        history = db.get_velocity_trend(days=days)

    if len(history) < 2:
        return {
            'trend': 'insufficient_data',
            'datapoints': len(history),
            'message': 'Need at least 2 velocity measurements for trend analysis'
        }

    # Calculate acceleration (change in velocity over time)
    recent_velocity = sum(h['velocity_score'] for h in history[-7:]) / min(7, len(history))
    older_velocity = sum(h['velocity_score'] for h in history[:7]) / min(7, len(history))

    acceleration = recent_velocity - older_velocity

    # Determine trend
    if acceleration > 10:
        trend = 'accelerating'  # Improving significantly
    elif acceleration > 2:
        trend = 'improving'     # Gradual improvement
    elif acceleration > -2:
        trend = 'stable'        # No significant change
    elif acceleration > -10:
        trend = 'declining'     # Gradual decline
    else:
        trend = 'degrading'     # Significant decline

    return {
        'trend': trend,
        'acceleration': acceleration,
        'recent_velocity': recent_velocity,
        'older_velocity': older_velocity,
        'datapoints': len(history),
        'improvement_percent': (acceleration / older_velocity * 100) if older_velocity > 0 else 0,
        'history': history
    }


def get_correction_breakdown(window_days: int = 30,
                             memory_dir: Optional[Path] = None) -> Dict:
    """
    Break down corrections by category

    Args:
        window_days: Number of days to analyze
        memory_dir: Optional path to memory-ts directory

    Returns:
        Dict with correction categories and counts
    """
    client = MemoryTSClient(memory_dir)
    all_memories = client.search()  # Returns all memories when no filters

    cutoff = datetime.now() - timedelta(days=window_days)
    recent_corrections = [
        m for m in all_memories
        if datetime.fromisoformat(m.created) > cutoff and _is_correction(m)
    ]

    if not recent_corrections:
        return {
            'total': 0,
            'by_category': {},
            'common_patterns': []
        }

    # Group by category/domain
    by_category = {}
    for mem in recent_corrections:
        category = mem.knowledge_domain if hasattr(mem, 'knowledge_domain') else 'unknown'
        by_category[category] = by_category.get(category, 0) + 1

    # Extract common correction patterns
    content_words = []
    for mem in recent_corrections:
        # Extract key phrases from content (simple word frequency)
        words = mem.content.lower().split()
        content_words.extend([w for w in words if len(w) > 4])  # Words longer than 4 chars

    # Count word frequency
    word_counts = {}
    for word in content_words:
        word_counts[word] = word_counts.get(word, 0) + 1

    # Top patterns
    common_patterns = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        'total': len(recent_corrections),
        'by_category': by_category,
        'common_patterns': [{'term': term, 'count': count} for term, count in common_patterns],
        'window_days': window_days
    }


def get_roi_estimate(days: int = 90, db_path: Optional[Path] = None) -> Dict:
    """
    Estimate ROI of memory system based on velocity improvements

    Args:
        days: Analysis window
        db_path: Optional database path

    Returns:
        Dict with ROI metrics
    """
    trend = get_velocity_trend(days=days, db_path=db_path)

    if trend['trend'] == 'insufficient_data':
        return {
            'roi': 'unknown',
            'message': 'Insufficient data for ROI calculation'
        }

    # Rough estimate: each 10-point velocity improvement = 5% time savings
    # (fewer corrections = less rework = more productive sessions)
    improvement_percent = trend.get('improvement_percent', 0)
    time_savings_percent = improvement_percent * 0.5

    # Assuming 40 hours/week of Claude Code usage
    hours_per_week = 40
    hours_saved_per_week = hours_per_week * (time_savings_percent / 100)

    return {
        'velocity_improvement': f"{improvement_percent:.1f}%",
        'estimated_time_savings': f"{time_savings_percent:.1f}%",
        'hours_saved_per_week': f"{hours_saved_per_week:.1f}h",
        'trend': trend['trend'],
        'current_velocity': trend['recent_velocity'],
        'baseline_velocity': trend['older_velocity'],
        'analysis_period_days': days
    }
