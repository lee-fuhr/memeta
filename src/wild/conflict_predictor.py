"""
Feature 37: Conflict prediction

Predict potential contradictions BEFORE saving a new memory.
Prevents surprises and reduces future conflict resolution work.
"""

from typing import Dict, List, Optional, Tuple
from pathlib import Path
import hashlib
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from wild.intelligence_db import IntelligenceDB
from memory_ts_client import MemoryTSClient
from contradiction_detector import find_similar_memories, check_contradictions


def predict_conflicts(new_memory_content: str,
                     confidence_threshold: float = 0.6,
                     memory_dir: Optional[Path] = None,
                     db_path: Optional[Path] = None) -> Dict:
    """
    Predict if new memory will conflict with existing memories

    Args:
        new_memory_content: Content of proposed new memory
        confidence_threshold: Minimum confidence to flag (0.0-1.0)
        memory_dir: Optional memory-ts path
        db_path: Optional database path

    Returns:
        Dict with conflict prediction and reasoning
    """
    client = MemoryTSClient(memory_dir)
    existing_memories = [{'id': m.id, 'content': m.content} for m in client.search()]

    # Find similar memories
    similar = find_similar_memories(new_memory_content, existing_memories, top_n=5)

    if not similar:
        return {
            'conflict_predicted': False,
            'confidence': 0.0,
            'reasoning': 'No similar memories found',
            'action': 'save'
        }

    # Check for contradictions with most similar
    most_similar = similar[0]
    contradiction = check_contradictions(new_memory_content, existing_memories)

    confidence = _calculate_conflict_confidence(new_memory_content, most_similar)

    # Log prediction
    memory_hash = hashlib.md5(new_memory_content.encode()).hexdigest()[:16]
    predicted_conflict_id = most_similar['id'] if contradiction.contradicts else None

    if confidence >= confidence_threshold:
        with IntelligenceDB(db_path) as db:
            db.log_conflict_prediction(
                memory_hash=memory_hash,
                predicted_conflict_id=predicted_conflict_id,
                confidence=confidence,
                reasoning=f"Similar to memory {most_similar['id']}: {most_similar['content'][:100]}"
            )

    return {
        'conflict_predicted': contradiction.contradicts and confidence >= confidence_threshold,
        'confidence': confidence,
        'conflicting_memory_id': predicted_conflict_id,
        'conflicting_content': most_similar['content'] if contradiction.contradicts else None,
        'reasoning': f"Detected {'contradiction' if contradiction.contradicts else 'similarity'} with existing memory",
        'action': contradiction.action if contradiction.contradicts else 'save',
        'similar_memories_count': len(similar)
    }


def _calculate_conflict_confidence(new_content: str, similar_memory: Dict) -> float:
    """
    Calculate confidence that a conflict exists

    Based on:
    - Word overlap percentage
    - Presence of negation words
    - Preference statement indicators
    """
    new_words = set(new_content.lower().split())
    similar_words = set(similar_memory['content'].lower().split())

    overlap = len(new_words & similar_words) / len(new_words | similar_words) if (new_words | similar_words) else 0

    # Boost confidence if both contain preference/negation keywords
    negation_keywords = {'not', 'never', 'don\'t', 'doesn\'t', 'avoid', 'stop'}
    preference_keywords = {'prefer', 'like', 'want', 'should', 'must', 'always'}

    new_has_negation = any(kw in new_words for kw in negation_keywords)
    similar_has_negation = any(kw in similar_words for kw in negation_keywords)

    new_has_preference = any(kw in new_words for kw in preference_keywords)
    similar_has_preference = any(kw in similar_words for kw in preference_keywords)

    # If both have preferences/negations and high overlap, likely a conflict
    confidence = overlap
    if (new_has_negation or new_has_preference) and (similar_has_negation or similar_has_preference):
        confidence = min(1.0, confidence + 0.2)

    return confidence


def update_prediction_outcome(prediction_hash: str, was_accurate: bool,
                              user_action: str, db_path: Optional[Path] = None):
    """
    Update prediction with actual outcome for accuracy tracking

    Args:
        prediction_hash: Hash of predicted memory
        was_accurate: Whether prediction was correct
        user_action: What user did ('save_anyway', 'skip', 'merge', 'replace')
        db_path: Optional database path
    """
    # TODO: Look up prediction_id by hash and update
    # For now, this is a placeholder for the feedback loop
    pass
