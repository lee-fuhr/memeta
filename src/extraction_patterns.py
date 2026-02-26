"""
Extraction patterns for session memory consolidation

Pre-compiled regex patterns and pattern-based memory extraction logic.
Extracted from session_consolidator.py to keep files under 500 lines.
"""

import re
from typing import List, Callable

from .importance_engine import calculate_importance

# Pre-compiled regex patterns for memory extraction
LEARNING_PATTERNS = [
    re.compile(r"(?:learned|discovered|realized|found out|noticed) that ([^.!?]+[.!?])", re.IGNORECASE),
    re.compile(r"(?:key insight|important to note|worth remembering):? ([^.!?]+[.!?])", re.IGNORECASE),
    re.compile(r"(?:pattern|trend) (?:I noticed|observed|saw):? ([^.!?]+[.!?])", re.IGNORECASE),
]
CORRECTION_PATTERNS = [
    re.compile(r"user:.*?(?:actually|correction|no,|wrong|mistake|should be|meant to say) ([^.!?]+[.!?])", re.IGNORECASE | re.DOTALL),
    re.compile(r"user:.*?(?:better way|instead try|prefer) ([^.!?]+[.!?])", re.IGNORECASE | re.DOTALL),
]
PROBLEM_SOLUTION_PATTERN = re.compile(
    r"(?:problem|issue|challenge):.*?([^.!?]+[.!?]).*?(?:solution|fix|approach):.*?([^.!?]+[.!?])",
    re.IGNORECASE | re.DOTALL,
)
ASSISTANT_INSIGHT_PATTERN = re.compile(r"assistant:.*?([A-Z][^.!?]{30,}[.!?])", re.DOTALL)
NORMALIZE_PATTERN = re.compile(r'[^\w\s]')

# Garbage detection patterns
TOOL_CALL_MARKERS = ('toolu_', 'tool_use', 'tool_result', "'input': {", '"input": {', "'name': '")
LINE_NUMBER_PATTERN = re.compile(r'\d+[→\t].*\d+[→\t].*\d+[→\t]')
JSON_CHARS = set('{}[]\'"')

# Meta-memory keywords - prevent memories about the memory system itself
# Use phrases to avoid false positives (e.g. "memory extraction" not just "extraction")
META_KEYWORDS = (
    'memory system', 'memory-system', 'total recall', 'memory extraction',
    'session consolidat', '3-pass', 'embedding', 'fsrs', 'semantic search',
    'hybrid search', 'memory consolidat', 'llm extract', 'importance scor',
    'memory file', 'memory.md', 'intelligence.db', 'memory_ts_client',
    'session consolidator', 'memoryts'
)


def is_garbage_content(text: str) -> bool:
    """Check if extracted content is garbage (tool calls, JSON, line numbers, meta-memories)."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 30:
        return True

    # Meta-memories (about the memory system itself)
    lower_text = stripped.lower()
    if any(keyword in lower_text for keyword in META_KEYWORDS):
        return True

    # Tool call artifacts
    for marker in TOOL_CALL_MARKERS:
        if marker in stripped:
            return True
    # Line number dumps (3+ consecutive)
    if LINE_NUMBER_PATTERN.search(stripped):
        return True
    # High ratio of JSON-like characters (>20%)
    json_count = sum(1 for c in stripped if c in JSON_CHARS)
    if json_count / len(stripped) > 0.20:
        return True
    return False


def extract_memories_patterns(
    conversation: str,
    project_id: str,
    memory_factory: Callable,
) -> List:
    """
    Pattern-based memory extraction (fast, deterministic)

    Uses regex patterns to identify learning moments:
    - Corrections (user corrects assistant)
    - Explicit learnings ("I learned that...", "discovered that...")
    - Patterns across multiple exchanges
    - Problem-solution pairs

    Args:
        conversation: Full conversation text
        project_id: Project identifier for created memories
        memory_factory: Callable that creates SessionMemory instances.
            Signature: memory_factory(content, importance, project_id) -> SessionMemory

    Returns:
        List of extracted SessionMemory objects
    """
    memories = []

    # Pattern 1: Explicit learning statements
    for pattern in LEARNING_PATTERNS:
        matches = pattern.finditer(conversation)
        for match in matches:
            learning_content = match.group(1).strip()
            if len(learning_content) > 50 and len(learning_content) < 2000 and not is_garbage_content(learning_content):
                importance = calculate_importance(learning_content)
                if importance >= 0.5:  # Threshold for saving
                    memories.append(memory_factory(
                        content=learning_content,
                        importance=importance,
                        project_id=project_id,
                    ))

    # Pattern 2: User corrections (important signals)
    for pattern in CORRECTION_PATTERNS:
        matches = pattern.finditer(conversation)
        for match in matches:
            correction_content = match.group(1).strip()
            if len(correction_content) > 50 and len(correction_content) < 2000 and not is_garbage_content(correction_content):
                # Corrections get boosted importance
                base_importance = calculate_importance(correction_content)
                boosted_importance = min(0.95, base_importance * 1.2)
                memories.append(memory_factory(
                    content=f"Correction: {correction_content}",
                    importance=boosted_importance,
                    project_id=project_id,
                ))

    # Pattern 3: Problem-solution pairs
    matches = PROBLEM_SOLUTION_PATTERN.finditer(conversation)
    for match in matches:
        problem = match.group(1).strip()
        solution = match.group(2).strip()
        if len(problem) > 20 and len(solution) > 20 and not is_garbage_content(problem) and not is_garbage_content(solution):
            content = f"Problem: {problem} Solution: {solution}"
            importance = calculate_importance(content)
            if importance >= 0.6:
                memories.append(memory_factory(
                    content=content,
                    importance=importance,
                    project_id=project_id,
                ))

    # Pattern 4: Assistant insights in response to questions
    assistant_insights = ASSISTANT_INSIGHT_PATTERN.finditer(conversation)

    insight_count = 0
    for match in assistant_insights:
        if insight_count >= 3:  # Limit to top insights per session
            break

        insight = match.group(1).strip()

        # Filter out trivial responses and garbage
        if is_garbage_content(insight):
            continue
        if len(insight) > 2000:
            continue
        if any(phrase in insight.lower() for phrase in [
            "let me", "i'll", "here's", "sure", "okay", "got it"
        ]):
            continue

        # Check for learning indicators (expanded list)
        if any(indicator in insight.lower() for indicator in [
            "better to", "key is", "important", "pattern", "approach",
            "when you", "if you", "works well", "effective", "i've found",
            "rather than", "instead of", "acknowledge", "reframe", "ask",
            "often hide", "surface", "recommend"
        ]):
            importance = calculate_importance(insight)
            if importance >= 0.5:  # Lower threshold to catch more insights
                memories.append(memory_factory(
                    content=insight,
                    importance=importance,
                    project_id=project_id,
                ))
                insight_count += 1

    return memories
