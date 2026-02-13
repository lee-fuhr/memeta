"""
Memory lifespan prediction - Predict when memories become stale.

Feature 17: Categorize memories as evergreen vs time-bound.
Flag for review when approaching expiration.
"""

from typing import Dict, Optional
import re
from datetime import datetime, timedelta


# Time-bound keywords
TIME_BOUND_KEYWORDS = [
    'deadline', 'due', 'launch', 'release', 'expires', 'ends',
    'meeting', 'event', 'Q1', 'Q2', 'Q3', 'Q4', '2026', '2027',
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
    'this week', 'next week', 'this month', 'next month'
]

# Evergreen indicators
EVERGREEN_KEYWORDS = [
    'always', 'never', 'preference', 'principle', 'value',
    'philosophy', 'approach', 'methodology', 'framework',
    'best practice', 'guideline', 'rule', 'pattern'
]


def predict_lifespan_category(content: str) -> str:
    """
    Predict if memory is evergreen or time-bound.

    Args:
        content: Memory content

    Returns:
        "evergreen" | "short_term" | "medium_term" | "long_term"
    """
    content_lower = content.lower()

    # Check for time-bound keywords
    time_bound_count = sum(1 for kw in TIME_BOUND_KEYWORDS if kw in content_lower)
    evergreen_count = sum(1 for kw in EVERGREEN_KEYWORDS if kw in content_lower)

    # Strong evergreen signals
    if evergreen_count >= 2:
        return "evergreen"

    # Strong time-bound signals
    if time_bound_count >= 2:
        return "short_term"

    # Check for date patterns
    if re.search(r'\d{4}-\d{2}-\d{2}', content):  # YYYY-MM-DD
        return "short_term"

    if re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}', content_lower):
        return "short_term"

    # Preferences and decisions are typically medium-term
    if 'prefer' in content_lower or 'decided' in content_lower:
        return "medium_term"

    # Default: long-term
    return "long_term"


def predict_expiration_date(
    content: str,
    created_at: datetime,
    category: Optional[str] = None
) -> Optional[datetime]:
    """
    Predict when memory might become stale.

    Args:
        content: Memory content
        created_at: When memory was created
        category: Lifespan category (auto-detected if None)

    Returns:
        Predicted expiration datetime (None for evergreen)
    """
    if category is None:
        category = predict_lifespan_category(content)

    # Evergreen memories don't expire
    if category == "evergreen":
        return None

    # Time-based predictions
    if category == "short_term":
        # Expires in 30 days
        return created_at + timedelta(days=30)

    if category == "medium_term":
        # Expires in 6 months
        return created_at + timedelta(days=180)

    if category == "long_term":
        # Expires in 2 years
        return created_at + timedelta(days=730)

    return None


def should_flag_for_review(
    memory: Dict,
    days_until_expiration_threshold: int = 7
) -> bool:
    """
    Check if memory is approaching expiration and needs review.

    Args:
        memory: Memory dict with expiration_date
        days_until_expiration_threshold: Flag if expiring within N days

    Returns:
        True if should review
    """
    expiration = memory.get('expiration_date')
    if not expiration:
        return False  # Evergreen, no review needed

    if isinstance(expiration, str):
        expiration = datetime.fromisoformat(expiration)

    days_until = (expiration - datetime.now()).days

    return days_until <= days_until_expiration_threshold


def extract_explicit_expiration(content: str) -> Optional[datetime]:
    """
    Extract explicit expiration date from content.

    Patterns:
    - "expires 2026-02-20"
    - "valid until March 15"
    - "deadline: Feb 28"

    Args:
        content: Memory content

    Returns:
        Expiration datetime if found
    """
    # Pattern: YYYY-MM-DD
    match = re.search(r'(expires?|deadline|due|valid until)\s*:?\s*(\d{4}-\d{2}-\d{2})', content.lower())
    if match:
        try:
            return datetime.strptime(match.group(2), '%Y-%m-%d')
        except ValueError:
            pass

    # TODO: Add more date parsing patterns as needed

    return None


def get_lifespan_stats(memories: list) -> Dict:
    """
    Get statistics about memory lifespans.

    Args:
        memories: List of memory dicts

    Returns:
        Dict with counts by category
    """
    categories = {}

    for mem in memories:
        content = mem.get('content', '')
        category = predict_lifespan_category(content)
        categories[category] = categories.get(category, 0) + 1

    return {
        'total': len(memories),
        'by_category': categories,
        'evergreen_percent': (categories.get('evergreen', 0) / len(memories) * 100) if memories else 0
    }
