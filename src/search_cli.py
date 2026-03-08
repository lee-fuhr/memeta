"""CLI search interface for memeta memories.

Provides SearchCLI class with backend detection, filtered search execution,
and multiple output formats (table, JSON, full, IDs).
"""

import json
from pathlib import Path

from memory_system.memory_injector import (
    DEFAULT_INDEX_PATH,
    DEFAULT_MEMORY_DIR,
    load_search_index,
)
from memory_system.search_utils import match_reasons, extract_snippet


class SearchCLI:
    """Interactive search interface for memory files.

    Loads the pre-built JSON search index, executes BM25 search,
    applies post-search filters, and formats output in several styles.
    """

    def __init__(
        self,
        memory_dir: Path | None = None,
        index_path: Path | None = None,
    ) -> None:
        self.memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
        self.index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH

    # ── Backend detection ────────────────────────────────────────────────

    def detect_backend(self) -> str:
        """Detect available search backend.

        Returns:
            ``"hybrid"`` when the hybrid_search module is importable,
            ``"bm25"`` otherwise.
        """
        try:
            from memory_system.hybrid_search import hybrid_search  # noqa: F401
            return "hybrid"
        except ImportError:
            return "bm25"

    # ── Search execution ─────────────────────────────────────────────────

    def execute_search(
        self,
        query: str,
        domain: str | None = None,
        tags: list[str] | None = None,
        min_importance: float | None = None,
        context_type: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        """Execute search with optional post-search filters.

        Uses BM25 keyword search from ``hybrid_search.keyword_search``,
        then applies domain / tag / importance / context_type filters,
        pagination via *offset* and *limit*.

        Args:
            query: Search query string. Empty string returns [].
            domain: If set, only return memories whose ``knowledge_domain``
                matches this value.
            tags: If set, only return memories that have at least one of
                these tags.
            min_importance: If set, exclude memories below this threshold.
            context_type: If set, only return memories whose
                ``context_type`` matches.
            limit: Maximum number of results to return.
            offset: Number of leading results to skip (pagination).

        Returns:
            list of memory dicts (may be empty).
        """
        if not query or not query.strip():
            return []

        memories = load_search_index(self.index_path)
        if not memories:
            return []

        # BM25 search — over-fetch to allow for filter attrition
        from memory_system.hybrid_search import keyword_search
        raw = keyword_search(query=query, memories=memories, top_k=limit * 5 + 50)

        # Drop zero-score results (BM25 returns all docs, scored 0 when no match)
        raw = [m for m in raw if m.get("bm25_score", 0.0) > 0.0]

        # Post-search filters
        filtered = self._apply_filters(
            raw,
            domain=domain,
            tags=tags,
            min_importance=min_importance,
            context_type=context_type,
        )

        # Pagination
        return filtered[offset : offset + limit]

    @staticmethod
    def _apply_filters(
        memories: list[dict],
        domain: str | None = None,
        tags: list[str] | None = None,
        min_importance: float | None = None,
        context_type: str | None = None,
    ) -> list[dict]:
        """Apply domain / tag / importance / context-type filters."""
        result = memories

        if domain is not None:
            result = [m for m in result if m.get("knowledge_domain") == domain]

        if tags:
            tag_set = set(tags)
            result = [
                m for m in result
                if tag_set & set(m.get("tags", []))
            ]

        if min_importance is not None:
            result = [
                m for m in result
                if m.get("importance", 0) >= min_importance
            ]

        if context_type is not None:
            result = [m for m in result if m.get("context_type") == context_type]

        return result

    # ── Output formatting ────────────────────────────────────────────────

    def format_table(self, results: list[dict], query: str) -> str:
        """Format results as a coloured, human-readable table.

        Columns: #, ID (truncated), Importance, Snippet, Match reasons.
        High-importance rows (>= 0.8) are highlighted with ANSI bold/colour.

        Args:
            results: list of memory dicts.
            query: Original query (used for snippet extraction and match reasons).

        Returns:
            Multi-line string ready for terminal display.
        """
        if not results:
            return "No results."

        lines: list[str] = []
        # Header
        lines.append(
            f"{'#':>3}  {'ID':<12}  {'Imp':>5}  {'Snippet':<50}  {'Match reasons'}"
        )
        lines.append("-" * 100)

        for idx, mem in enumerate(results, 1):
            mid = mem.get("id", "?")[:12]
            importance = mem.get("importance", 0.0)
            content = mem.get("content", "")
            tags = mem.get("tags", [])
            domain = mem.get("knowledge_domain", "")

            snippet = extract_snippet(content, query, window=48)
            reasons = match_reasons(query, content, tags, domain)
            reason_str = ", ".join(reasons) if reasons else "-"

            imp_str = f"{importance:.2f}"

            # Colour-code high importance (ANSI bold yellow)
            if importance >= 0.8:
                row = (
                    f"\033[1;33m{idx:>3}  {mid:<12}  {imp_str:>5}  "
                    f"{snippet:<50}  {reason_str}\033[0m"
                )
            else:
                row = (
                    f"{idx:>3}  {mid:<12}  {imp_str:>5}  "
                    f"{snippet:<50}  {reason_str}"
                )

            lines.append(row)

        lines.append(f"\n{len(results)} result(s)")
        return "\n".join(lines)

    def format_json(self, results: list[dict]) -> str:
        """Format results as a JSON array.

        Args:
            results: list of memory dicts.

        Returns:
            Pretty-printed JSON string.
        """
        return json.dumps(results, indent=2, ensure_ascii=False)

    def format_full(self, results: list[dict]) -> str:
        """Format results with full body content.

        Each memory is separated by a horizontal rule. Includes ID,
        importance, tags, domain, and the complete body text.

        Args:
            results: list of memory dicts.

        Returns:
            Multi-line string with full details per memory.
        """
        if not results:
            return "No results."

        blocks: list[str] = []
        for mem in results:
            mid = mem.get("id", "?")
            importance = mem.get("importance", 0.0)
            tags = ", ".join(mem.get("tags", []))
            domain = mem.get("knowledge_domain", "")
            ctx = mem.get("context_type", "")
            body = mem.get("content", "")

            block = (
                f"--- {mid} ---\n"
                f"importance: {importance}  |  domain: {domain}  |  "
                f"type: {ctx}  |  tags: [{tags}]\n\n"
                f"{body}\n"
            )
            blocks.append(block)

        return "\n".join(blocks)

    def format_ids(self, results: list[dict]) -> str:
        """Format results as one ID per line.

        Args:
            results: list of memory dicts.

        Returns:
            Newline-separated IDs, or empty string for no results.
        """
        if not results:
            return ""
        return "\n".join(m.get("id", "") for m in results)
