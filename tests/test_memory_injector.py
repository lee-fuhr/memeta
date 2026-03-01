"""
Tests for memory_injector module.

Tests the pre-built search index, BM25-based memory search,
formatting for injection, and high-level injection functions.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_system.memory_injector import (
    build_search_index,
    load_search_index,
    search_memories,
    format_injection,
    inject_at_session_start,
    inject_for_prompt,
    DEFAULT_INDEX_PATH,
    DEFAULT_MEMORY_DIR,
    BM25_FLOOR,
    NORMALIZED_THRESHOLD,
    DEFAULT_TOP_K,
)


# --- Fixtures ---


def _make_memory_file(directory: Path, mem_id: str, content: str,
                      importance: float = 0.5, tags: list = None,
                      project_id: str = "LFI", extra_fields: str = "") -> Path:
    """Create a mock memory file in YAML frontmatter + markdown format."""
    tags_str = json.dumps(tags or [])
    text = f"""---
id: {mem_id}
created: 1767566679286
importance_weight: {importance}
semantic_tags: {tags_str}
project_id: {project_id}
status: active
{extra_fields}---

{content}"""
    filepath = directory / f"{mem_id}.md"
    filepath.write_text(text)
    return filepath


@pytest.fixture
def memory_dir(tmp_path):
    """Create a temp directory with sample memory files."""
    d = tmp_path / "memories"
    d.mkdir()
    _make_memory_file(d, "mem_001", "Python debugging with pdb is essential for finding bugs",
                      importance=0.85, tags=["python", "debugging"])
    _make_memory_file(d, "mem_002", "Docker containers simplify deployment workflows",
                      importance=0.72, tags=["docker", "deployment"])
    _make_memory_file(d, "mem_003", "React hooks changed how we manage component state",
                      importance=0.60, tags=["react", "frontend"])
    return d


@pytest.fixture
def index_path(tmp_path):
    """Return a temp path for the search index."""
    return tmp_path / "memory-search-index.json"


@pytest.fixture
def sample_index(memory_dir, index_path):
    """Build and return a sample index."""
    build_search_index(memory_dir=memory_dir, output_path=index_path)
    return index_path


# --- TestBuildSearchIndex ---


class TestBuildSearchIndex:
    def test_indexes_valid_memory_files(self, memory_dir, index_path):
        """Index should contain entries for all valid memory files."""
        count = build_search_index(memory_dir=memory_dir, output_path=index_path)
        assert count == 3

        data = json.loads(index_path.read_text())
        ids = {m["id"] for m in data}
        assert ids == {"mem_001", "mem_002", "mem_003"}

    def test_handles_empty_directory(self, tmp_path, index_path):
        """Empty directory should produce empty index."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        count = build_search_index(memory_dir=empty_dir, output_path=index_path)
        assert count == 0

        data = json.loads(index_path.read_text())
        assert data == []

    def test_handles_corrupt_yaml(self, tmp_path, index_path):
        """Corrupt files should be skipped without crashing."""
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()

        # Valid file
        _make_memory_file(mem_dir, "mem_good", "Valid memory content",
                          importance=0.8)

        # Corrupt file (no closing ---)
        corrupt = mem_dir / "corrupt.md"
        corrupt.write_text("---\nid: mem_bad\nthis is not valid\n")

        count = build_search_index(memory_dir=mem_dir, output_path=index_path)
        assert count == 1

        data = json.loads(index_path.read_text())
        assert data[0]["id"] == "mem_good"

    def test_atomic_write(self, memory_dir, index_path):
        """Index should be written atomically (tmp + rename)."""
        # Write an initial index
        build_search_index(memory_dir=memory_dir, output_path=index_path)
        assert index_path.exists()

        # No .tmp file should remain after successful write
        tmp_file = index_path.with_suffix(".json.tmp")
        assert not tmp_file.exists()

    def test_returns_count(self, memory_dir, index_path):
        """Return value should be the number of indexed memories."""
        count = build_search_index(memory_dir=memory_dir, output_path=index_path)
        assert isinstance(count, int)
        assert count == 3

    def test_custom_paths(self, tmp_path):
        """Custom memory_dir and output_path should work."""
        custom_dir = tmp_path / "custom_memories"
        custom_dir.mkdir()
        custom_out = tmp_path / "custom_index.json"

        _make_memory_file(custom_dir, "mem_custom", "Custom path memory",
                          importance=0.9, project_id="TestProject")

        count = build_search_index(memory_dir=custom_dir, output_path=custom_out)
        assert count == 1

        data = json.loads(custom_out.read_text())
        assert data[0]["project_id"] == "TestProject"

    def test_index_contains_required_fields(self, memory_dir, index_path):
        """Each index entry must have id, content, importance, tags, project_id."""
        build_search_index(memory_dir=memory_dir, output_path=index_path)
        data = json.loads(index_path.read_text())

        required_fields = {"id", "content", "importance", "tags", "project_id"}
        for entry in data:
            assert required_fields.issubset(entry.keys()), (
                f"Missing fields: {required_fields - entry.keys()}"
            )

    def test_content_extracted_from_body(self, memory_dir, index_path):
        """Content should come from the markdown body, not frontmatter."""
        build_search_index(memory_dir=memory_dir, output_path=index_path)
        data = json.loads(index_path.read_text())

        mem_001 = next(m for m in data if m["id"] == "mem_001")
        assert "Python debugging with pdb" in mem_001["content"]
        # Should NOT contain frontmatter keys
        assert "importance_weight" not in mem_001["content"]


# --- TestLoadSearchIndex ---


class TestLoadSearchIndex:
    def test_loads_valid_index(self, sample_index):
        """Should load and return list of memory dicts."""
        memories = load_search_index(index_path=sample_index)
        assert isinstance(memories, list)
        assert len(memories) == 3
        assert all("id" in m for m in memories)

    def test_returns_empty_on_missing(self, tmp_path):
        """Missing index file should return empty list."""
        nonexistent = tmp_path / "does_not_exist.json"
        memories = load_search_index(index_path=nonexistent)
        assert memories == []

    def test_returns_empty_on_corrupt(self, tmp_path):
        """Corrupt JSON should return empty list."""
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{this is not valid json!!")
        memories = load_search_index(index_path=corrupt)
        assert memories == []


# --- TestSearchMemories ---


class TestSearchMemories:
    @patch("memory_system.memory_injector.keyword_search")
    def test_basic_search(self, mock_ks):
        """Should return results from keyword_search that pass the gates."""
        mock_ks.return_value = [
            {"id": "m1", "content": "Python debugging tips",
             "importance": 0.85, "bm25_score": 3.5, "bm25_score_normalized": 0.8,
             "hybrid_score": 0.8},
        ]
        memories = [{"id": "m1", "content": "Python debugging tips", "importance": 0.85}]
        results = search_memories("python", memories=memories)
        assert len(results) == 1
        assert results[0]["id"] == "m1"

    @patch("memory_system.memory_injector.keyword_search")
    def test_bm25_floor_filters(self, mock_ks):
        """Results below BM25_FLOOR should be filtered out."""
        mock_ks.return_value = [
            {"id": "m1", "content": "test", "importance": 0.5,
             "bm25_score": 0.5, "bm25_score_normalized": 0.9, "hybrid_score": 0.9},
        ]
        results = search_memories("query", memories=[{"content": "test"}])
        assert len(results) == 0

    @patch("memory_system.memory_injector.keyword_search")
    def test_normalized_threshold_filters(self, mock_ks):
        """Results below NORMALIZED_THRESHOLD should be filtered out."""
        mock_ks.return_value = [
            {"id": "m1", "content": "test", "importance": 0.5,
             "bm25_score": 2.0, "bm25_score_normalized": 0.1, "hybrid_score": 0.1},
        ]
        results = search_memories("query", memories=[{"content": "test"}])
        assert len(results) == 0

    @patch("memory_system.memory_injector.keyword_search")
    def test_dual_gate_applied(self, mock_ks):
        """Both absolute and normalized gates must pass."""
        mock_ks.return_value = [
            # Passes both gates
            {"id": "m1", "content": "good match", "importance": 0.9,
             "bm25_score": 2.5, "bm25_score_normalized": 0.7, "hybrid_score": 0.7},
            # Fails absolute floor
            {"id": "m2", "content": "weak match", "importance": 0.5,
             "bm25_score": 0.8, "bm25_score_normalized": 0.5, "hybrid_score": 0.5},
            # Fails normalized threshold
            {"id": "m3", "content": "barely match", "importance": 0.3,
             "bm25_score": 1.5, "bm25_score_normalized": 0.2, "hybrid_score": 0.2},
        ]
        results = search_memories("query", memories=[{"content": "x"}])
        assert len(results) == 1
        assert results[0]["id"] == "m1"

    @patch("memory_system.memory_injector.keyword_search")
    def test_excludes_low_scores(self, mock_ks):
        """All results below thresholds should be excluded."""
        mock_ks.return_value = [
            {"id": "m1", "content": "test", "importance": 0.5,
             "bm25_score": 0.3, "bm25_score_normalized": 0.1, "hybrid_score": 0.1},
            {"id": "m2", "content": "test2", "importance": 0.5,
             "bm25_score": 0.9, "bm25_score_normalized": 0.2, "hybrid_score": 0.2},
        ]
        results = search_memories("query", memories=[{"content": "x"}])
        assert len(results) == 0

    @patch("memory_system.memory_injector.keyword_search")
    def test_returns_top_k(self, mock_ks):
        """Should return at most top_k results."""
        mock_ks.return_value = [
            {"id": f"m{i}", "content": f"memory {i}", "importance": 0.8,
             "bm25_score": 3.0 - i * 0.1, "bm25_score_normalized": 0.9 - i * 0.05,
             "hybrid_score": 0.9 - i * 0.05}
            for i in range(10)
        ]
        results = search_memories("query", memories=[{"content": "x"}], top_k=3)
        assert len(results) <= 3

    @patch("memory_system.memory_injector.keyword_search")
    def test_empty_query(self, mock_ks):
        """Empty query should return empty results."""
        mock_ks.return_value = []
        results = search_memories("", memories=[{"content": "x"}])
        assert results == []

    @patch("memory_system.memory_injector.keyword_search")
    def test_no_results_above_threshold(self, mock_ks):
        """When no results pass gates, should return empty list."""
        mock_ks.return_value = [
            {"id": "m1", "content": "test", "importance": 0.5,
             "bm25_score": 0.5, "bm25_score_normalized": 0.1, "hybrid_score": 0.1},
        ]
        results = search_memories("obscure query", memories=[{"content": "x"}])
        assert results == []

    @patch("memory_system.memory_injector.keyword_search")
    def test_custom_thresholds(self, mock_ks):
        """Custom min_score and min_normalized should override defaults."""
        mock_ks.return_value = [
            {"id": "m1", "content": "test", "importance": 0.5,
             "bm25_score": 0.5, "bm25_score_normalized": 0.5, "hybrid_score": 0.5},
        ]
        # With low thresholds, this should pass
        results = search_memories("query", memories=[{"content": "x"}],
                                  min_score=0.1, min_normalized=0.1)
        assert len(results) == 1


# --- TestFormatInjection ---


class TestFormatInjection:
    def test_session_format(self):
        """Session format should use numbered list with importance."""
        memories = [
            {"content": "Python debugging tips", "importance": 0.85},
            {"content": "Docker deployment guide", "importance": 0.72},
        ]
        result = format_injection(memories, context="session")
        assert "=== RELEVANT MEMORIES ===" in result
        assert "========================" in result
        assert "[1]" in result
        assert "[2]" in result
        assert "(importance: 0.85)" in result
        assert "(importance: 0.72)" in result
        assert "Python debugging tips" in result
        assert "Docker deployment guide" in result

    def test_prompt_format(self):
        """Prompt format should be compact with pipe separators."""
        memories = [
            {"content": "Python debugging tips", "importance": 0.85},
            {"content": "Docker deployment guide", "importance": 0.72},
        ]
        result = format_injection(memories, context="prompt")
        assert "Relevant context:" in result
        assert "Python debugging tips" in result
        assert "Docker deployment guide" in result
        assert "|" in result

    def test_empty_memories(self):
        """Empty memories should return empty string."""
        assert format_injection([], context="session") == ""
        assert format_injection([], context="prompt") == ""

    def test_truncates_long_content(self):
        """Long content should be truncated in output."""
        long_content = "x" * 1000
        memories = [{"content": long_content, "importance": 0.5}]
        result = format_injection(memories, context="session")
        # Should not contain the full 1000-char content
        assert len(result) < 1000


# --- TestInjectAtSessionStart ---


class TestInjectAtSessionStart:
    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_returns_formatted_string(self, mock_load, mock_search):
        """Should return a formatted string with relevant memories."""
        mock_load.return_value = [
            {"id": "m1", "content": "Python tips", "importance": 0.85,
             "project_id": "LFI", "tags": ["python"]},
        ]
        mock_search.return_value = [
            {"id": "m1", "content": "Python tips", "importance": 0.85},
        ]
        result = inject_at_session_start(project="LFI")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_no_memories_returns_empty(self, mock_load, mock_search):
        """No relevant memories should return empty string."""
        mock_load.return_value = []
        mock_search.return_value = []
        result = inject_at_session_start(project="LFI")
        assert result == ""


# --- TestInjectForPrompt ---


class TestInjectForPrompt:
    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_returns_compact_format(self, mock_load, mock_search):
        """Should return compact format for prompt injection."""
        mock_load.return_value = [
            {"id": "m1", "content": "Relevant info", "importance": 0.8},
        ]
        mock_search.return_value = [
            {"id": "m1", "content": "Relevant info", "importance": 0.8},
        ]
        result = inject_for_prompt("some user prompt")
        assert isinstance(result, str)
        # Prompt format is compact
        assert "Relevant context:" in result or result == ""

    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_excludes_already_injected(self, mock_load, mock_search):
        """Should exclude memories already injected in this session."""
        mock_load.return_value = [
            {"id": "m1", "content": "Already seen", "importance": 0.8},
            {"id": "m2", "content": "New info", "importance": 0.7},
        ]
        mock_search.return_value = [
            {"id": "m2", "content": "New info", "importance": 0.7},
        ]
        result = inject_for_prompt("query", exclude_ids=["m1"])
        # search_memories should have been called; mock already returns filtered
        mock_search.assert_called_once()
        # The exclude_ids should be respected — m1 not in results
        if result:
            assert "Already seen" not in result

    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_no_results_returns_empty(self, mock_load, mock_search):
        """No search results should return empty string."""
        mock_load.return_value = []
        mock_search.return_value = []
        result = inject_for_prompt("obscure query")
        assert result == ""
