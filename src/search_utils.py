"""Shared search utilities — match reasons and snippet extraction.

Used by both the CLI search and the dashboard search to provide
consistent match-reason labelling and contextual snippet display.
"""


def match_reasons(
    query: str,
    memory_content: str,
    memory_tags: list,
    memory_domain: str,
) -> list[str]:
    """Return list of human-readable match reason strings.

    Checks body content, tags, and domain for query substring matches
    (case-insensitive).

    Args:
        query: Search query string.
        memory_content: Full body text of the memory.
        memory_tags: List of tag strings attached to the memory.
        memory_domain: Knowledge domain string (e.g. "engineering").

    Returns:
        List of reason strings, e.g. ["body match", "tag match: #python"].
        Empty list when nothing matches.
    """
    reasons: list[str] = []
    query_lower = query.lower()

    if query_lower in memory_content.lower():
        reasons.append("body match")

    for tag in memory_tags:
        if query_lower in tag.lower():
            reasons.append(f"tag match: #{tag}")

    if query_lower in memory_domain.lower():
        reasons.append(f"domain match: {memory_domain}")

    return reasons


def extract_snippet(content: str, query: str, window: int = 120) -> str:
    """Extract a content snippet centered on the query match.

    If the query is not found, returns the beginning of the content
    (up to *window* characters).

    Args:
        content: Full text to extract snippet from.
        query: Search term to centre the snippet on.
        window: Approximate total character width of the snippet.

    Returns:
        Snippet string, potentially prefixed/suffixed with ``"..."``.
    """
    idx = content.lower().find(query.lower())

    if idx == -1:
        # No match — return beginning of content
        if len(content) <= window:
            return content
        return content[:window] + "..."

    start = max(0, idx - window // 2)
    end = min(len(content), idx + len(query) + window // 2)

    snippet = content[start:end]

    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet
