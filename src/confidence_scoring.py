"""
Confidence scoring - Track memory reliability.

Feature 15: Track how many times a memory has been confirmed vs contradicted.

Examples:
- Single mention: confidence = 0.5
- Confirmed 3x: confidence = 0.9
- Contradicted once: confidence = 0.3
- User explicitly corrects: confidence = 0.0 (archived)
"""

from typing import Dict, Optional


def calculate_confidence(
    confirmations: int,
    contradictions: int,
    source_count: int = 1
) -> float:
    """
    Calculate confidence score for a memory.

    Args:
        confirmations: Number of times memory was confirmed
        contradictions: Number of times memory was contradicted
        source_count: Number of independent sources (default: 1)

    Returns:
        Confidence score (0.0-1.0)
    """
    # Base confidence depends on confirmations
    if confirmations == 0 and contradictions == 0:
        # Single mention - medium confidence
        base = 0.5
    elif confirmations > 0:
        # Confirmed memories get higher confidence
        base = min(0.9, 0.5 + (confirmations * 0.1))
    else:
        base = 0.5

    # Contradictions reduce confidence significantly
    if contradictions > 0:
        penalty = contradictions * 0.3
        base = max(0.1, base - penalty)

    # Multiple independent sources boost confidence
    if source_count > 1:
        boost = min(0.1, (source_count - 1) * 0.05)
        base = min(1.0, base + boost)

    return base


def update_confidence_on_confirmation(memory: Dict) -> float:
    """
    Update confidence when memory is confirmed.

    Args:
        memory: Memory dict with confidence_score, confirmations, contradictions

    Returns:
        New confidence score
    """
    confirmations = memory.get('confirmations', 0) + 1
    contradictions = memory.get('contradictions', 0)
    source_count = memory.get('source_count', 1)

    return calculate_confidence(confirmations, contradictions, source_count)


def update_confidence_on_contradiction(memory: Dict) -> float:
    """
    Update confidence when memory is contradicted.

    Args:
        memory: Memory dict with confidence_score, confirmations, contradictions

    Returns:
        New confidence score (significantly reduced)
    """
    confirmations = memory.get('confirmations', 0)
    contradictions = memory.get('contradictions', 0) + 1
    source_count = memory.get('source_count', 1)

    return calculate_confidence(confirmations, contradictions, source_count)


def should_archive_low_confidence(memory: Dict, threshold: float = 0.2) -> bool:
    """
    Check if memory confidence is too low to keep.

    Args:
        memory: Memory dict with confidence_score
        threshold: Minimum confidence to keep (default: 0.2)

    Returns:
        True if should archive
    """
    confidence = memory.get('confidence_score', 0.5)
    contradictions = memory.get('contradictions', 0)

    # Archive if confidence below threshold OR multiple contradictions
    return confidence < threshold or contradictions >= 2


def classify_confidence_level(confidence: float) -> str:
    """
    Classify confidence into human-readable levels.

    Args:
        confidence: Confidence score (0.0-1.0)

    Returns:
        Level string: "very_low" | "low" | "medium" | "high" | "very_high"
    """
    if confidence >= 0.9:
        return "very_high"
    elif confidence >= 0.7:
        return "high"
    elif confidence >= 0.5:
        return "medium"
    elif confidence >= 0.3:
        return "low"
    else:
        return "very_low"


def get_confidence_stats(memories: list) -> Dict:
    """
    Get statistics about memory confidence across a corpus.

    Args:
        memories: List of memory dicts

    Returns:
        Dict with confidence distribution stats
    """
    if not memories:
        return {
            'total': 0,
            'avg_confidence': 0.0,
            'by_level': {}
        }

    confidences = [m.get('confidence_score', 0.5) for m in memories]
    avg_confidence = sum(confidences) / len(confidences)

    # Count by level
    levels = {}
    for conf in confidences:
        level = classify_confidence_level(conf)
        levels[level] = levels.get(level, 0) + 1

    return {
        'total': len(memories),
        'avg_confidence': avg_confidence,
        'by_level': levels,
        'low_confidence_count': sum(1 for c in confidences if c < 0.3)
    }
