"""
Agent context function - Memory briefings for delegated agents.

Provides agent-type-aware memory context with tag filtering and
correction surfacing for delegated agent tasks.
"""

from typing import List, Dict, Tuple, Optional
from . import hybrid_search as hybrid_search_module


# Agent-type to semantic tag mapping
# Maps agent types to relevant tags for filtering
AGENT_TAG_MAP = {
    "dev": ["development", "python", "typescript", "code-quality", "testing", "infrastructure"],
    "brand": ["brand", "messaging", "voice", "positioning"],
    "copywriter": ["writing", "copy", "content", "messaging"],
    "seo": ["seo", "keywords", "content"],
    "designer": ["design", "visual", "ui", "ux"],
    "researcher": ["research", "analysis", "data"],
    "relationship": ["relationship", "client", "personal"],
    # Add more agent types as needed
}


def get_context_for_agent(
    agent_type: str,
    task_description: str,
    memories: Optional[List[Dict]] = None,
    top_k: int = 5,
    project_id: Optional[str] = None
) -> Tuple[str, List[str]]:
    """
    Get memory context for a delegated agent task.

    Uses hybrid search (semantic + BM25) to find relevant memories,
    with agent-type-aware tag filtering. Corrections always surface
    regardless of tag filter (highest value memories).

    Args:
        agent_type: Type of agent (dev, brand, copywriter, etc.)
        task_description: Description of the task the agent will perform
        memories: Optional list of memory dicts. If None, loads from search index.
        top_k: Maximum number of memories to return (default: 5)
        project_id: Optional project filter (e.g., "LFI")

    Returns:
        Tuple of (formatted_context_string, list_of_memory_ids)

    Example:
        >>> context, ids = get_context_for_agent(
        ...     agent_type="dev",
        ...     task_description="Fix TypeScript type errors",
        ...     top_k=5
        ... )
        >>> print(context)
        === RELEVANT MEMORIES ===
        [1] Correction: Never use 'any' type...
        [2] Lee prefers TDD workflow...
    """
    # Load memories if not provided
    if memories is None:
        from .memory_injector import load_search_index
        memories = load_search_index()

    if not memories:
        return "", []

    # Filter by project if specified
    if project_id:
        memories = [m for m in memories if m.get("project_id") == project_id]

    if not memories:
        return "", []

    # Separate corrections from regular memories
    # Corrections ALWAYS surface regardless of tag filter
    corrections = [
        m for m in memories
        if m.get("context_type") == "correction"
    ]
    regular_memories = [
        m for m in memories
        if m.get("context_type") != "correction"
    ]

    # Get relevant tags for this agent type
    relevant_tags = AGENT_TAG_MAP.get(agent_type, [])

    # Apply tag-aware filtering to regular memories (if we have relevant tags)
    if relevant_tags:
        # Boost memories with relevant tags, but don't exclude others
        # (hybrid search will still find semantically relevant memories)
        tag_boosted_memories = []
        for mem in regular_memories:
            mem_tags = mem.get("tags", [])
            # Calculate tag overlap score
            tag_overlap = len(set(mem_tags) & set(relevant_tags))
            # Add tag boost to importance for sorting
            boosted_mem = {**mem}
            boosted_mem["_tag_boost"] = tag_overlap * 0.1  # Small boost per matching tag
            tag_boosted_memories.append(boosted_mem)
        regular_memories = tag_boosted_memories

    # Use hybrid search on regular memories (semantic + BM25)
    # Request more than top_k to allow for correction insertion
    search_results = hybrid_search_module.hybrid_search(
        query=task_description if task_description else agent_type,
        memories=regular_memories,
        top_k=top_k * 2,  # Over-fetch to allow correction insertion
        use_semantic=True
    )

    # Boost tag-matched memories in search results
    if relevant_tags:
        for result in search_results:
            tag_boost = result.get("_tag_boost", 0)
            result["hybrid_score"] = result.get("hybrid_score", 0) + tag_boost

        # Re-sort after tag boost
        search_results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)

    # Search corrections separately (all corrections are relevant)
    if corrections:
        correction_results = hybrid_search_module.hybrid_search(
            query=task_description if task_description else "corrections",
            memories=corrections,
            top_k=top_k,  # Get all relevant corrections
            use_semantic=True
        )
    else:
        correction_results = []

    # Prioritize corrections by importance, then merge with regular results
    correction_results.sort(key=lambda x: x.get("importance", 0), reverse=True)

    # Take top corrections (up to 2) and merge with regular memories
    top_corrections = correction_results[:2]
    remaining_slots = top_k - len(top_corrections)

    # Get top regular memories (excluding any that are already in corrections)
    correction_ids = {c.get("id") for c in top_corrections}
    top_regular = [
        r for r in search_results
        if r.get("id") not in correction_ids
    ][:remaining_slots]

    # Combine: corrections first, then regular memories
    final_results = top_corrections + top_regular

    # Extract memory IDs
    memory_ids = [m.get("id") for m in final_results if m.get("id")]

    # Format context string
    context_str = _format_agent_context(final_results, agent_type)

    return context_str, memory_ids


def _format_agent_context(memories: List[Dict], agent_type: str) -> str:
    """
    Format memories into agent context string.

    Args:
        memories: List of memory dicts
        agent_type: Type of agent receiving the context

    Returns:
        Formatted context string
    """
    if not memories:
        return ""

    lines = ["=== RELEVANT MEMORIES ==="]

    for i, mem in enumerate(memories, 1):
        content = mem.get("content", "")
        importance = mem.get("importance", 0.0)
        context_type = mem.get("context_type", "knowledge")

        # Truncate long content
        if len(content) > 300:
            content = content[:297] + "..."

        # Mark corrections explicitly
        if context_type == "correction":
            lines.append(f"[{i}] ⚠️  CORRECTION (importance: {importance:.2f})")
            lines.append(f"    {content}")
        else:
            lines.append(f"[{i}] (importance: {importance:.2f}) {content}")

    lines.append("===========================")

    return "\n".join(lines)
