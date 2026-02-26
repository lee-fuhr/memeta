"""
Deduplication logic for session memory consolidation

Smart deduplication with LLM-powered gray-area decisions.
Extracted from session_consolidator.py to keep files under 500 lines.
"""

from typing import List

from .extraction_patterns import NORMALIZE_PATTERN


def smart_dedup_decision(
    new_content: str,
    existing_content: str,
    similarity: float
) -> str:
    """
    LLM-powered dedup decision for gray area (50-90% similarity).

    With fallback: If LLM times out, use stricter similarity threshold (>0.75 = duplicate).

    Args:
        new_content: New memory content
        existing_content: Existing memory content
        similarity: Word overlap similarity (0.0-1.0)

    Returns:
        "DUPLICATE" | "UPDATE" | "NEW"
    """
    # Fast path: obvious cases
    if similarity < 0.5:
        return "NEW"
    if similarity > 0.9:
        return "DUPLICATE"

    # Gray area (50-90%) - ask LLM with fallback
    from .llm_extractor import ask_claude

    prompt = f"""Compare these two memories:

New: {new_content}
Existing: {existing_content}

Is the new memory:
- DUPLICATE (same fact, skip it)
- UPDATE (refinement or replacement of existing)
- NEW (genuinely new information)

Answer with ONE WORD ONLY."""

    decision = ask_claude(prompt, timeout=30, max_retries=2).strip().upper()

    # LLM fallback: Use stricter similarity threshold when LLM fails
    if not decision:
        # Timeout or failure - use conservative similarity-based decision
        if similarity > 0.75:
            return "DUPLICATE"
        else:
            return "NEW"

    if "DUPLICATE" in decision:
        return "DUPLICATE"
    elif "UPDATE" in decision:
        return "UPDATE"
    else:
        return "NEW"


def deduplicate(
    new_memories: List,
    existing_memories: List,
    use_llm_dedup: bool = True
) -> List:
    """
    Remove memories that duplicate existing ones

    Enhanced with LLM-powered decisions for gray area (50-90% similarity).

    Args:
        new_memories: List of newly extracted SessionMemory objects
        existing_memories: List of existing Memory objects (must have .content and .id)
        use_llm_dedup: If True, use LLM for smarter dedup decisions

    Returns:
        Deduplicated list of SessionMemory objects
    """
    # Pre-compute normalized word sets and content mapping
    existing_data = []
    for existing in existing_memories:
        text_clean = NORMALIZE_PATTERN.sub(' ', existing.content.lower())
        words = frozenset(w for w in text_clean.split() if w)
        if words:
            existing_data.append({
                'words': words,
                'content': existing.content,
                'id': existing.id
            })

    unique_memories = []

    for new_mem in new_memories:
        text_clean = NORMALIZE_PATTERN.sub(' ', new_mem.content.lower())
        new_words = frozenset(w for w in text_clean.split() if w)

        # Skip empty memories
        if not new_words:
            continue

        is_duplicate = False
        new_len = len(new_words)
        best_match_similarity = 0.0
        best_match_content = None

        for existing in existing_data:
            # Calculate bidirectional similarity
            overlap = len(new_words & existing['words'])
            new_similarity = overlap / new_len
            existing_similarity = overlap / len(existing['words'])
            max_similarity = max(new_similarity, existing_similarity)

            # Track best match for LLM decision
            if max_similarity > best_match_similarity:
                best_match_similarity = max_similarity
                best_match_content = existing['content']

            # Definite duplicate if >90% similar
            if max_similarity >= 0.9:
                is_duplicate = True
                break

        # Gray area (50-90%) - use LLM if enabled
        if not is_duplicate and use_llm_dedup and best_match_similarity >= 0.5:
            decision = smart_dedup_decision(
                new_mem.content,
                best_match_content,
                best_match_similarity
            )

            if decision == "DUPLICATE":
                is_duplicate = True

        if not is_duplicate:
            unique_memories.append(new_mem)

    return unique_memories
