"""
Tests for pattern_recall module.

Detects when users hit problems and proactively surfaces past solutions
from memory. Uses BM25-only search to stay within ~50ms hook budget.
"""

import json
from pathlib import Path

import pytest

from memory_system.pattern_recall import (
    PROBLEM_INDICATORS,
    calculate_problem_signal_strength,
    extract_problem_query,
    search_past_solutions,
    format_pattern_recall,
    should_inject_for_problem,
)


# --- Helpers ---


def _make_memory_file(
    directory: Path,
    mem_id: str,
    content: str,
    importance: float = 0.5,
    context_type: str = "knowledge",
    tags: list | None = None,
    project_id: str = "LFI",
) -> Path:
    """Create a mock memory file with YAML frontmatter + markdown body."""
    tags_str = json.dumps(tags or [])
    text = f"""---
id: {mem_id}
created: 1767566679286
importance_weight: {importance}
semantic_tags: {tags_str}
project_id: {project_id}
context_type: {context_type}
status: active
---

{content}"""
    filepath = directory / f"{mem_id}.md"
    filepath.write_text(text, encoding="utf-8")
    return filepath


# ================================================================
# calculate_problem_signal_strength
# ================================================================


class TestCalculateProblemSignalStrength:
    """Tests for multi-signal problem detection scoring."""

    def test_multi_indicator_high_signal(self):
        """Error message + frustration = high signal (>0.5)."""
        prompt = "Error: connection refused and it's not working at all"
        score = calculate_problem_signal_strength(prompt)
        assert score > 0.5

    def test_single_indicator_low_signal(self):
        """Only one indicator type = low signal (<0.3)."""
        prompt = "not working"
        score = calculate_problem_signal_strength(prompt)
        assert score < 0.3

    def test_no_indicators_zero(self):
        """No problem indicators = 0.0."""
        prompt = "Can you refactor the user model to use dataclasses?"
        score = calculate_problem_signal_strength(prompt)
        assert score == 0.0

    def test_meta_reference_implement_error_handling_low(self):
        """CRITICAL: 'implement error handling' is NOT a real error."""
        prompt = "implement error handling for the API endpoints"
        score = calculate_problem_signal_strength(prompt)
        assert score < 0.3

    def test_meta_reference_add_error_messages_low(self):
        """'add error messages to the form' is NOT a real error."""
        prompt = "add error messages to the form validation"
        score = calculate_problem_signal_strength(prompt)
        assert score < 0.3

    def test_actual_error_with_frustration_high(self):
        """Real error + frustration = high signal."""
        prompt = "Error: connection refused — this keeps failing every time"
        score = calculate_problem_signal_strength(prompt)
        assert score > 0.5

    def test_stack_trace_alone_low(self):
        """Stack trace alone = single type = low signal."""
        prompt = 'File "app.py", line 42, in main'
        score = calculate_problem_signal_strength(prompt)
        assert score < 0.3


# ================================================================
# extract_problem_query
# ================================================================


class TestExtractProblemQuery:
    """Tests for search query extraction from problem descriptions."""

    def test_strips_code_blocks(self):
        """Code blocks (```...```) should be removed."""
        prompt = "not working\n```python\nprint('hello')\n```\nstill broken"
        query = extract_problem_query(prompt)
        assert "print" not in query
        assert "hello" not in query

    def test_strips_long_file_paths(self):
        """File paths longer than 50 chars should be stripped."""
        prompt = "Error in /Users/lee/very/long/deeply/nested/path/to/some/file.py — not working"
        query = extract_problem_query(prompt)
        assert "/Users/lee/very/long" not in query

    def test_preserves_problem_description(self):
        """Natural language problem description should remain."""
        prompt = "The database connection keeps timing out when running migrations"
        query = extract_problem_query(prompt)
        assert "database" in query.lower() or "connection" in query.lower()

    def test_limits_to_200_chars(self):
        """Output must not exceed 200 characters."""
        prompt = "not working " * 50  # Very long prompt
        query = extract_problem_query(prompt)
        assert len(query) <= 200

    def test_empty_input_returns_empty(self):
        """Empty or whitespace-only input returns empty string."""
        assert extract_problem_query("") == ""
        assert extract_problem_query("   ") == ""


# ================================================================
# search_past_solutions
# ================================================================


class TestSearchPastSolutions:
    """Tests for memory search targeting past solutions."""

    def test_returns_scored_results(self, tmp_path):
        """Should return results with scores from BM25 search."""
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        _make_memory_file(
            mem_dir, "sol_001",
            "Fixed database connection timeout by increasing pool size to 20",
            context_type="problem_solution",
            tags=["database", "timeout"],
        )
        _make_memory_file(
            mem_dir, "sol_002",
            "Resolved React hydration mismatch by wrapping in useEffect",
            context_type="problem_solution",
            tags=["react", "hydration"],
        )

        results = search_past_solutions("database connection timeout", mem_dir)
        assert len(results) >= 1
        # First result should be the database one
        assert "database" in results[0].get("content", "").lower()

    def test_empty_memory_dir_returns_empty(self, tmp_path):
        """Empty directory should return empty list."""
        mem_dir = tmp_path / "empty_memories"
        mem_dir.mkdir()
        results = search_past_solutions("any query", mem_dir)
        assert results == []

    def test_filters_by_context_type(self, tmp_path):
        """Should prefer problem_solution memories when available."""
        mem_dir = tmp_path / "memories"
        mem_dir.mkdir()
        _make_memory_file(
            mem_dir, "sol_001",
            "Fixed timeout error by increasing pool size",
            context_type="problem_solution",
        )
        _make_memory_file(
            mem_dir, "know_001",
            "Timeout configuration is important for databases",
            context_type="knowledge",
        )

        results = search_past_solutions("timeout error", mem_dir)
        # Should have results — the problem_solution should be findable
        assert len(results) >= 1


# ================================================================
# format_pattern_recall
# ================================================================


class TestFormatPatternRecall:
    """Tests for formatting past solutions for display."""

    def test_correct_header(self):
        """Output should start with the recall header."""
        memories = [{"content": "Fixed the bug by restarting", "hybrid_score": 0.8}]
        output = format_pattern_recall(memories)
        assert "YOU'VE SEEN THIS BEFORE" in output

    def test_truncates_long_content(self):
        """Long content should be truncated."""
        long_content = "x" * 500
        memories = [{"content": long_content, "hybrid_score": 0.8}]
        output = format_pattern_recall(memories)
        assert "..." in output
        # Should not contain the full 500 chars
        assert long_content not in output

    def test_empty_list_returns_empty_string(self):
        """No memories = empty string (no header, nothing)."""
        assert format_pattern_recall([]) == ""


# ================================================================
# should_inject_for_problem
# ================================================================


class TestShouldInjectForProblem:
    """Tests for the injection decision gate."""

    def test_high_signal_cooldown_passed_true(self):
        """High signal + enough exchanges since last recall = True."""
        prompt = "Error: connection refused and it's not working"
        state = {"exchange_count": 15, "last_pattern_recall_exchange": 5}
        assert should_inject_for_problem(prompt, state) is True

    def test_high_signal_cooldown_not_passed_false(self):
        """High signal but within cooldown window = False."""
        prompt = "Error: connection refused and it's not working"
        state = {"exchange_count": 7, "last_pattern_recall_exchange": 5}
        assert should_inject_for_problem(prompt, state) is False

    def test_low_signal_false_regardless(self):
        """Low signal = False even if cooldown is satisfied."""
        prompt = "not working"
        state = {"exchange_count": 100, "last_pattern_recall_exchange": 0}
        assert should_inject_for_problem(prompt, state) is False

    def test_missing_session_state_keys_graceful(self):
        """Missing keys should be handled gracefully (defaults)."""
        prompt = "Error: connection refused and it's not working"
        # Empty dict — should default exchange_count=0, last_pattern_recall_exchange=0
        state = {}
        # With exchange_count=0, cooldown check: 0 - 0 = 0 < 5, so False
        assert should_inject_for_problem(prompt, state) is False

        # Provide exchange_count but missing last_pattern_recall_exchange
        state2 = {"exchange_count": 20}
        # last_pattern_recall_exchange defaults to 0, so 20 - 0 = 20 >= 5 → True
        assert should_inject_for_problem(prompt, state2) is True
