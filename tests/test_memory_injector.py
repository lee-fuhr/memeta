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
    _format_corrections,
    DEFAULT_INDEX_PATH,
    DEFAULT_MEMORY_DIR,
    BM25_FLOOR,
    NORMALIZED_THRESHOLD,
    DEFAULT_TOP_K,
)


# --- Fixtures ---


def _make_memory_file(directory: Path, mem_id: str, content: str,
                      importance: float = 0.5, tags: list = None,
                      project_id: str = "test-project", extra_fields: str = "") -> Path:
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
             "project_id": "test-project", "tags": ["python"]},
        ]
        mock_search.return_value = [
            {"id": "m1", "content": "Python tips", "importance": 0.85},
        ]
        result = inject_at_session_start(project="test-project")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_no_memories_returns_empty(self, mock_load, mock_search):
        """No relevant memories should return empty string."""
        mock_load.return_value = []
        mock_search.return_value = []
        result = inject_at_session_start(project="test-project")
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


# --- TestFormatCorrections ---


class TestFormatCorrections:
    def test_format_corrections_block(self):
        """_format_corrections returns properly formatted block with markers."""
        corrections = [
            {"content": "Use sentence case for all headings", "importance": 0.9},
            {"content": "Never use title case in file names", "importance": 0.8},
        ]
        result = _format_corrections(corrections)
        assert "=== ACTIVE CORRECTIONS ===" in result
        assert "===========================" in result
        assert "[1]" in result
        assert "[2]" in result
        assert "Use sentence case for all headings" in result
        assert "Never use title case in file names" in result

    def test_format_corrections_empty(self):
        """_format_corrections([]) returns empty string."""
        result = _format_corrections([])
        assert result == ""

    def test_format_corrections_strips_prefix(self):
        """'Correction: use sentence case.' should strip prefix and capitalize."""
        corrections = [
            {"content": "Correction: use sentence case always.", "importance": 0.9},
        ]
        result = _format_corrections(corrections)
        assert "Correction: " not in result
        # The content after stripping should be present
        assert "use sentence case always." in result


# --- TestBuildSearchIndexContextType ---


class TestBuildSearchIndexContextType:
    def test_build_search_index_includes_context_type(self, tmp_path):
        """build_search_index includes context_type field in index entries."""
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        index_out = tmp_path / "index.json"

        # Create a correction memory with context_type
        _make_memory_file(
            mem_dir, "corr_001",
            "Correction: use sentence case for headings",
            importance=0.9,
            extra_fields="context_type: correction\n",
        )
        # Create a regular memory without context_type
        _make_memory_file(
            mem_dir, "mem_001",
            "Python debugging tips",
            importance=0.8,
        )

        build_search_index(memory_dir=mem_dir, output_path=index_out)
        data = json.loads(index_out.read_text())

        corr = next(m for m in data if m["id"] == "corr_001")
        reg = next(m for m in data if m["id"] == "mem_001")

        assert corr["context_type"] == "correction"
        assert reg["context_type"] == "knowledge"  # default


# --- TestInjectAtSessionStartCorrections ---


class TestInjectAtSessionStartCorrections:
    def _build_index_with_corrections(self, tmp_path, memories):
        """Helper to build an index from a list of memory dicts."""
        index_path = tmp_path / "index.json"
        index_path.write_text(json.dumps(memories, ensure_ascii=False))
        return index_path

    def test_inject_at_session_start_corrections_first(self, tmp_path):
        """Corrections block appears before regular memories block."""
        memories = [
            {"id": "corr_1", "content": "Correction: use sentence case",
             "importance": 0.95, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
            {"id": "mem_1", "content": "Python debugging tips are essential",
             "importance": 0.85, "tags": ["python"], "project_id": "test-project",
             "context_type": "knowledge"},
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        # Both blocks should be present
        assert "=== ACTIVE CORRECTIONS ===" in result
        assert "=== RELEVANT MEMORIES ===" in result

        # Corrections block should come first
        corr_pos = result.index("=== ACTIVE CORRECTIONS ===")
        mem_pos = result.index("=== RELEVANT MEMORIES ===")
        assert corr_pos < mem_pos

    def test_inject_at_session_start_no_corrections(self, tmp_path):
        """No correction memories means no corrections block, regular block still works."""
        memories = [
            {"id": "mem_1", "content": "Python debugging tips are essential",
             "importance": 0.85, "tags": ["python"], "project_id": "test-project",
             "context_type": "knowledge"},
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        assert "=== ACTIVE CORRECTIONS ===" not in result
        # Regular block should still work (may or may not appear depending on search)
        # At minimum, should not crash

    def test_inject_at_session_start_corrections_only(self, tmp_path):
        """If only corrections exist, still get output."""
        memories = [
            {"id": "corr_1", "content": "Correction: always use sentence case",
             "importance": 0.95, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
            {"id": "corr_2", "content": "Correction: no title case in headings",
             "importance": 0.90, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        assert "=== ACTIVE CORRECTIONS ===" in result
        assert len(result) > 0

    def test_inject_at_session_start_corrections_sorted_by_importance(self, tmp_path):
        """Higher importance corrections appear first."""
        memories = [
            {"id": "corr_low", "content": "Low priority correction",
             "importance": 0.5, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
            {"id": "corr_high", "content": "High priority correction",
             "importance": 0.99, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
            {"id": "corr_mid", "content": "Medium priority correction",
             "importance": 0.75, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        assert "=== ACTIVE CORRECTIONS ===" in result
        # High should come before medium, medium before low
        high_pos = result.index("High priority correction")
        mid_pos = result.index("Medium priority correction")
        low_pos = result.index("Low priority correction")
        assert high_pos < mid_pos < low_pos

    def test_inject_at_session_start_max_3_corrections(self, tmp_path):
        """At most 3 corrections shown even if more exist."""
        memories = [
            {"id": f"corr_{i}", "content": f"Correction number {i}",
             "importance": 0.9 - i * 0.01, "tags": [], "project_id": "test-project",
             "context_type": "correction"}
            for i in range(5)
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        assert "=== ACTIVE CORRECTIONS ===" in result
        # Count numbered entries in the corrections block
        # Extract just the corrections block
        corr_start = result.index("=== ACTIVE CORRECTIONS ===")
        corr_end = result.index("===========================", corr_start)
        corr_block = result[corr_start:corr_end]
        assert "[1]" in corr_block
        assert "[2]" in corr_block
        assert "[3]" in corr_block
        assert "[4]" not in corr_block
        assert "[5]" not in corr_block

    def test_inject_at_session_start_corrections_filtered_by_project(self, tmp_path):
        """Corrections filtered to project when specified."""
        memories = [
            {"id": "corr_test", "content": "Project-specific correction",
             "importance": 0.95, "tags": [], "project_id": "test-project",
             "context_type": "correction"},
            {"id": "corr_other", "content": "Other project correction",
             "importance": 0.95, "tags": [], "project_id": "OtherProject",
             "context_type": "correction"},
            {"id": "mem_1", "content": "Python debugging tips are essential",
             "importance": 0.85, "tags": ["python"], "project_id": "test-project",
             "context_type": "knowledge"},
        ]
        index_path = self._build_index_with_corrections(tmp_path, memories)
        result = inject_at_session_start(project="test-project", index_path=index_path)

        # Project correction should appear
        assert "Project-specific correction" in result
        # Other project correction should NOT appear
        assert "Other project correction" not in result


# --- TestInjectForPromptUnchanged ---


class TestInjectForPromptUnchanged:
    @patch("memory_system.memory_injector.search_memories")
    @patch("memory_system.memory_injector.load_search_index")
    def test_inject_for_prompt_unchanged(self, mock_load, mock_search):
        """inject_for_prompt should NOT include corrections block."""
        mock_load.return_value = [
            {"id": "corr_1", "content": "Correction: use sentence case",
             "importance": 0.95, "project_id": "test-project",
             "context_type": "correction"},
            {"id": "mem_1", "content": "Relevant info here",
             "importance": 0.8, "project_id": "test-project",
             "context_type": "knowledge"},
        ]
        mock_search.return_value = [
            {"id": "mem_1", "content": "Relevant info here",
             "importance": 0.8},
        ]
        result = inject_for_prompt("some user prompt")
        # Should NOT contain corrections block markers
        assert "=== ACTIVE CORRECTIONS ===" not in result
        # Should still have regular prompt format
        assert "Relevant context:" in result
