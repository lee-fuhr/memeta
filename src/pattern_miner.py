"""
Cross-session pattern mining - Detect habits and recurring patterns.

Feature 18: Analyze memories across sessions to find:
- Temporal patterns ("Lee always asks about X on Mondays")
- Frequency patterns ("User mentions Y every week")
- Sequential patterns ("When A happens, B usually follows")
"""

from typing import List, Dict
from collections import defaultdict, Counter
from datetime import datetime


def mine_temporal_patterns(memories: List[Dict]) -> Dict:
    """
    Find patterns by day of week or time of day.

    Args:
        memories: List of memory dicts with created timestamp

    Returns:
        Dict with temporal insights
    """
    by_weekday = defaultdict(list)
    by_hour = defaultdict(list)

    for mem in memories:
        created = mem.get('created')
        if not created:
            continue

        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        elif isinstance(created, (int, float)):
            created = datetime.fromtimestamp(created)

        weekday = created.strftime('%A')
        hour = created.hour

        content = mem.get('content', '').lower()

        by_weekday[weekday].append(content)
        by_hour[hour].append(content)

    # Find common topics by weekday
    weekday_topics = {}
    for day, contents in by_weekday.items():
        # Extract most common words (simple topic detection)
        words = ' '.join(contents).split()
        common_words = Counter(words).most_common(5)
        weekday_topics[day] = [w for w, count in common_words if count > 2]

    # Find busy hours
    busy_hours = [(hour, len(contents)) for hour, contents in by_hour.items()]
    busy_hours.sort(key=lambda x: x[1], reverse=True)

    return {
        'by_weekday': weekday_topics,
        'busiest_hours': dict(busy_hours[:5]),
        'total_memories': len(memories)
    }


def mine_frequency_patterns(memories: List[Dict], min_frequency: int = 3) -> List[Dict]:
    """
    Find topics or concepts mentioned frequently.

    Args:
        memories: List of memory dicts
        min_frequency: Minimum mentions to report

    Returns:
        List of frequent patterns
    """
    # Extract all words/phrases
    all_content = ' '.join(m.get('content', '').lower() for m in memories)
    words = all_content.split()

    # Count frequencies
    word_freq = Counter(words)

    # Filter for meaningful words (>3 chars, not common words)
    common_words = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'been', 'which'}
    frequent_patterns = []

    for word, count in word_freq.most_common(50):
        if len(word) > 3 and word not in common_words and count >= min_frequency:
            frequent_patterns.append({
                'term': word,
                'frequency': count,
                'percentage': (count / len(words)) * 100 if words else 0
            })

    return frequent_patterns


def mine_sequential_patterns(memories: List[Dict]) -> List[Dict]:
    """
    Find patterns where event A often precedes event B.

    Args:
        memories: List of memory dicts (ordered by time)

    Returns:
        List of sequential patterns
    """
    # Look for sequences in time-ordered memories
    sequences = defaultdict(int)

    for i in range(len(memories) - 1):
        mem_a = memories[i].get('content', '').lower()
        mem_b = memories[i + 1].get('content', '').lower()

        # Extract key terms (simple: first 3 words)
        terms_a = ' '.join(mem_a.split()[:3])
        terms_b = ' '.join(mem_b.split()[:3])

        if terms_a and terms_b:
            sequences[(terms_a, terms_b)] += 1

    # Filter for significant sequences (appears 2+ times)
    significant_sequences = []

    for (term_a, term_b), count in sequences.items():
        if count >= 2:
            significant_sequences.append({
                'first': term_a,
                'then': term_b,
                'occurrences': count
            })

    significant_sequences.sort(key=lambda x: x['occurrences'], reverse=True)

    return significant_sequences[:10]  # Top 10


def mine_all_patterns(memories: List[Dict]) -> Dict:
    """
    Run all pattern mining techniques.

    Args:
        memories: List of memory dicts

    Returns:
        Dict with all pattern types
    """
    return {
        'temporal': mine_temporal_patterns(memories),
        'frequency': mine_frequency_patterns(memories),
        'sequential': mine_sequential_patterns(memories),
        'total_memories_analyzed': len(memories)
    }


def format_pattern_insights(patterns: Dict) -> str:
    """
    Format patterns into human-readable insights.

    Args:
        patterns: Pattern dict from mine_all_patterns

    Returns:
        Formatted string
    """
    lines = []
    lines.append("# Pattern Mining Results\n")

    # Temporal patterns
    temporal = patterns.get('temporal', {})
    if temporal.get('by_weekday'):
        lines.append("## Temporal Patterns\n")
        for day, topics in temporal['by_weekday'].items():
            if topics:
                lines.append(f"- **{day}**: Often discusses {', '.join(topics[:3])}")

    # Frequency patterns
    frequency = patterns.get('frequency', [])
    if frequency:
        lines.append("\n## Frequent Topics\n")
        for pattern in frequency[:5]:
            lines.append(f"- **{pattern['term']}**: Mentioned {pattern['frequency']}x ({pattern['percentage']:.1f}%)")

    # Sequential patterns
    sequential = patterns.get('sequential', [])
    if sequential:
        lines.append("\n## Sequential Patterns\n")
        for seq in sequential[:5]:
            lines.append(f"- When '{seq['first']}', often followed by '{seq['then']}' ({seq['occurrences']}x)")

    return '\n'.join(lines)
