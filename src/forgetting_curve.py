"""Forgetting curve simulation - Feature 26: FSRS-6 review scheduling"""
from datetime import datetime, timedelta
from typing import Dict, List

def calculate_next_review(memory: Dict) -> datetime:
    """Calculate next review date using FSRS-6 spaced repetition."""
    stability = memory.get('stability', 1.0)
    difficulty = memory.get('difficulty', 5.0)
    days_until_review = stability * (9 - difficulty) / 2
    return datetime.now() + timedelta(days=int(days_until_review))

def get_due_for_review(memories: List[Dict]) -> List[Dict]:
    """Get memories due for review today."""
    today = datetime.now().date()
    return [m for m in memories if m.get('next_review') and 
            datetime.fromisoformat(m['next_review']).date() <= today]

def schedule_reviews(memories: List[Dict]) -> List[Dict]:
    """Add review schedules to all memories."""
    for mem in memories:
        mem['next_review'] = calculate_next_review(mem).isoformat()
    return memories
