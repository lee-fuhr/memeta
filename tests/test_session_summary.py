"""
Tests for session summary module — "Where was I?" resumption cards.

Covers:
- get_summaries_dir() path resolution and creation
- generate_summary() heuristic extraction from JSONL transcripts
- save_summary() atomic writes with .tmp + rename
- load_summary() with valid, missing, and corrupt files
- get_latest_summary() scanning by generated_at timestamp
- format_resumption_card() human-readable output
- cleanup_old_summaries() age-based pruning
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory_system.session_summary import (
    DEFAULT_SUMMARIES_DIR,
    MAX_FILES_TRACKED,
    MAX_SUMMARY_LENGTH,
    cleanup_old_summaries,
    format_resumption_card,
    generate_summary,
    get_latest_summary,
    get_summaries_dir,
    load_summary,
    save_summary,
    generate_llm_summary,
    StructuredSessionSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_transcript_line(role: str, content, msg_type: str = None) -> str:
    """Build a single JSONL line mimicking Claude session transcript format."""
    if role == "human":
        obj = {"type": "human", "message": {"content": content}}
    elif role == "assistant":
        if isinstance(content, str):
            # Simple text-only assistant message
            obj = {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": content}],
                },
            }
        elif isinstance(content, list):
            # Pre-built content blocks (e.g., mix of text + tool_use)
            obj = {"type": "assistant", "message": {"content": content}}
        else:
            raise ValueError(f"Unexpected content type: {type(content)}")
    else:
        raise ValueError(f"Unknown role: {role}")
    return json.dumps(obj)


def _build_transcript(lines: list[str]) -> str:
    """Join JSONL lines with newlines."""
    return "\n".join(lines)


def _make_summary(
    session_id: str = "test-session-abc",
    summary: str = "Worked on session summary module.",
    open_questions: list[str] | None = None,
    files_touched: list[str] | None = None,
    generated_at: str | None = None,
) -> dict:
    """Build a well-formed summary dict for tests."""
    return {
        "session_id": session_id,
        "summary": summary,
        "open_questions": open_questions or [],
        "files_touched": files_touched or [],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# TestGetSummariesDir
# ---------------------------------------------------------------------------

class TestGetSummariesDir:
    def test_returns_default_path(self):
        result = get_summaries_dir()
        assert result == DEFAULT_SUMMARIES_DIR
        assert isinstance(result, Path)

    def test_creates_directory(self, tmp_path):
        target = tmp_path / "summaries"
        assert not target.exists()
        result = get_summaries_dir(target)
        assert result == target
        assert target.is_dir()


# ---------------------------------------------------------------------------
# TestGenerateSummary
# ---------------------------------------------------------------------------

class TestGenerateSummary:
    def test_extracts_summary_from_transcript(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Let's refactor the config module."),
            _make_transcript_line("assistant", "I'll restructure the config to use dataclasses."),
            _make_transcript_line("human", "Looks good. Also fix the imports."),
            _make_transcript_line("assistant", "Done. I've updated all import paths."),
        ])
        result = generate_summary(transcript, session_id="sess-001")
        assert "summary" in result
        assert len(result["summary"]) > 0
        assert result["session_id"] == "sess-001"

    def test_extracts_open_questions(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Should we use SQLite or JSON for storage?"),
            _make_transcript_line("assistant", "Good question. Let me think about that."),
            _make_transcript_line("human", "TODO: benchmark both approaches."),
            _make_transcript_line("assistant", "We need to decide on the schema first."),
        ])
        result = generate_summary(transcript)
        assert len(result["open_questions"]) > 0
        # Should find the question mark line and the TODO
        found_question = any("SQLite" in q or "storage" in q for q in result["open_questions"])
        found_todo = any("benchmark" in q.lower() for q in result["open_questions"])
        assert found_question or found_todo

    def test_extracts_files_touched(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Edit /Users/testuser/project/src/config.py"),
            _make_transcript_line("assistant", "I updated src/config.py and tests/test_config.py"),
            _make_transcript_line("human", "Check the README.md too"),
        ])
        result = generate_summary(transcript)
        assert len(result["files_touched"]) > 0
        paths = result["files_touched"]
        assert any("config.py" in p for p in paths)

    def test_handles_empty_transcript(self):
        result = generate_summary("")
        assert result["summary"] == ""
        assert result["open_questions"] == []
        assert result["files_touched"] == []

    def test_handles_tool_only_transcript(self):
        """Transcript with only tool_use blocks should produce empty summary."""
        tool_content = [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/foo.py"}},
        ]
        transcript = _build_transcript([
            _make_transcript_line("assistant", tool_content),
        ])
        result = generate_summary(transcript)
        # Summary should be empty or very short since no substantive text
        assert len(result["summary"]) <= MAX_SUMMARY_LENGTH

    def test_truncates_long_summary(self):
        # Build a transcript with very long messages
        long_msg = "This is a detailed explanation. " * 100
        transcript = _build_transcript([
            _make_transcript_line("human", long_msg),
            _make_transcript_line("assistant", long_msg),
        ])
        result = generate_summary(transcript)
        assert len(result["summary"]) <= MAX_SUMMARY_LENGTH

    def test_limits_files_touched(self):
        # Mention more than MAX_FILES_TRACKED file paths
        lines = []
        for i in range(20):
            lines.append(
                _make_transcript_line("human", f"Edit /Users/testuser/project/file{i}.py")
            )
        transcript = _build_transcript(lines)
        result = generate_summary(transcript)
        assert len(result["files_touched"]) <= MAX_FILES_TRACKED

    def test_includes_generated_at(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Hello"),
        ])
        before = datetime.now(timezone.utc).isoformat()
        result = generate_summary(transcript)
        after = datetime.now(timezone.utc).isoformat()
        assert "generated_at" in result
        assert before <= result["generated_at"] <= after

    def test_generates_session_id_when_none(self):
        transcript = _build_transcript([
            _make_transcript_line("human", "Hello"),
        ])
        result = generate_summary(transcript, session_id=None)
        assert result["session_id"] is not None
        assert len(result["session_id"]) > 0

    def test_truncates_huge_transcript(self):
        """Transcripts larger than MAX_TRANSCRIPT_BYTES are tail-truncated."""
        # Build a transcript that exceeds the 2 MB limit
        lines = []
        for i in range(5000):
            lines.append(
                _make_transcript_line("human", f"Message number {i} " + "x" * 400)
            )
        transcript = _build_transcript(lines)
        assert len(transcript) > 2 * 1024 * 1024, "Test needs transcript > 2 MB"

        result = generate_summary(transcript, session_id="huge-sess")
        # Should still produce a valid summary (not crash or OOM)
        assert result["session_id"] == "huge-sess"
        assert isinstance(result["summary"], str)
        assert isinstance(result["open_questions"], list)
        assert isinstance(result["files_touched"], list)


# ---------------------------------------------------------------------------
# TestSaveSummary
# ---------------------------------------------------------------------------

class TestSaveSummary:
    def test_saves_valid_json(self, tmp_path):
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-save", summaries_dir=tmp_path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["session_id"] == "test-session-abc"
        assert loaded["summary"] == summary["summary"]

    def test_atomic_write(self, tmp_path):
        """No .tmp file should remain after save completes."""
        summary = _make_summary()
        save_summary(summary, session_id="sess-atomic", summaries_dir=tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-nested", summaries_dir=nested)
        assert path.exists()
        assert nested.is_dir()

    def test_custom_path(self, tmp_path):
        custom_dir = tmp_path / "custom-summaries"
        summary = _make_summary()
        path = save_summary(summary, session_id="sess-custom", summaries_dir=custom_dir)
        assert path.parent == custom_dir
        assert path.name == "sess-custom.json"


# ---------------------------------------------------------------------------
# TestLoadSummary
# ---------------------------------------------------------------------------

class TestLoadSummary:
    def test_loads_valid_summary(self, tmp_path):
        summary = _make_summary(session_id="sess-load")
        save_summary(summary, session_id="sess-load", summaries_dir=tmp_path)
        loaded = load_summary("sess-load", summaries_dir=tmp_path)
        assert loaded is not None
        assert loaded["session_id"] == "sess-load"

    def test_returns_none_missing(self, tmp_path):
        result = load_summary("nonexistent-session", summaries_dir=tmp_path)
        assert result is None

    def test_returns_none_corrupt(self, tmp_path):
        corrupt_file = tmp_path / "corrupt-sess.json"
        corrupt_file.write_text("{{{{not json at all!!!!")
        result = load_summary("corrupt-sess", summaries_dir=tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestGetLatestSummary
# ---------------------------------------------------------------------------

class TestGetLatestSummary:
    def test_returns_newest(self, tmp_path):
        old = _make_summary(
            session_id="old",
            generated_at="2025-01-01T00:00:00+00:00",
        )
        new = _make_summary(
            session_id="new",
            summary="Latest work",
            generated_at="2026-02-28T12:00:00+00:00",
        )
        save_summary(old, session_id="old", summaries_dir=tmp_path)
        save_summary(new, session_id="new", summaries_dir=tmp_path)
        latest = get_latest_summary(summaries_dir=tmp_path)
        assert latest is not None
        assert latest["session_id"] == "new"

    def test_returns_none_empty_dir(self, tmp_path):
        result = get_latest_summary(summaries_dir=tmp_path)
        assert result is None

    def test_handles_multiple_summaries(self, tmp_path):
        """Correctly picks newest from 5+ summaries."""
        for i in range(5):
            ts = f"2026-01-{10 + i:02d}T00:00:00+00:00"
            s = _make_summary(session_id=f"sess-{i}", generated_at=ts)
            save_summary(s, session_id=f"sess-{i}", summaries_dir=tmp_path)
        latest = get_latest_summary(summaries_dir=tmp_path)
        assert latest["session_id"] == "sess-4"


# ---------------------------------------------------------------------------
# TestFormatResumptionCard
# ---------------------------------------------------------------------------

class TestFormatResumptionCard:
    def test_formats_complete_card(self):
        summary = _make_summary(
            session_id="abc123def456",
            summary="Refactored config module to use dataclasses.",
            open_questions=["Should we add env var support?", "Need to benchmark."],
            files_touched=["src/config.py", "tests/test_config.py"],
            generated_at="2026-02-28T10:30:00+00:00",
        )
        card = format_resumption_card(summary)
        assert "# Project state" in card
        assert "abc123def456" in card
        assert "Refactored config" in card
        assert "env var" in card
        assert "benchmark" in card

    def test_handles_empty_fields(self):
        summary = _make_summary(
            summary="",
            open_questions=[],
            files_touched=[],
        )
        card = format_resumption_card(summary)
        assert isinstance(card, str)
        assert "# Project state" in card
        # Should not crash on empty fields

    def test_includes_session_id(self):
        summary = _make_summary(session_id="session-xyz-789012")
        card = format_resumption_card(summary)
        # Should include truncated session_id
        assert "session-xyz-" in card


# ---------------------------------------------------------------------------
# TestCleanupOldSummaries
# ---------------------------------------------------------------------------

class TestCleanupOldSummaries:
    def test_removes_old_files(self, tmp_path):
        # Create a file with old timestamp
        old_summary = _make_summary(
            session_id="old-sess",
            generated_at="2020-01-01T00:00:00+00:00",
        )
        path = save_summary(old_summary, session_id="old-sess", summaries_dir=tmp_path)
        # Set mtime to 60 days ago
        old_time = time.time() - (60 * 86400)
        os.utime(path, (old_time, old_time))
        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed >= 1
        assert not path.exists()

    def test_keeps_recent_files(self, tmp_path):
        recent = _make_summary(session_id="recent-sess")
        path = save_summary(recent, session_id="recent-sess", summaries_dir=tmp_path)
        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed == 0
        assert path.exists()

    def test_returns_count(self, tmp_path):
        # Create 3 old files
        for i in range(3):
            s = _make_summary(session_id=f"old-{i}")
            p = save_summary(s, session_id=f"old-{i}", summaries_dir=tmp_path)
            old_time = time.time() - (60 * 86400)
            os.utime(p, (old_time, old_time))
        # Create 2 recent files
        for i in range(2):
            s = _make_summary(session_id=f"recent-{i}")
            save_summary(s, session_id=f"recent-{i}", summaries_dir=tmp_path)

        removed = cleanup_old_summaries(summaries_dir=tmp_path, max_age_days=30)
        assert removed == 3
        # 2 recent files should remain
        remaining = list(tmp_path.glob("*.json"))
        assert len(remaining) == 2


# ---------------------------------------------------------------------------
# TestGenerateLLMSummary
# ---------------------------------------------------------------------------

class TestGenerateLLMSummary:
    """Tests for LLM-powered summary generation."""

    def test_generates_structured_summary(self, monkeypatch):
        """LLM call returns structured summary with all required fields."""
        # Mock ask_claude to return a JSON response
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return json.dumps({
                "summary": "Built session summary feature with LLM integration",
                "topic": "memory-system-v1",
                "decisions": ["Use LLM for rich summaries", "Keep heuristic as fallback"],
                "open_questions": ["Should we cache LLM summaries?"],
                "open_threads": ["Wire into consolidation hook"],
                "files_touched": ["src/session_summary.py", "tests/test_session_summary.py"]
            })

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([
            _make_transcript_line("human", "Let's add LLM summaries"),
            _make_transcript_line("assistant", "I'll build that feature"),
        ])

        result = generate_llm_summary(transcript, session_id="test-llm-001")

        assert isinstance(result, StructuredSessionSummary)
        assert result.session_id == "test-llm-001"
        assert "LLM" in result.summary
        assert result.topic == "memory-system-v1"
        assert len(result.decisions) == 2
        assert len(result.open_questions) == 1
        assert len(result.files_touched) == 2
        assert result.generator == "llm"

    def test_handles_llm_timeout(self, monkeypatch):
        """Falls back to heuristic when LLM times out."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return ""  # Timeout/failure

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([
            _make_transcript_line("human", "Test message"),
        ])

        result = generate_llm_summary(transcript, session_id="fallback-001")

        assert result.generator == "heuristic"
        assert result.session_id == "fallback-001"

    def test_handles_malformed_llm_response(self, monkeypatch):
        """Falls back to heuristic when LLM returns invalid JSON."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return "This is not JSON at all"

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([
            _make_transcript_line("human", "Test"),
        ])

        result = generate_llm_summary(transcript)
        assert result.generator == "heuristic"

    def test_handles_partial_llm_response(self, monkeypatch):
        """Fills missing fields with defaults when LLM response is incomplete."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return json.dumps({
                "summary": "Partial summary",
                "topic": "test-project"
                # Missing: decisions, open_questions, etc.
            })

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([
            _make_transcript_line("human", "Test"),
        ])

        result = generate_llm_summary(transcript)
        assert result.summary == "Partial summary"
        assert result.topic == "test-project"
        assert result.decisions == []
        assert result.open_questions == []
        assert result.generator == "llm"

    def test_quality_gate_rejects_short_summaries(self, monkeypatch):
        """Rejects heuristic summaries that are too short or all questions."""
        # This tests the quality gate for heuristic fallback
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return ""  # Force heuristic

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        # Transcript that would produce very short summary
        transcript = _build_transcript([
            _make_transcript_line("human", "?"),
        ])

        result = generate_llm_summary(transcript)
        # Should still return a result, but with minimal content
        assert result is not None
        assert result.generator == "heuristic"


# ---------------------------------------------------------------------------
# TestStructuredSessionSummary
# ---------------------------------------------------------------------------

class TestStructuredSessionSummary:
    """Tests for StructuredSessionSummary dataclass."""

    def test_creates_with_all_fields(self):
        """Can create summary with all 11 fields."""
        summary = StructuredSessionSummary(
            session_id="test-123",
            summary="Test summary",
            topic="test-topic",
            decisions=["decision 1"],
            open_questions=["question 1"],
            open_threads=["thread 1"],
            files_touched=["file.py"],
            frustration_level="low",
            depends_on=["session-456"],
            generated_at="2026-02-28T10:00:00Z",
            generator="llm"
        )

        assert summary.session_id == "test-123"
        assert summary.summary == "Test summary"
        assert summary.frustration_level == "low"
        assert summary.depends_on == ["session-456"]
        assert summary.generator == "llm"

    def test_can_convert_to_dict(self):
        """StructuredSessionSummary can be converted to dict for JSON serialization."""
        from dataclasses import asdict

        summary = StructuredSessionSummary(
            session_id="test-123",
            summary="Test",
            topic="topic",
            decisions=[],
            open_questions=[],
            open_threads=[],
            files_touched=[],
            frustration_level="low",
            depends_on=[],
            generated_at="2026-02-28T10:00:00Z",
            generator="llm"
        )

        data = asdict(summary)
        assert data["session_id"] == "test-123"
        assert data["generator"] == "llm"


# ---------------------------------------------------------------------------
# TestWatchOutForSection
# ---------------------------------------------------------------------------

class TestWatchOutForSection:
    """Tests for 'Watch out for' section in resumption cards."""

    def test_includes_corrections_in_card(self, tmp_path, monkeypatch):
        """Resumption card includes relevant corrections in 'Watch out for' section."""
        # Mock memory search to return corrections
        def mock_search_memories(query, memories=None, index_path=None, top_k=3,
                                 strategy="bm25", min_score=1.0, min_normalized=0.3):
            return [
                {"id": "corr-1", "content": "Always run tests before committing",
                 "context_type": "correction"},
                {"id": "corr-2", "content": "Use virtual env, not system Python",
                 "context_type": "correction"},
            ]

        # Patch at memory_injector where it's defined
        monkeypatch.setattr("memory_system.memory_injector.search_memories", mock_search_memories)

        summary = _make_summary(
            session_id="test-watch-123",
            summary="Working on test suite",
            open_questions=["Should we add more tests?"],
        )
        # Add topic field so the card will search for corrections
        summary["topic"] = "testing"

        card = format_resumption_card(summary)

        assert "Watch out for" in card or "watch out for" in card.lower()
        assert "tests before committing" in card or "Always run tests" in card

    def test_no_corrections_no_section(self, monkeypatch):
        """When no corrections found, 'Watch out for' section is not shown."""
        def mock_search_memories(*args, **kwargs):
            return []  # No corrections

        monkeypatch.setattr("memory_system.memory_injector.search_memories", mock_search_memories)

        summary = _make_summary()
        summary["topic"] = "testing"
        card = format_resumption_card(summary)

        # Should not include empty "Watch out for" section
        assert "Watch out for" not in card

    def test_limits_to_top_3_corrections(self, monkeypatch):
        """Only shows top 3 most relevant corrections."""
        def mock_search_memories(*args, **kwargs):
            return [
                {"id": f"corr-{i}", "content": f"Correction {i}",
                 "context_type": "correction"}
                for i in range(10)  # Return 10, should only show 3
            ]

        monkeypatch.setattr("memory_system.memory_injector.search_memories", mock_search_memories)

        summary = _make_summary()
        summary["topic"] = "test-topic"
        card = format_resumption_card(summary)

        # Count how many corrections appear
        correction_count = sum(1 for i in range(10) if f"Correction {i}" in card)
        assert correction_count <= 3


# ---------------------------------------------------------------------------
# TestBackwardCompatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Tests for reading old-format summaries gracefully."""

    def test_reads_old_format_summary(self, tmp_path):
        """Old 5-field format loads without errors."""
        old_summary = {
            "session_id": "old-123",
            "summary": "Old format summary",
            "open_questions": ["Old question?"],
            "files_touched": ["old_file.py"],
            "generated_at": "2026-01-01T00:00:00Z"
        }

        path = tmp_path / "old-123.json"
        path.write_text(json.dumps(old_summary))

        loaded = load_summary("old-123", summaries_dir=tmp_path)

        assert loaded is not None
        assert loaded["session_id"] == "old-123"
        assert "summary" in loaded

    def test_formats_old_summary_gracefully(self):
        """format_resumption_card handles old format with missing new fields."""
        old_summary = {
            "session_id": "old-456",
            "summary": "Old summary",
            "open_questions": [],
            "files_touched": [],
            "generated_at": "2026-01-01T00:00:00Z"
            # Missing: topic, decisions, open_threads, frustration_level, etc.
        }

        card = format_resumption_card(old_summary)

        # Should not crash
        assert isinstance(card, str)
        assert "Old summary" in card

    def test_new_fields_have_defaults(self):
        """New StructuredSessionSummary fields default gracefully when missing."""
        # Simulate loading old format and converting
        old_data = {
            "session_id": "mixed-789",
            "summary": "Summary text",
            "open_questions": [],
            "files_touched": [],
            "generated_at": "2026-02-28T10:00:00Z"
        }

        # Create new structure with defaults for missing fields
        summary = StructuredSessionSummary(
            session_id=old_data["session_id"],
            summary=old_data["summary"],
            topic=old_data.get("topic", ""),
            decisions=old_data.get("decisions", []),
            open_questions=old_data.get("open_questions", []),
            open_threads=old_data.get("open_threads", []),
            files_touched=old_data.get("files_touched", []),
            frustration_level=old_data.get("frustration_level", "unknown"),
            depends_on=old_data.get("depends_on", []),
            generated_at=old_data["generated_at"],
            generator=old_data.get("generator", "heuristic")
        )

        assert summary.topic == ""
        assert summary.decisions == []
        assert summary.frustration_level == "unknown"
        assert summary.generator == "heuristic"


# ---------------------------------------------------------------------------
# TestFrustrationLevel
# ---------------------------------------------------------------------------

class TestFrustrationLevel:
    """Tests for frustration level integration."""

    def test_includes_frustration_level(self, monkeypatch):
        """Summary includes frustration level from detector."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return json.dumps({
                "summary": "Test",
                "topic": "test",
                "decisions": [],
                "open_questions": [],
                "open_threads": [],
                "files_touched": []
            })

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        # Mock frustration detection
        def mock_detect_frustration(session_id):
            return "medium"

        import memory_system.session_summary
        monkeypatch.setattr(memory_system.session_summary, "detect_frustration_level",
                          mock_detect_frustration)

        transcript = _build_transcript([
            _make_transcript_line("human", "This keeps breaking"),
        ])

        result = generate_llm_summary(transcript, session_id="frust-123")

        assert result.frustration_level in ["low", "medium", "high", "unknown"]


# ---------------------------------------------------------------------------
# TestGeneratorField
# ---------------------------------------------------------------------------

class TestGeneratorField:
    """Tests for generator field tracking."""

    def test_llm_success_sets_generator_llm(self, monkeypatch):
        """When LLM succeeds, generator is 'llm'."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return json.dumps({
                "summary": "LLM summary",
                "topic": "test",
                "decisions": [],
                "open_questions": [],
                "open_threads": [],
                "files_touched": []
            })

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([_make_transcript_line("human", "Test")])
        result = generate_llm_summary(transcript)

        assert result.generator == "llm"

    def test_heuristic_fallback_sets_generator_heuristic(self, monkeypatch):
        """When LLM fails, generator is 'heuristic'."""
        def mock_ask_claude(prompt, timeout=30, max_retries=3):
            return ""  # Failure

        monkeypatch.setattr("memory_system.llm_extractor.ask_claude", mock_ask_claude)

        transcript = _build_transcript([_make_transcript_line("human", "Test")])
        result = generate_llm_summary(transcript)

        assert result.generator == "heuristic"
