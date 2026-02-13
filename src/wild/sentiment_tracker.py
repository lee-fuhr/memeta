"""
Feature 33: Sentiment tracking

Detect frustration/satisfaction trends over time.
Track emotional tone of corrections and user interactions.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from wild.intelligence_db import IntelligenceDB


# Sentiment trigger words
FRUSTRATION_KEYWORDS = [
    'frustrated', 'annoying', 'annoyed', 'wrong', 'mistake', 'error', 'broken',
    'doesn\'t work', 'failed', 'failing', 'not working', 'stuck', 'confused',
    'why did', 'keep making', 'stop doing', 'don\'t do that', 'incorrect',
    'missed', 'overlooked', 'ignored', 'waste', 'wasted time', 'redo', 'again'
]

SATISFACTION_KEYWORDS = [
    'great', 'perfect', 'excellent', 'love', 'brilliant', 'exactly', 'spot on',
    'nice', 'good', 'helpful', 'useful', 'works', 'working well', 'thank you',
    'thanks', 'appreciate', 'impressed', 'fantastic', 'awesome', 'wonderful'
]


def analyze_sentiment(content: str) -> Tuple[str, Optional[str]]:
    """
    Detect sentiment from content

    Args:
        content: Text to analyze (memory content, correction, etc.)

    Returns:
        Tuple of (sentiment, trigger_words)
        sentiment: 'frustrated' | 'satisfied' | 'neutral'
        trigger_words: Comma-separated list of matched keywords (or None)
    """
    content_lower = content.lower()

    # Check for frustration signals
    frustration_matches = [kw for kw in FRUSTRATION_KEYWORDS if kw in content_lower]
    if frustration_matches:
        return 'frustrated', ', '.join(frustration_matches[:3])  # Limit to first 3

    # Check for satisfaction signals
    satisfaction_matches = [kw for kw in SATISFACTION_KEYWORDS if kw in content_lower]
    if satisfaction_matches:
        return 'satisfied', ', '.join(satisfaction_matches[:3])

    return 'neutral', None


def track_memory_sentiment(memory: Dict, session_id: str, db_path: Optional[Path] = None):
    """
    Analyze and log sentiment for a memory

    Args:
        memory: Memory dict with 'id' and 'content'
        session_id: Session identifier
        db_path: Optional database path
    """
    content = memory.get('content', '')
    sentiment, triggers = analyze_sentiment(content)

    with IntelligenceDB(db_path) as db:
        db.log_sentiment(
            session_id=session_id,
            sentiment=sentiment,
            trigger_words=triggers,
            context=content[:200],  # First 200 chars for context
            memory_id=memory.get('id')
        )


def get_sentiment_trends(days: int = 30, db_path: Optional[Path] = None) -> Dict:
    """
    Get sentiment trend analysis

    Args:
        days: Number of days to analyze
        db_path: Optional database path

    Returns:
        Dict with sentiment statistics and trends
    """
    with IntelligenceDB(db_path) as db:
        history = db.get_sentiment_history(days=days)

    if not history:
        return {
            'total': 0,
            'frustrated': 0,
            'satisfied': 0,
            'neutral': 0,
            'frustration_rate': 0.0,
            'satisfaction_rate': 0.0,
            'trend': 'neutral',
            'common_triggers': []
        }

    # Count sentiments
    counts = {'frustrated': 0, 'satisfied': 0, 'neutral': 0}
    for entry in history:
        counts[entry['sentiment']] += 1

    total = len(history)
    frustration_rate = counts['frustrated'] / total
    satisfaction_rate = counts['satisfied'] / total

    # Analyze trend (compare last week to previous weeks)
    cutoff = datetime.now() - timedelta(days=7)
    recent = [h for h in history if datetime.fromisoformat(h['timestamp']) > cutoff]
    older = [h for h in history if datetime.fromisoformat(h['timestamp']) <= cutoff]

    recent_frustration = sum(1 for h in recent if h['sentiment'] == 'frustrated') / len(recent) if recent else 0
    older_frustration = sum(1 for h in older if h['sentiment'] == 'frustrated') / len(older) if older else 0

    # Determine trend
    if recent_frustration > older_frustration + 0.1:
        trend = 'worsening'
    elif recent_frustration < older_frustration - 0.1:
        trend = 'improving'
    else:
        trend = 'stable'

    # Extract common frustration triggers
    frustration_entries = [h for h in history if h['sentiment'] == 'frustrated' and h['trigger_words']]
    all_triggers = []
    for entry in frustration_entries:
        if entry['trigger_words']:
            all_triggers.extend(entry['trigger_words'].split(', '))

    # Count trigger frequency
    trigger_counts = {}
    for trigger in all_triggers:
        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

    # Top 5 triggers
    common_triggers = sorted(trigger_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        'total': total,
        'frustrated': counts['frustrated'],
        'satisfied': counts['satisfied'],
        'neutral': counts['neutral'],
        'frustration_rate': frustration_rate,
        'satisfaction_rate': satisfaction_rate,
        'trend': trend,
        'common_triggers': [{'trigger': t, 'count': c} for t, c in common_triggers],
        'window_days': days
    }


def get_sentiment_timeline(days: int = 30, db_path: Optional[Path] = None) -> List[Dict]:
    """
    Get day-by-day sentiment breakdown

    Args:
        days: Number of days to analyze
        db_path: Optional database path

    Returns:
        List of daily sentiment summaries
    """
    with IntelligenceDB(db_path) as db:
        history = db.get_sentiment_history(days=days)

    # Group by date
    daily_counts = {}
    for entry in history:
        date = entry['timestamp'][:10]  # YYYY-MM-DD
        if date not in daily_counts:
            daily_counts[date] = {'frustrated': 0, 'satisfied': 0, 'neutral': 0}
        daily_counts[date][entry['sentiment']] += 1

    # Convert to timeline
    timeline = []
    for date, counts in sorted(daily_counts.items()):
        total = sum(counts.values())
        timeline.append({
            'date': date,
            'frustrated': counts['frustrated'],
            'satisfied': counts['satisfied'],
            'neutral': counts['neutral'],
            'total': total,
            'frustration_rate': counts['frustrated'] / total if total > 0 else 0
        })

    return timeline


def should_trigger_optimization(threshold: float = 0.3, days: int = 7,
                               db_path: Optional[Path] = None) -> Dict:
    """
    Check if frustration rate warrants system optimization

    Args:
        threshold: Frustration rate threshold (0.0-1.0)
        days: Window to check
        db_path: Optional database path

    Returns:
        Dict with trigger status and reasoning
    """
    trends = get_sentiment_trends(days=days, db_path=db_path)

    if trends['frustration_rate'] >= threshold:
        return {
            'should_optimize': True,
            'reason': f"Frustration rate {trends['frustration_rate']:.1%} exceeds threshold {threshold:.1%}",
            'common_issues': trends['common_triggers'][:3],
            'recommendation': 'Review recent corrections and identify root causes'
        }

    if trends['trend'] == 'worsening':
        return {
            'should_optimize': True,
            'reason': f"Frustration trend is worsening (current rate: {trends['frustration_rate']:.1%})",
            'common_issues': trends['common_triggers'][:3],
            'recommendation': 'System behavior may be degrading - investigate recent changes'
        }

    return {
        'should_optimize': False,
        'reason': f"Frustration rate {trends['frustration_rate']:.1%} is below threshold",
        'current_trend': trends['trend']
    }
