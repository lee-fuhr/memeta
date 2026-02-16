"""
Feature 36: Memory lifespan prediction (integration wrapper)

Integrates existing lifespan_prediction.py with wild features.
Predicts when memories become stale and flags for review.
"""

from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Import existing lifespan prediction module
from memory_system.lifespan_prediction import (
    predict_lifespan_category,
    predict_expiration_date,
    should_flag_for_review,
    extract_explicit_expiration,
    get_lifespan_stats
)

from memory_system.memory_ts_client import MemoryTSClient


def analyze_memory_lifespans(memory_dir: Optional[Path] = None) -> Dict:
    """
    Analyze all memories for lifespan categories and upcoming expirations

    Args:
        memory_dir: Optional memory-ts path

    Returns:
        Dict with lifespan analysis
    """
    client = MemoryTSClient(memory_dir)
    memories = client.search()

    # Convert to dict format for lifespan_prediction module
    memory_dicts = [
        {
            'id': m.id,
            'content': m.content,
            'created': m.created,
            'expiration_date': predict_expiration_date(
                m.content,
                datetime.fromisoformat(m.created)
            )
        }
        for m in memories
    ]

    # Get stats
    stats = get_lifespan_stats(memory_dicts)

    # Find memories needing review
    needs_review = [
        m for m in memory_dicts
        if should_flag_for_review(m, days_until_expiration_threshold=7)
    ]

    # Count by category
    categories = {}
    for mem_dict in memory_dicts:
        category = predict_lifespan_category(mem_dict['content'])
        categories[category] = categories.get(category, 0) + 1

    return {
        'total_memories': stats['total'],
        'by_category': stats['by_category'],
        'evergreen_percent': stats['evergreen_percent'],
        'needs_review_count': len(needs_review),
        'needs_review': [
            {
                'id': m['id'],
                'content': m['content'][:100],
                'expires': m['expiration_date'].isoformat() if m['expiration_date'] else None
            }
            for m in needs_review[:10]  # Limit to 10
        ]
    }


def flag_expiring_memories(days_threshold: int = 7,
                          memory_dir: Optional[Path] = None) -> List[Dict]:
    """
    Get list of memories expiring soon

    Args:
        days_threshold: Days until expiration to flag
        memory_dir: Optional memory-ts path

    Returns:
        List of expiring memories
    """
    client = MemoryTSClient(memory_dir)
    memories = client.search()

    expiring = []
    for mem in memories:
        expiration = predict_expiration_date(
            mem.content,
            datetime.fromisoformat(mem.created)
        )

        if expiration:
            days_until = (expiration - datetime.now()).days
            if 0 <= days_until <= days_threshold:
                expiring.append({
                    'id': mem.id,
                    'content': mem.content,
                    'expires_in_days': days_until,
                    'expiration_date': expiration.isoformat()
                })

    return sorted(expiring, key=lambda x: x['expires_in_days'])


# Re-export core functions for convenience
__all__ = [
    'predict_lifespan_category',
    'predict_expiration_date',
    'should_flag_for_review',
    'extract_explicit_expiration',
    'get_lifespan_stats',
    'analyze_memory_lifespans',
    'flag_expiring_memories'
]
