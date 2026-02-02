"""
Importance scoring engine for memory-ts

Calculates importance scores (0.0-1.0) with:
- Base importance from content signals
- Decay over time (0.99^days)
- Reinforcement from access (+15% with 0.95 cap)
- Trigger word detection for boost
"""

import re
from datetime import datetime
from typing import List, Dict, Any


# Trigger words that boost importance
TRIGGER_WORDS = {
    # Urgency
    "critical", "urgent", "breaking", "production", "broken", "failed",
    # Patterns
    "pattern", "across", "multiple", "clients", "projects", "universal",
    # Impact
    "mistake", "error", "failure", "success", "win", "breakthrough",
    # Learning markers
    "learned", "discovered", "realized", "insight", "revelation"
}

# Importance signal keywords (weighted)
IMPORTANCE_SIGNALS = {
    "critical": 0.3,
    "urgent": 0.25,
    "breaking": 0.25,
    "production": 0.2,
    "pattern": 0.15,
    "across": 0.1,
    "clients": 0.1,
    "mistake": 0.15,
    "failed": 0.15,
    "success": 0.1,
}


def calculate_importance(content: str) -> float:
    """
    Calculate base importance score from content signals

    Returns score 0.3-1.0 based on:
    - Presence of importance keywords
    - Content length (longer = more substantial)
    - Punctuation indicating emphasis (!, multiple sentences)

    Args:
        content: Memory content text

    Returns:
        Importance score between 0.3 and 1.0
    """
    if not content:
        return 0.3

    score = 0.5  # baseline
    content_lower = content.lower()

    # Check for importance signal keywords
    for keyword, weight in IMPORTANCE_SIGNALS.items():
        if keyword in content_lower:
            score += weight

    # Length bonus (substantial content = more important)
    word_count = len(content.split())
    if word_count > 50:
        score += 0.1
    elif word_count > 100:
        score += 0.2

    # Emphasis markers (exclamation, all caps words)
    if '!' in content:
        score += 0.05
    caps_words = sum(1 for word in content.split() if word.isupper() and len(word) > 2)
    if caps_words > 0:
        score += min(0.1, caps_words * 0.05)

    # Multiple sentences indicate structured thought
    sentence_count = content.count('.') + content.count('!') + content.count('?')
    if sentence_count > 2:
        score += 0.05

    # Cap at 1.0, floor at 0.3
    return min(1.0, max(0.3, score))


def apply_decay(importance: float, days_since: int) -> float:
    """
    Apply decay formula: importance × (0.99 ^ days_since)

    Memories naturally decay over time unless reinforced.
    Stanford spaced repetition decay rate.

    Args:
        importance: Current importance score
        days_since: Days since last access

    Returns:
        Decayed importance score (>= 0)
    """
    if days_since < 0:
        days_since = 0

    decay_rate = 0.99
    multiplier = decay_rate ** days_since
    decayed = importance * multiplier

    return max(0.0, decayed)


def apply_reinforcement(importance: float) -> float:
    """
    Apply reinforcement: +15% with headroom (cap at 0.95)

    When a memory is accessed/used, boost its importance.
    Cap at 0.95 to leave headroom for future growth.

    Args:
        importance: Current importance score

    Returns:
        Reinforced importance score (capped at 0.95)
    """
    reinforced = importance * 1.15
    return min(0.95, reinforced)


def detect_trigger_words(content: str) -> List[str]:
    """
    Detect trigger words in content that indicate high importance

    Trigger words are case-insensitive matches against TRIGGER_WORDS set.

    Args:
        content: Memory content text

    Returns:
        List of detected trigger words (preserves original case)
    """
    if not content:
        return []

    detected = []
    content_lower = content.lower()
    words = re.findall(r'\b\w+\b', content_lower)

    for word in words:
        if word in TRIGGER_WORDS and word not in [d.lower() for d in detected]:
            # Find original case version
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
            match = pattern.search(content)
            if match:
                detected.append(match.group())

    return detected


def get_importance_score(content: str, metadata: Dict[str, Any]) -> float:
    """
    Complete importance scoring pipeline

    Combines:
    1. Base importance from content
    2. Decay based on age
    3. Reinforcement from recent access
    4. Trigger word boost

    Args:
        content: Memory content text
        metadata: Memory metadata dict with:
            - created: ISO datetime string
            - last_accessed: ISO datetime string
            - access_count: (optional) number of accesses

    Returns:
        Final importance score (0.0-1.0)
    """
    # Calculate base importance
    base_score = calculate_importance(content)

    # Apply decay if memory is old
    created = datetime.fromisoformat(metadata.get("created", datetime.now().isoformat()))
    last_accessed = datetime.fromisoformat(metadata.get("last_accessed", datetime.now().isoformat()))

    days_since_access = (datetime.now() - last_accessed).days
    score_with_decay = apply_decay(base_score, days_since_access)

    # Apply reinforcement if recently accessed or accessed multiple times
    access_count = metadata.get("access_count", 0)
    if days_since_access == 0 or access_count > 1:
        score_with_decay = apply_reinforcement(score_with_decay)

    # Boost for trigger words
    triggers = detect_trigger_words(content)
    if len(triggers) > 0:
        # +5% per trigger word, max +20%
        boost = min(0.2, len(triggers) * 0.05)
        score_with_decay = min(1.0, score_with_decay + boost)

    return score_with_decay
