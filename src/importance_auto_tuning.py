"""
Memory importance auto-tuning based on recall frequency.

Feature 12: Adaptive decay - memories recalled frequently get higher importance,
rarely-recalled memories decay faster.

Theory: If you keep asking about something, it's important. If it never comes up, lower priority.
"""

from typing import Dict
import time


def calculate_adaptive_importance(
    base_importance: float,
    recall_count: int,
    days_since_creation: int,
    days_since_last_recall: int
) -> float:
    """
    Calculate importance with adaptive tuning.

    Args:
        base_importance: Initial importance score (0.0-1.0)
        recall_count: Number of times memory has been recalled
        days_since_creation: Days since memory was created
        days_since_last_recall: Days since last recall (or creation if never recalled)

    Returns:
        Adjusted importance (0.0-1.0)
    """
    # Start with base importance
    importance = base_importance

    # Boost for frequent recall (up to +0.2)
    if recall_count > 0:
        recall_boost = min(0.2, recall_count * 0.02)
        importance += recall_boost

    # Decay over time (0.99^days) but slower if frequently recalled
    if days_since_last_recall > 0:
        # Memories recalled recently decay slower
        decay_rate = 0.99 if recall_count < 3 else 0.995

        # Apply decay based on days since last recall
        time_decay = decay_rate ** days_since_last_recall
        importance *= time_decay

    # Never go below 0.1 or above 1.0
    return max(0.1, min(1.0, importance))


def should_boost_importance(
    memory: Dict,
    recall_threshold: int = 3,
    days_threshold: int = 7
) -> bool:
    """
    Check if memory should get importance boost.

    Criteria: Recalled 3+ times in past 7 days.

    Args:
        memory: Memory dict with recall_count and last_recalled timestamp
        recall_threshold: Minimum recalls to boost
        days_threshold: Days window for recent recalls

    Returns:
        True if should boost
    """
    recall_count = memory.get('recall_count', 0)

    if recall_count < recall_threshold:
        return False

    # Check if recalls are recent
    last_recalled = memory.get('last_recalled', 0)
    days_since = (time.time() - last_recalled) / 86400

    return days_since <= days_threshold


def calculate_decay_factor(
    recall_count: int,
    base_decay: float = 0.99
) -> float:
    """
    Calculate adaptive decay factor based on recall frequency.

    Args:
        recall_count: Number of times recalled
        base_decay: Base decay rate (default: 0.99/day)

    Returns:
        Adjusted decay factor (0.99-0.999)
    """
    if recall_count >= 10:
        return 0.999  # Almost no decay
    elif recall_count >= 5:
        return 0.995  # Slow decay
    elif recall_count >= 3:
        return 0.993  # Medium decay
    else:
        return base_decay  # Standard decay


def update_importance_on_recall(memory: Dict) -> float:
    """
    Update memory importance when it's recalled.

    Args:
        memory: Memory dict with importance, recall_count, created, last_recalled

    Returns:
        New importance score
    """
    base_importance = memory.get('importance', 0.7)
    recall_count = memory.get('recall_count', 0) + 1  # Increment
    created = memory.get('created', time.time())
    last_recalled = memory.get('last_recalled', created)

    days_since_creation = (time.time() - created) / 86400
    days_since_last_recall = (time.time() - last_recalled) / 86400

    return calculate_adaptive_importance(
        base_importance=base_importance,
        recall_count=recall_count,
        days_since_creation=int(days_since_creation),
        days_since_last_recall=int(days_since_last_recall)
    )
