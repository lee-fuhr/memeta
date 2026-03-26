"""
LLM-powered memory extraction using Claude Code CLI

Runs Claude Code in non-interactive mode to analyze session conversations
and extract learnings that pattern-based extraction misses.

Fully automatic - called from SessionEnd hook alongside pattern extraction.
"""

import json
import re

from .circuit_breaker import get_breaker, CircuitBreakerOpenError
from .llm_backend import run_llm_prompt, strip_code_fence
from .session_consolidator import SessionMemory
import logging

logger = logging.getLogger(__name__)


MAX_CONVERSATION_LENGTH = 15000  # Chars to send to LLM


def generate_extraction_prompt(conversation: str) -> str:
    """
    Generate the extraction prompt for Claude CLI

    Uses PromptEvolver to get best prompt from genetic algorithm.
    Falls back to hardcoded prompt if evolver unavailable.

    Args:
        conversation: Full conversation text

    Returns:
        Prompt string ready for claude -p
    """
    # Truncate to last N chars (most recent = most relevant)
    sample = conversation[-MAX_CONVERSATION_LENGTH:]

    # Try to use evolved prompt
    try:
        from memory_system.wild.prompt_evolver import ExtractionPromptEvolver
        evolver = ExtractionPromptEvolver()
        template = evolver.get_best_prompt(epsilon=0.1)
        return template.format(CONVERSATION=sample)
    except Exception:
        # Fall back to hardcoded prompt
        pass

    # Hardcoded fallback
    return f"""Analyze this Claude Code session and extract learnings worth remembering.

CONVERSATION:
{sample}

Extract learnings in these categories:
1. **Preferences** - User stated preferences ("I prefer X", "Don't do Y")
2. **Corrections** - User corrected the assistant about something
3. **Technical** - Solutions, patterns, approaches that worked
4. **Process** - Workflows, sequences, methods that were effective
5. **Client-specific** - Patterns specific to a client/project mentioned

For each learning:
- Write 1-2 clear, specific, actionable sentences
- Rate importance: 0.5=minor tip, 0.7=useful pattern, 0.85=critical insight, 0.95=game-changer
- Explain why it matters in 1 sentence
- Assign a category

QUALITY BARS:
- Only extract genuinely useful insights
- Skip generic advice ("test thoroughly", "be clear")
- Corrections get 0.8+ importance
- Preferences get 0.7+ importance
- If no significant learnings, return empty array []

Return ONLY a JSON array:
[{{"content": "Specific learning", "importance": 0.75, "reasoning": "Why this matters", "category": "preference"}}]"""


def parse_llm_response(response: str, project_id: str = "default") -> list[SessionMemory]:
    """
    Parse LLM JSON response into SessionMemory objects

    Handles:
    - Clean JSON arrays
    - ```json fenced code blocks
    - Malformed responses (returns empty list)
    - Missing fields (skips invalid entries)
    - Out-of-range importance values (clamps to 0.0-1.0)

    Args:
        response: Raw string output from Claude CLI
        project_id: Project identifier for memories

    Returns:
        list of SessionMemory objects
    """
    if not response or not response.strip():
        return []

    # Strip markdown code fencing if present
    text = response.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```\s*$', '', text)

    # Try to parse JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    memories = []
    for item in data:
        if not isinstance(item, dict):
            continue

        content = item.get("content")
        if not content:
            continue

        # Clamp importance to valid range
        raw_importance = item.get("importance", 0.5)
        importance = max(0.0, min(1.0, float(raw_importance)))

        memories.append(SessionMemory(
            content=content,
            importance=importance,
            project_id=project_id,
            tags=["#learning", "#llm-extracted"],
        ))

    return memories


def extract_with_llm(
    conversation: str,
    project_id: str = "default",
    timeout: int = 30
) -> list[SessionMemory]:
    """
    Extract memories using Claude Code CLI

    Generates prompt, calls claude -p, parses response.
    Falls back to empty list on any failure.

    Args:
        conversation: Full conversation text
        project_id: Project identifier
        timeout: CLI timeout in seconds

    Returns:
        list of extracted SessionMemory objects (empty on failure)
    """
    prompt = generate_extraction_prompt(conversation)
    breaker = get_breaker("llm_extraction", failure_threshold=3, recovery_timeout=60.0)

    def _run_extraction():
        response = run_llm_prompt(prompt, timeout=timeout, retries=2)
        if not response:
            raise RuntimeError("LLM returned empty response")
        return parse_llm_response(response, project_id=project_id)

    try:
        return breaker.call(_run_extraction)
    except CircuitBreakerOpenError:
        return []
    except Exception:
        breaker.record_failure()
        return []


def ask_claude(prompt: str, timeout: int = 30, max_retries: int = 3) -> str:
    """
    Simple helper to ask the LLM a question and get a text response.

    Uses centralized LLM backend with circuit breaker protection.
    Retry logic is handled by run_llm_prompt.

    Args:
        prompt: Question or task for the LLM
        timeout: CLI timeout in seconds
        max_retries: Maximum retry attempts

    Returns:
        Response text (empty string on all failures)
    """
    breaker = get_breaker("llm_ask_claude", failure_threshold=3, recovery_timeout=60.0)

    if breaker.is_open:
        return ""

    response = run_llm_prompt(prompt, timeout=timeout, retries=max_retries)
    if response:
        breaker.record_success()
    else:
        breaker.record_failure()
    return response


def combine_extractions(
    pattern_memories: list[SessionMemory],
    llm_memories: list[SessionMemory],
    similarity_threshold: float = 0.7
) -> list[SessionMemory]:
    """
    Merge pattern-based and LLM-based extractions, deduplicating

    When duplicates are found between methods, keeps the version
    with higher importance score.

    Args:
        pattern_memories: Memories from pattern extraction
        llm_memories: Memories from LLM extraction
        similarity_threshold: Word overlap threshold for deduplication

    Returns:
        Combined, deduplicated list
    """
    if not llm_memories:
        return list(pattern_memories)
    if not pattern_memories:
        return list(llm_memories)

    def normalize_text(text: str) -> set:
        """Normalize text for comparison"""
        text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
        return set(w for w in text_clean.split() if w)

    # Start with all memories, marking source
    combined = []
    used_llm_indices = set()

    for pattern_mem in pattern_memories:
        pattern_words = normalize_text(pattern_mem.content)
        if not pattern_words:
            continue

        is_duplicate = False
        best_llm_match_idx = None
        best_llm_match_importance = 0

        for i, llm_mem in enumerate(llm_memories):
            llm_words = normalize_text(llm_mem.content)
            if not llm_words:
                continue

            overlap = len(pattern_words & llm_words)
            pattern_sim = overlap / len(pattern_words)
            llm_sim = overlap / len(llm_words)

            if pattern_sim >= similarity_threshold or llm_sim >= similarity_threshold:
                is_duplicate = True
                if llm_mem.importance > best_llm_match_importance:
                    best_llm_match_idx = i
                    best_llm_match_importance = llm_mem.importance

        if is_duplicate and best_llm_match_idx is not None:
            # Keep higher importance version
            if best_llm_match_importance >= pattern_mem.importance:
                combined.append(llm_memories[best_llm_match_idx])
            else:
                combined.append(pattern_mem)
            used_llm_indices.add(best_llm_match_idx)
        else:
            combined.append(pattern_mem)

    # Add non-duplicate LLM memories
    for i, llm_mem in enumerate(llm_memories):
        if i not in used_llm_indices:
            combined.append(llm_mem)

    return combined
