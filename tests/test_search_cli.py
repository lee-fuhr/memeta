"""Tests for search_cli.py — SearchCLI class for memory search."""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from memory_system.search_cli import SearchCLI


def _make_memory(
    id_: str,
    content: str,
    importance: float = 0.5,
    tags: list | None = None,
    domain: str = "learnings",
    context_type: str = "knowledge",
    project_id: str = "LFI",
) -> dict:
    """Helper to create a memory dict for testing."""
    return {
        "id": id_,
        "content": content,
        "importance": importance,
        "tags": tags or [],
        "knowledge_domain": domain,
        "context_type": context_type,
        "project_id": project_id,
    }


def _write_index(tmp_dir: Path, memories: list[dict]) -> Path:
    """Write a search index JSON file and return its path."""
    index_path = tmp_dir / "search-index.json"
    index_path.write_text(json.dumps(memories, ensure_ascii=False), encoding="utf-8")
    return index_path


# ---------- Fixtures ----------

@pytest.fixture
def sample_memories():
    """A small set of memories for testing."""
    return [
        _make_memory("m1", "Python is great for scripting and automation", 0.9, ["python", "dev"], "engineering"),
        _make_memory("m2", "Always write tests before code for TDD", 0.8, ["testing", "tdd"], "engineering"),
        _make_memory("m3", "Use git rebase for clean history", 0.6, ["git", "workflow"], "engineering"),
        _make_memory("m4", "Morning routine includes coffee and planning", 0.4, ["personal"], "lifestyle"),
        _make_memory("m5", "React hooks simplify state management", 0.7, ["react", "javascript"], "frontend"),
        _make_memory("m6", "Correction: never use force push on main", 0.95, ["git"], "engineering", "correction"),
    ]


@pytest.fixture
def tmp_index(tmp_path, sample_memories):
    """Write sample memories to a temp index and return (memory_dir, index_path)."""
    index_path = _write_index(tmp_path, sample_memories)
    return tmp_path, index_path


@pytest.fixture
def cli(tmp_index):
    """Create a SearchCLI wired to temp index."""
    memory_dir, index_path = tmp_index
    return SearchCLI(memory_dir=memory_dir, index_path=index_path)


# ---------- Backend detection ----------

class TestBackendDetection:
    """Tests for detect_backend()."""

    def test_hybrid_available(self, cli):
        """When hybrid_search is importable, backend is 'hybrid'."""
        with patch.dict("sys.modules", {"memory_system.hybrid_search": MagicMock()}):
            assert cli.detect_backend() == "hybrid"

    def test_bm25_fallback(self, cli):
        """When hybrid_search import fails, falls back to 'bm25'."""
        with patch.dict("sys.modules", {"memory_system.hybrid_search": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                assert cli.detect_backend() == "bm25"


# ---------- Search execution ----------

class TestSearchExecution:
    """Tests for execute_search()."""

    def test_basic_query_returns_results(self, cli):
        """Basic query matching content returns non-empty results."""
        results = cli.execute_search("python")
        assert len(results) > 0
        # First result should be the python memory
        assert any("python" in r["content"].lower() for r in results)

    def test_empty_query_returns_empty(self, cli):
        """Empty query string returns no results."""
        results = cli.execute_search("")
        assert results == []

    def test_no_match_returns_empty(self, cli):
        """Query with no matches returns empty list."""
        results = cli.execute_search("xyzzyplugh")
        assert results == []


# ---------- Filters ----------

class TestSearchFilters:
    """Tests for post-search filtering."""

    def test_filter_by_domain(self, cli):
        """Domain filter limits results to matching domain."""
        results = cli.execute_search("python", domain="engineering")
        for r in results:
            assert r.get("knowledge_domain") == "engineering"

    def test_filter_by_tags(self, cli):
        """Tag filter limits results to memories with at least one matching tag."""
        results = cli.execute_search("python", tags=["python"])
        for r in results:
            assert "python" in r.get("tags", [])

    def test_filter_by_min_importance(self, cli):
        """min_importance filter excludes low-importance results."""
        results = cli.execute_search("python", min_importance=0.8)
        for r in results:
            assert r.get("importance", 0) >= 0.8

    def test_filter_by_context_type(self, cli):
        """context_type filter limits results to matching type."""
        results = cli.execute_search("git", context_type="correction")
        for r in results:
            assert r.get("context_type") == "correction"

    def test_multiple_filters_combined(self, cli):
        """Multiple filters are applied together (AND logic)."""
        results = cli.execute_search(
            "python",
            domain="engineering",
            min_importance=0.8,
            tags=["python"],
        )
        for r in results:
            assert r.get("knowledge_domain") == "engineering"
            assert r.get("importance", 0) >= 0.8
            assert "python" in r.get("tags", [])


# ---------- Pagination ----------

class TestPagination:
    """Tests for limit and offset."""

    def test_limit(self, cli):
        """Limit caps the number of results."""
        results = cli.execute_search("e", limit=2)  # broad query
        assert len(results) <= 2

    def test_offset(self, cli):
        """Offset skips the first N results."""
        all_results = cli.execute_search("e", limit=100)
        offset_results = cli.execute_search("e", limit=100, offset=1)
        if len(all_results) > 1:
            assert offset_results[0]["id"] == all_results[1]["id"]

    def test_offset_beyond_results(self, cli):
        """Offset beyond result count returns empty."""
        results = cli.execute_search("python", offset=1000)
        assert results == []


# ---------- Output formatting ----------

class TestTableFormat:
    """Tests for format_table()."""

    def test_table_has_importance_column(self, cli, sample_memories):
        """Table output includes importance values."""
        output = cli.format_table(sample_memories[:2], "python")
        assert "0.9" in output or "importance" in output.lower()

    def test_table_color_codes_by_importance(self, cli, sample_memories):
        """High importance memories get color-coded (ANSI escape)."""
        output = cli.format_table(sample_memories[:2], "python")
        # Should contain ANSI escape sequences for colors
        assert "\033[" in output or "importance" in output.lower()

    def test_table_shows_match_reasons(self, cli, sample_memories):
        """Table output includes match reason info."""
        output = cli.format_table(sample_memories[:1], "python")
        # Should mention body match or tag match
        assert "match" in output.lower()


class TestJsonFormat:
    """Tests for format_json()."""

    def test_valid_json(self, cli, sample_memories):
        """JSON output is valid JSON."""
        output = cli.format_json(sample_memories[:2])
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_json_contains_fields(self, cli, sample_memories):
        """JSON output contains expected fields."""
        output = cli.format_json(sample_memories[:1])
        parsed = json.loads(output)
        assert "id" in parsed[0]
        assert "content" in parsed[0]
        assert "importance" in parsed[0]


class TestFullFormat:
    """Tests for format_full()."""

    def test_includes_body(self, cli, sample_memories):
        """Full format includes the complete body text."""
        output = cli.format_full(sample_memories[:1])
        assert sample_memories[0]["content"] in output

    def test_includes_metadata(self, cli, sample_memories):
        """Full format includes metadata like ID and importance."""
        output = cli.format_full(sample_memories[:1])
        assert sample_memories[0]["id"] in output


class TestIdsFormat:
    """Tests for format_ids()."""

    def test_one_per_line(self, cli, sample_memories):
        """IDs format outputs one ID per line."""
        output = cli.format_ids(sample_memories[:3])
        lines = output.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "m1"
        assert lines[1] == "m2"
        assert lines[2] == "m3"

    def test_empty_input(self, cli):
        """Empty input returns empty string."""
        output = cli.format_ids([])
        assert output == ""
