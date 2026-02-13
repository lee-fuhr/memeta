"""AI-powered memory analysis - Features 33-37"""
from typing import Dict, List
from datetime import datetime, timedelta

# Feature 33: Sentiment tracking
def analyze_sentiment(memory: Dict) -> str:
    """Detect: frustrated | satisfied | neutral"""
    content = memory.get('content', '').lower()
    if any(w in content for w in ['frustrated', 'annoying', 'wrong', 'mistake']):
        return 'frustrated'
    if any(w in content for w in ['great', 'perfect', 'excellent', 'love']):
        return 'satisfied'
    return 'neutral'

# Feature 34: Learning velocity metrics
def calculate_velocity(memories: List[Dict], window_days: int = 30) -> Dict:
    """Measure system improvement rate."""
    cutoff = datetime.now() - timedelta(days=window_days)
    recent = [m for m in memories if datetime.fromisoformat(m['created']) > cutoff]
    corrections = [m for m in recent if 'correction' in m.get('category', '')]
    return {
        'total_memories': len(recent),
        'corrections': len(corrections),
        'correction_rate': len(corrections) / len(recent) if recent else 0,
        'velocity': 'improving' if len(corrections) < 10 else 'needs_work'
    }

# Feature 35: Personality-aware responses
def adapt_response_style(user_history: List[Dict]) -> Dict:
    """Learn communication preferences from corrections."""
    directness = sum(1 for m in user_history if 'direct' in m.get('content', '').lower())
    verbosity = sum(len(m.get('content', '').split()) for m in user_history) / len(user_history) if user_history else 50
    return {
        'directness': 'high' if directness > 3 else 'medium',
        'verbosity': 'concise' if verbosity < 30 else 'detailed',
        'formality': 'casual'  # Lee likes casual
    }

# Feature 36: Predictive suggestions
def predict_needs(memory_patterns: Dict, current_context: Dict) -> List[str]:
    """Based on patterns, predict what user might need."""
    day_of_week = datetime.now().strftime('%A')
    suggestions = []
    # "You usually ask about X on Fridays"
    if day_of_week in memory_patterns.get('weekly_patterns', {}):
        suggestions.append(f"FYI: You usually work on {memory_patterns['weekly_patterns'][day_of_week']} on {day_of_week}s")
    return suggestions

# Feature 37: Memory conflict prediction
def predict_conflicts(new_memory: str, existing: List[Dict]) -> List[Dict]:
    """Flag potential contradictions before saving."""
    # Would use LLM to detect potential conflicts
    return []  # Simplified
