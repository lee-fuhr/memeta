"""
Pattern recall — detect problem-solving and surface past solutions.

Feature 126: When the user hits a problem, proactively search memory
for past solutions they've already found. Uses BM25-only search to
stay within the ~50ms hook budget.

Multi-signal scoring prevents false positives from meta-references
like "implement error handling" (which is NOT a real error).
"""

import re
from pathlib import Path

from memory_system.hybrid_search import keyword_search
from memory_system.memory_injector import _parse_frontmatter

# --- Problem indicator patterns ---

PROBLEM_INDICATORS: dict[str, list[str]] = {
    "error_message": [r"error:", r"Error:", r"ERROR", r"exception:", r"traceback"],
    "stack_trace": [r'File ".*", line \d+', r"at .*:\d+:\d+"],
    "frustration": [r"not working", r"doesn't work", r"broken", r"keeps failing"],
    "help_request": [r"how do I", r"how can I", r"what's the .* way to"],
}

# Phrases that signal meta-reference (talking ABOUT errors, not having them)
_META_PREFIXES = re.compile(
    r"\b(implement|add|create|build|design|write|handle|show|display|render)\b",
    re.IGNORECASE,
)

# Max content display length in formatted output
_MAX_CONTENT_DISPLAY = 200

# Cooldown: minimum exchanges between pattern recall injections
_COOLDOWN_EXCHANGES = 5


def calculate_problem_signal_strength(prompt: str) -> float:
    """Calculate how likely this prompt contains a real problem.

    Multi-signal scoring:
    - 2+ indicator types matched = high signal (>0.5)
    - Single type matched = low signal (<0.3)
    - No matches = 0.0

    Meta-references about errors (e.g. "implement error handling")
    are detected and reduce signal strength.

    Args:
        prompt: The user's prompt text.

    Returns:
        Float score in [0.0, 1.0].
    """
    if not prompt or not prompt.strip():
        return 0.0

    matched_types: set[str] = set()

    for indicator_type, patterns in PROBLEM_INDICATORS.items():
        for pattern in patterns:
            if re.search(pattern, prompt):
                matched_types.add(indicator_type)
                break  # One match per type is enough

    if not matched_types:
        return 0.0

    # Check for meta-references: if the prompt contains construction
    # verbs near the indicator text, it's likely talking ABOUT errors,
    # not experiencing them.
    is_meta = bool(_META_PREFIXES.search(prompt))

    type_count = len(matched_types)

    if is_meta:
        # Meta-reference: even multiple types get penalised heavily
        return min(0.2, type_count * 0.1)

    if type_count >= 2:
        # Multiple distinct signal types = genuine problem
        # 2 types → 0.6, 3 → 0.75, 4 → 0.9
        return min(1.0, 0.45 + type_count * 0.15)

    # Single type = weak signal
    return 0.2


def extract_problem_query(prompt: str) -> str:
    """Extract a search query from a problem description.

    Strips code blocks, long file paths, and excess whitespace.
    Preserves natural language sentences containing problem context.
    Limits output to 200 chars for search efficiency.

    Args:
        prompt: The user's problem description.

    Returns:
        Cleaned search query string, or empty string.
    """
    if not prompt or not prompt.strip():
        return ""

    text = prompt

    # Strip fenced code blocks (```...```)
    text = re.sub(r"```[\s\S]*?```", " ", text)

    # Strip inline code (`...`)
    text = re.sub(r"`[^`]+`", " ", text)

    # Strip long file paths (>50 chars that look like paths)
    text = re.sub(r"/?(?:[a-zA-Z0-9._-]+/){3,}[a-zA-Z0-9._-]+", _strip_long_path, text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Limit to 200 chars
    if len(text) > 200:
        text = text[:200].rsplit(" ", 1)[0]

    return text.strip()


def _strip_long_path(match: re.Match) -> str:
    """Remove path if longer than 50 chars, keep if shorter."""
    path = match.group(0)
    if len(path) > 50:
        return " "
    return path


def search_past_solutions(
    query: str,
    memory_dir: Path,
    top_k: int = 5,
) -> list[dict]:
    """Search memories for past solutions.

    Loads memory files from memory_dir, filters for problem_solution
    context_type if available, runs keyword_search.
    Falls back to unfiltered search if no problem_solution results.

    Args:
        query: Extracted problem query.
        memory_dir: Path to directory containing memory .md files.
        top_k: Max results to return.

    Returns:
        List of memory dicts with BM25 scores.
    """
    memory_dir = Path(memory_dir)
    if not memory_dir.exists():
        return []

    all_memories = _load_memories_from_dir(memory_dir)
    if not all_memories:
        return []

    # Try problem_solution memories first
    solution_memories = [
        m for m in all_memories
        if m.get("context_type") == "problem_solution"
    ]

    if solution_memories:
        results = keyword_search(query=query, memories=solution_memories, top_k=top_k)
        if results:
            return results

    # Fall back to all memories
    return keyword_search(query=query, memories=all_memories, top_k=top_k)


def _load_memories_from_dir(memory_dir: Path) -> list[dict]:
    """Load all memory files from a directory into dicts.

    Parses YAML frontmatter to extract metadata, uses markdown body
    as the 'content' field for BM25 search.

    Args:
        memory_dir: Directory containing .md memory files.

    Returns:
        List of memory dicts with at least 'id' and 'content' keys.
    """
    memories: list[dict] = []

    for filepath in sorted(memory_dir.glob("*.md")):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            if not meta.get("id") or not body.strip():
                continue

            memories.append({
                "id": meta["id"],
                "content": body.strip(),
                "context_type": meta.get("context_type", "knowledge"),
                "importance": meta.get("importance_weight", meta.get("importance", 0.5)),
                "tags": meta.get("semantic_tags", meta.get("tags", [])),
            })
        except (ValueError, OSError, UnicodeDecodeError):
            continue

    return memories


def format_pattern_recall(memories: list[dict]) -> str:
    """Format past solutions for display.

    Header: "=== YOU'VE SEEN THIS BEFORE ==="
    Each memory: truncated content + score indicator.
    Returns empty string if no memories.

    Args:
        memories: List of memory dicts with 'content' key.

    Returns:
        Formatted string, or empty string.
    """
    if not memories:
        return ""

    lines = ["=== YOU'VE SEEN THIS BEFORE ==="]
    for i, mem in enumerate(memories, 1):
        content = mem.get("content", "")
        if len(content) > _MAX_CONTENT_DISPLAY:
            content = content[:_MAX_CONTENT_DISPLAY - 3] + "..."

        score = mem.get("hybrid_score", mem.get("bm25_score", 0.0))
        if score >= 0.7:
            indicator = "***"
        elif score >= 0.4:
            indicator = "**"
        else:
            indicator = "*"

        lines.append(f"[{i}] {indicator} {content}")

    lines.append("================================")
    return "\n".join(lines)


def should_inject_for_problem(prompt: str, session_state: dict) -> bool:
    """Decide whether to inject pattern recall.

    Conditions (ALL must be true):
    - signal_strength > 0.5
    - Cooldown: at least 5 exchanges since last pattern recall injection

    Args:
        prompt: Current user prompt.
        session_state: Dict with at minimum 'exchange_count' (int) and
                      optionally 'last_pattern_recall_exchange' (int).

    Returns:
        True if pattern recall should be injected.
    """
    signal = calculate_problem_signal_strength(prompt)
    if signal <= 0.5:
        return False

    exchange_count = session_state.get("exchange_count", 0)
    last_recall = session_state.get("last_pattern_recall_exchange", 0)

    if (exchange_count - last_recall) < _COOLDOWN_EXCHANGES:
        return False

    return True
