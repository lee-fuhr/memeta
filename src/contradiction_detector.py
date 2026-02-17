"""
Contradiction detection for memory-ts

Before saving a new memory, checks if it contradicts existing memories.
Uses LLM to detect semantic contradictions (not just duplicates).

Examples of contradictions:
- "I prefer morning meetings" vs "I prefer afternoon meetings"
- "Use Python for scripts" vs "Use Node.js for scripts"
- "Client wants minimalist design" vs "Client wants bold, colorful design"
"""

import subprocess
from typing import List, Dict, Optional
from dataclasses import dataclass

from .circuit_breaker import get_breaker, CircuitBreakerOpenError


@dataclass
class ContradictionResult:
    """Result of contradiction check"""
    contradicts: bool
    contradicted_memory: Optional[Dict] = None
    action: str = "save"  # "save" | "replace" | "skip"


def ask_claude_quick(prompt: str, timeout: int = 10) -> str:
    """
    Quick LLM query using Claude CLI.

    Protected by circuit breaker to fail fast when LLM is unavailable.

    Args:
        prompt: Question for Claude
        timeout: Timeout in seconds

    Returns:
        Response text (empty string on failure)
    """
    breaker = get_breaker("llm_contradiction", failure_threshold=3, recovery_timeout=60.0)

    def _run_query():
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI returned {result.returncode}")
        return result.stdout.strip()

    try:
        return breaker.call(_run_query)
    except CircuitBreakerOpenError:
        return ""
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return ""


def check_contradiction(
    new_content: str,
    existing_content: str
) -> bool:
    """
    Check if two memories contradict each other.

    Uses LLM to detect semantic contradictions.

    Args:
        new_content: New memory content
        existing_content: Existing memory content

    Returns:
        True if memories contradict, False otherwise
    """
    prompt = f"""Does this new fact CONTRADICT the existing fact?

New: {new_content}
Existing: {existing_content}

Answer ONLY with one word: CONTRADICTS or COMPATIBLE"""

    response = ask_claude_quick(prompt, timeout=10).upper()

    return "CONTRADICT" in response


def find_similar_memories(
    new_content: str,
    existing_memories: List[Dict],
    top_n: int = 5
) -> List[Dict]:
    """
    Find most similar existing memories using word overlap.

    Simple word-overlap similarity (no embeddings needed for now).

    Args:
        new_content: New memory content
        existing_memories: List of existing memory dicts
        top_n: Number of top matches to return

    Returns:
        List of most similar memory dicts
    """
    import re

    def normalize(text: str) -> set:
        """Normalize text to word set"""
        clean = re.sub(r'[^\w\s]', ' ', text.lower())
        return set(w for w in clean.split() if w and len(w) > 2)

    new_words = normalize(new_content)
    if not new_words:
        return []

    # Score each existing memory by word overlap
    scored = []
    for mem in existing_memories:
        mem_words = normalize(mem.get('content', ''))
        if not mem_words:
            continue

        overlap = len(new_words & mem_words)
        similarity = overlap / min(len(new_words), len(mem_words))

        if similarity > 0.3:  # Only consider if >30% overlap
            scored.append((similarity, mem))

    # Sort by similarity and return top N
    scored.sort(reverse=True, key=lambda x: x[0])
    return [mem for _, mem in scored[:top_n]]


def check_contradictions(
    new_memory: str,
    existing_memories: List[Dict]
) -> ContradictionResult:
    """
    Check if new memory contradicts any existing memories.

    Args:
        new_memory: New memory content
        existing_memories: List of existing memory dicts with 'content' and 'id' keys

    Returns:
        ContradictionResult with action to take
    """
    # Find similar memories
    similar = find_similar_memories(new_memory, existing_memories, top_n=5)

    if not similar:
        return ContradictionResult(contradicts=False, action="save")

    # Check each similar memory for contradiction
    for existing_mem in similar:
        existing_content = existing_mem.get('content', '')

        if check_contradiction(new_memory, existing_content):
            return ContradictionResult(
                contradicts=True,
                contradicted_memory=existing_mem,
                action="replace"
            )

    return ContradictionResult(contradicts=False, action="save")
