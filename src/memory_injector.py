"""
Memory injector — search and inject relevant memories into Claude context.

Uses pre-built BM25 search index for fast (~50ms) memory retrieval in hooks.
Dual relevance gate (absolute BM25 floor + normalized threshold) ensures
only genuinely relevant memories are injected.

Strategy parameter allows future switch from BM25 to hybrid search.
"""

import json
from pathlib import Path
from typing import Optional

from memory_system.hybrid_search import keyword_search

# --- Constants ---

DEFAULT_INDEX_PATH = Path.home() / ".local/share/memory/memory-search-index.json"
DEFAULT_MEMORY_DIR = Path.home() / ".local/share/memory/default/memories"
BM25_FLOOR = 1.0
NORMALIZED_THRESHOLD = 0.3
DEFAULT_TOP_K = 3
MAX_CONTENT_DISPLAY = 300


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from memory file text.

    Simple parser that splits on --- markers and extracts key: value pairs.
    Does not require PyYAML.

    Args:
        text: Full file content with --- delimited frontmatter.

    Returns:
        Tuple of (frontmatter_dict, body_content).

    Raises:
        ValueError: If frontmatter markers are missing or malformed.
    """
    # Strip leading whitespace/newlines
    text = text.strip()

    if not text.startswith("---"):
        raise ValueError("No opening --- marker")

    # Find the closing --- (skip the opening one)
    rest = text[3:].lstrip("\n")
    closing_idx = rest.find("\n---")
    if closing_idx == -1:
        raise ValueError("No closing --- marker")

    frontmatter_text = rest[:closing_idx]
    body = rest[closing_idx + 4:].strip()  # skip \n---

    # Parse key: value pairs from frontmatter
    meta = {}
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_idx = line.find(":")
        if colon_idx == -1:
            continue

        key = line[:colon_idx].strip()
        value = line[colon_idx + 1:].strip()

        # Parse common types
        if value.lower() in ("null", "none", "~"):
            meta[key] = None
        elif value.lower() == "true":
            meta[key] = True
        elif value.lower() == "false":
            meta[key] = False
        elif value.startswith("[") and value.endswith("]"):
            # JSON array (tags)
            try:
                meta[key] = json.loads(value)
            except json.JSONDecodeError:
                meta[key] = value
        else:
            # Try numeric
            try:
                meta[key] = float(value)
                if meta[key] == int(meta[key]) and "." not in value:
                    meta[key] = int(meta[key])
            except ValueError:
                meta[key] = value

    return meta, body


def build_search_index(
    memory_dir: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> int:
    """
    Scan memory YAML files and build a minimal JSON search index.

    Extracts {id, content, importance, tags, project_id} per memory.
    Uses atomic write (.tmp + rename) to prevent partial reads.

    Args:
        memory_dir: Directory containing memory .md files.
            Defaults to DEFAULT_MEMORY_DIR.
        output_path: Path to write the JSON index.
            Defaults to DEFAULT_INDEX_PATH.

    Returns:
        Count of indexed memories.
    """
    memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
    output_path = Path(output_path) if output_path else DEFAULT_INDEX_PATH

    entries = []

    if not memory_dir.exists():
        # Write empty index
        _atomic_write_json(output_path, entries)
        return 0

    for filepath in sorted(memory_dir.glob("*.md")):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            if not meta.get("id"):
                continue

            entry = {
                "id": meta["id"],
                "content": body.strip(),
                "importance": meta.get("importance_weight", meta.get("importance", 0.5)),
                "tags": meta.get("semantic_tags", meta.get("tags", [])),
                "project_id": meta.get("project_id", ""),
                "context_type": meta.get("context_type", "knowledge"),
            }

            if entry["content"]:
                entries.append(entry)

        except (ValueError, OSError, UnicodeDecodeError):
            # Skip corrupt or unreadable files
            continue

    _atomic_write_json(output_path, entries)
    return len(entries)


def _atomic_write_json(path: Path, data: list) -> None:
    """Write JSON atomically using tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        # Clean up tmp file on failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def load_search_index(index_path: Optional[Path] = None) -> list[dict]:
    """
    Load the pre-built JSON search index.

    Args:
        index_path: Path to the JSON index file.
            Defaults to DEFAULT_INDEX_PATH.

    Returns:
        List of memory dicts. Empty list if file is missing or corrupt.
    """
    index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH

    if not index_path.exists():
        return []

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []


def search_memories(
    query: str,
    memories: Optional[list[dict]] = None,
    index_path: Optional[Path] = None,
    top_k: int = DEFAULT_TOP_K,
    strategy: str = "bm25",
    min_score: float = BM25_FLOOR,
    min_normalized: float = NORMALIZED_THRESHOLD,
) -> list[dict]:
    """
    Search memories using specified strategy with dual relevance gate.

    Loads index if memories not provided. Applies absolute BM25 floor
    and normalized threshold. Returns top_k results that pass both gates.

    Args:
        query: Search query string.
        memories: Pre-loaded memory list. If None, loads from index_path.
        index_path: Path to JSON index (used if memories is None).
        top_k: Maximum results to return.
        strategy: Search strategy ("bm25" or future "hybrid").
        min_score: Absolute BM25 score floor.
        min_normalized: Normalized BM25 score threshold.

    Returns:
        List of memory dicts that pass both relevance gates, sorted by score.
    """
    if not query or not query.strip():
        return []

    if memories is None:
        memories = load_search_index(index_path)

    if not memories:
        return []

    # Use keyword_search (BM25-only) — fast, no model loading
    # Request more results than top_k since we'll filter
    raw_results = keyword_search(
        query=query,
        memories=memories,
        top_k=top_k * 3,  # over-fetch for filtering
    )

    # Apply dual relevance gate
    filtered = []
    for result in raw_results:
        bm25 = result.get("bm25_score", 0.0)
        normalized = result.get("bm25_score_normalized", 0.0)

        if bm25 >= min_score and normalized >= min_normalized:
            filtered.append(result)

    # Return top_k after filtering
    return filtered[:top_k]


def format_injection(memories: list[dict], context: str = "session") -> str:
    """
    Format memories for injection into Claude context.

    Args:
        memories: List of memory dicts with 'content' and 'importance' keys.
        context: "session" for rich format at session start,
                 "prompt" for compact format during session.

    Returns:
        Formatted string, or empty string if no memories.
    """
    if not memories:
        return ""

    if context == "session":
        return _format_session(memories)
    else:
        return _format_prompt(memories)


def _truncate(text: str, max_len: int = MAX_CONTENT_DISPLAY) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _format_corrections(corrections: list[dict]) -> str:
    """Format correction memories in a separate block for session start.

    Args:
        corrections: List of correction memory dicts with 'content' key.

    Returns:
        Formatted corrections block, or empty string if no corrections.
    """
    if not corrections:
        return ""
    lines = ["=== ACTIVE CORRECTIONS ==="]
    for i, mem in enumerate(corrections, 1):
        content = _truncate(mem.get("content", ""))
        # Strip "Correction: " prefix for cleaner display
        if content.lower().startswith("correction: "):
            content = content[len("correction: "):]
        lines.append(f"[{i}] {content}")
    lines.append("===========================")
    return "\n".join(lines)


def _format_session(memories: list[dict]) -> str:
    """Format memories in rich session-start format."""
    lines = ["=== RELEVANT MEMORIES ==="]
    for i, mem in enumerate(memories, 1):
        importance = mem.get("importance", 0.0)
        content = _truncate(mem.get("content", ""))
        lines.append(f"[{i}] (importance: {importance}) {content}")
    lines.append("========================")
    return "\n".join(lines)


def _format_prompt(memories: list[dict]) -> str:
    """Format memories in compact prompt format."""
    contents = [_truncate(m.get("content", ""), 200) for m in memories]
    joined = " | ".join(contents)
    return f"Relevant context: {joined}"


def inject_at_session_start(
    project: Optional[str] = None,
    index_path: Optional[Path] = None,
) -> str:
    """
    High-level function for SessionStart hook.

    Searches for project-relevant memories and recent high-importance ones.
    Surfaces correction memories in a separate block before regular memories.

    Args:
        project: Project ID to filter memories (e.g., "my-project").
        index_path: Path to JSON index file.

    Returns:
        Formatted injection string, or empty string if no relevant memories.
    """
    all_memories = load_search_index(index_path)
    if not all_memories:
        return ""

    # Separate corrections from regular memories
    corrections = [
        m for m in all_memories
        if m.get("context_type") == "correction"
    ]
    regular_memories = [
        m for m in all_memories
        if m.get("context_type") != "correction"
    ]

    # Filter corrections by project if specified
    if project and corrections:
        corrections = [
            c for c in corrections
            if c.get("project_id", "") == project
        ]

    # Format corrections block (top 3 by importance)
    corrections.sort(key=lambda m: m.get("importance", 0), reverse=True)
    corrections_block = _format_corrections(corrections[:3])

    # --- Regular memories logic (unchanged from original) ---
    memories = regular_memories
    query_parts = []
    if project:
        query_parts.append(project)
        # Filter to project-relevant memories
        project_memories = [
            m for m in memories
            if m.get("project_id", "") == project
        ]
        if project_memories:
            memories = project_memories

    # Also find high-importance memories
    high_importance = [
        m for m in memories
        if m.get("importance", 0) >= 0.8
    ]

    # Search with project as query, or use high-importance directly
    if query_parts:
        results = search_memories(
            query=" ".join(query_parts),
            memories=memories,
            top_k=DEFAULT_TOP_K,
            min_score=0.5,  # Lower threshold for session start
            min_normalized=0.2,
        )
    else:
        results = []

    # Merge high-importance memories (deduplicated)
    seen_ids = {r.get("id") for r in results}
    for mem in high_importance[:DEFAULT_TOP_K]:
        if mem.get("id") not in seen_ids:
            results.append(mem)
            seen_ids.add(mem.get("id"))

    results = results[:DEFAULT_TOP_K]
    regular_block = format_injection(results, context="session")

    # Combine: corrections first, then regular memories
    parts = []
    if corrections_block:
        parts.append(corrections_block)
    if regular_block:
        parts.append(regular_block)

    return "\n\n".join(parts)


def inject_for_prompt(
    prompt: str,
    exclude_ids: Optional[list] = None,
    index_path: Optional[Path] = None,
) -> str:
    """
    High-level function for UserPromptSubmit hook.

    Searches based on user prompt, excludes already-injected IDs.
    Returns formatted injection string in compact format.

    Args:
        prompt: The user's prompt text to search against.
        exclude_ids: List of memory IDs already injected this session.
        index_path: Path to JSON index file.

    Returns:
        Formatted injection string, or empty string if no relevant memories.
    """
    exclude_ids = set(exclude_ids or [])

    memories = load_search_index(index_path)
    if not memories:
        return ""

    # Filter out already-injected memories before search
    if exclude_ids:
        memories = [m for m in memories if m.get("id") not in exclude_ids]

    if not memories:
        return ""

    results = search_memories(
        query=prompt,
        memories=memories,
        top_k=DEFAULT_TOP_K,
    )

    return format_injection(results, context="prompt")
