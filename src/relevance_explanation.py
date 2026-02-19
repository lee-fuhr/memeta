"""
Relevance explanation - Human-readable explanations for search results.

Feature: Add 'explanation' field to hybrid search results explaining
why each memory matched the query, combining semantic similarity,
keyword overlap, and confidence signals.

Example output:
  "87% meaning match. Keywords: dark, mode. High confidence (confirmed 3x)."
"""

from typing import Dict, List, Optional


STOPWORDS = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
             'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
             'should', 'may', 'might', 'shall', 'can', 'to', 'of', 'in', 'for',
             'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
             'before', 'after', 'above', 'below', 'between', 'and', 'but', 'or',
             'not', 'no', 'if', 'then', 'than', 'that', 'this', 'it', 'its'}


def get_matching_keywords(query: str, content: str) -> List[str]:
    """
    Find words that appear in both query and content.

    Case-insensitive. Skips stopwords. Returns deduplicated list
    preserving order of appearance in the query.

    Args:
        query: Search query string
        content: Memory content string

    Returns:
        List of matching non-stopword keywords
    """
    if not query or not content:
        return []

    query_words = query.lower().split()
    content_words_set = set(content.lower().split())

    seen = set()
    matches = []
    for word in query_words:
        lower_word = word.lower()
        if lower_word in STOPWORDS:
            continue
        if lower_word in content_words_set and lower_word not in seen:
            matches.append(lower_word)
            seen.add(lower_word)

    return matches


def explain_relevance(query: str, memory: Dict, scores: Dict) -> str:
    """
    Generate a human-readable explanation of why this memory matched the query.

    Components:
    1. Semantic match: "87% meaning match" (from semantic_score)
    2. Keyword overlap: "Keywords: dark, mode" (from BM25 - find common terms)
    3. Confidence: "High confidence (confirmed 3x)" (from confidence_score + confirmations)
    4. Tag relevance: "Tags: #preference" (list matching tags)

    Format: "87% meaning match. Keywords: dark, mode. High confidence (confirmed 3x)."
    If semantic_score > 0.8: lead with "Strong semantic match"
    If bm25_score_normalized > 0.7: mention "Strong keyword overlap"
    If both low: "Partial match"

    Args:
        query: The search query
        memory: Memory dict (may contain 'content', 'semantic_tags',
                'confidence_score', 'confirmations')
        scores: Dict with 'semantic_score', 'bm25_score', 'bm25_score_normalized'

    Returns:
        Human-readable explanation string
    """
    parts = []

    semantic_score = scores.get('semantic_score', 0)
    bm25_normalized = scores.get('bm25_score_normalized', 0)

    # 1. Semantic match component
    if semantic_score > 0.8:
        pct = round(semantic_score * 100)
        parts.append(f"Strong semantic match ({pct}%)")
    elif semantic_score > 0.5:
        pct = round(semantic_score * 100)
        parts.append(f"{pct}% meaning match")
    elif semantic_score > 0.0:
        pct = round(semantic_score * 100)
        parts.append(f"Weak semantic match ({pct}%)")

    # 2. Keyword overlap component
    content = memory.get('content', '') or ''
    matching_keywords = get_matching_keywords(query, content)

    if bm25_normalized > 0.7 and matching_keywords:
        parts.append(f"Strong keyword overlap: {', '.join(matching_keywords)}")
    elif matching_keywords:
        parts.append(f"Keywords: {', '.join(matching_keywords)}")

    # 3. Confidence component
    confidence_score = memory.get('confidence_score', None)
    confirmations = memory.get('confirmations', 0) or 0

    if confidence_score is not None:
        from .confidence_scoring import classify_confidence_level
        level = classify_confidence_level(confidence_score)

        if level in ('very_high', 'high'):
            label = level.replace('_', ' ').capitalize()
            if confirmations > 0:
                parts.append(f"{label} confidence (confirmed {confirmations}x)")
            else:
                parts.append(f"{label} confidence")
        elif level == 'medium':
            # Don't overstate medium confidence
            pass
        elif level in ('low', 'very_low'):
            parts.append(f"{label} confidence" if level == 'low' else "Very low confidence")

    # 4. Tag relevance
    tags = memory.get('semantic_tags', None) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]
    if tags and query:
        query_lower = query.lower()
        matching_tags = [
            t for t in tags
            if any(w in t.lower() for w in query_lower.split() if w.lower() not in STOPWORDS)
        ]
        if matching_tags:
            tag_str = ', '.join(f'#{t}' for t in matching_tags[:3])
            parts.append(f"Tags: {tag_str}")

    # Fallback: if no signal components were generated
    if not parts:
        if semantic_score > 0 or bm25_normalized > 0:
            parts.append("Partial match")
        else:
            parts.append("Weak match")

    return '. '.join(parts) + '.'


def add_explanations_to_results(query: str, results: List[Dict]) -> List[Dict]:
    """
    Add 'explanation' field to each result dict.

    Modifies results in place and returns the list.

    Args:
        query: The search query
        results: List of result dicts from hybrid_search

    Returns:
        The same list with 'explanation' added to each dict
    """
    for result in results:
        scores = {
            'semantic_score': result.get('semantic_score', 0),
            'bm25_score': result.get('bm25_score', 0),
            'bm25_score_normalized': result.get('bm25_score_normalized', 0),
        }
        result['explanation'] = explain_relevance(query, result, scores)
    return results
