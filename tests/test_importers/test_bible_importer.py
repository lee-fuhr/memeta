"""Tests for BibleImporter — Build Bible → Memeta memory import."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from memory_system.importers.bible_importer import BibleImporter
from memory_system.importers.base import ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def importer(tmp_path):
    """BibleImporter with a mocked memory client."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    imp = BibleImporter(memory_dir=mem_dir, project_id="test-project")
    mock_client = MagicMock()
    mock_client.list.return_value = []
    mock_client.create.side_effect = lambda **kwargs: Memory(
        id=f"mem-{kwargs.get('content', '')[:8].replace(' ', '-')}",
        content=kwargs.get("content", ""),
        importance=kwargs.get("importance", 0.90),
        tags=kwargs.get("tags", []),
        project_id="test-project",
        context_type=kwargs.get("context_type", "principle"),
    )
    imp._client = mock_client
    return imp


SAMPLE_BIBLE = """\
# How we build
**Version:** 1.5.1

---

## 1. Core principles

### 1.1 Orchestrate, don't execute

The primary directive is orchestration, not solo execution.
Delegate to specialist agents. Target 80% delegation rate.

### 1.2 QA the design before writing code

Review the design before any implementation. Steelman every plan.
Use QA swarm for builds over 2 hours.

---

## 2. Reusable patterns

### 2.1 Hierarchical cost optimization (80/15/5)

Route work to the cheapest model that can handle it.
Haiku for routine tasks, Sonnet for synthesis, Opus for architecture.

### 2.2 Config-driven scaling

Scale with data files, not code changes.
One config key change should drive behavior across the system.

---

## 6. Anti-patterns

### 6.1 The 49-day research agent

An automation that runs without checkpoint validation will run
indefinitely. Always set measurable checkpoints with explicit failure plans.

### 6.2 The premature learning engine

Building ML/scoring infrastructure before you have data.
Minimum 100 data points before scoring; 1,000 before tuning.

---

## 7. Operations reference

### 7.1 Scripts and services

This section is operational reference and should not be imported.
"""


@pytest.fixture
def bible_file(tmp_path):
    """Write SAMPLE_BIBLE to a temp file."""
    path = tmp_path / "Build Bible.md"
    path.write_text(SAMPLE_BIBLE)
    return path


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

class TestBibleSectionParsing:
    def test_detects_principle_sections(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        principles = [s for s in sections if s["section_type"] == "principle"]
        assert len(principles) == 2

    def test_detects_pattern_sections(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        patterns = [s for s in sections if s["section_type"] == "pattern"]
        assert len(patterns) == 2

    def test_detects_anti_pattern_sections(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        anti = [s for s in sections if s["section_type"] == "anti_pattern"]
        assert len(anti) == 2

    def test_skips_unknown_sections(self, importer):
        """Section 7 (operations reference) should not appear."""
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        types = {s["section_type"] for s in sections}
        assert None not in types
        headings = [s["heading"] for s in sections]
        assert not any("7.1" in h for h in headings)

    def test_extracts_section_ids(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        ids = {s["section_id"] for s in sections}
        assert "1.1" in ids
        assert "1.2" in ids
        assert "2.1" in ids
        assert "6.1" in ids

    def test_section_content_is_non_empty(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        for s in sections:
            assert s["content"].strip(), f"Empty content for {s['section_id']}"

    def test_heading_preserved(self, importer):
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        headings = [s["heading"] for s in sections]
        assert any("Orchestrate" in h for h in headings)
        assert any("49-day" in h for h in headings)


# ---------------------------------------------------------------------------
# Section type detection
# ---------------------------------------------------------------------------

class TestDetectSectionType:
    def test_principle_prefix_1x(self, importer):
        assert importer._detect_section_type("1.1 Orchestrate, don't execute") == "principle"

    def test_principle_multi_digit(self, importer):
        assert importer._detect_section_type("1.14 Speed hides debt") == "principle"

    def test_pattern_prefix_2x(self, importer):
        assert importer._detect_section_type("2.3 Progressive disclosure") == "pattern"

    def test_anti_pattern_prefix_6x(self, importer):
        assert importer._detect_section_type("6.1 The 49-day research agent") == "anti_pattern"

    def test_unknown_section_returns_none(self, importer):
        assert importer._detect_section_type("7.1 Scripts and services") is None

    def test_non_numbered_returns_none(self, importer):
        assert importer._detect_section_type("Table of contents") is None


# ---------------------------------------------------------------------------
# Import creates correct memory fields
# ---------------------------------------------------------------------------

class TestBibleImport:
    def test_import_creates_memories_for_known_sections(self, importer, bible_file):
        result = importer.import_source(bible_file)
        assert result.imported == 6  # 2 principles + 2 patterns + 2 anti-patterns

    def test_principles_get_high_importance(self, importer, bible_file):
        importer.import_source(bible_file)
        calls = importer._client.create.call_args_list
        principle_calls = [c for c in calls if c.kwargs.get("context_type") == "principle"]
        for call in principle_calls:
            assert call.kwargs["importance"] == 0.90

    def test_anti_patterns_get_high_importance(self, importer, bible_file):
        importer.import_source(bible_file)
        calls = importer._client.create.call_args_list
        anti_calls = [c for c in calls if c.kwargs.get("context_type") == "anti_pattern"]
        for call in anti_calls:
            assert call.kwargs["importance"] == 0.90

    def test_patterns_get_medium_importance(self, importer, bible_file):
        importer.import_source(bible_file)
        calls = importer._client.create.call_args_list
        pattern_calls = [c for c in calls if c.kwargs.get("context_type") == "pattern"]
        for call in pattern_calls:
            assert call.kwargs["importance"] == 0.85

    def test_source_bible_tag_always_present(self, importer, bible_file):
        importer.import_source(bible_file)
        for call in importer._client.create.call_args_list:
            assert "#source:bible" in call.kwargs["tags"]

    def test_section_id_tag_present(self, importer, bible_file):
        importer.import_source(bible_file)
        all_tags = [tag for call in importer._client.create.call_args_list
                    for tag in call.kwargs["tags"]]
        assert any(t.startswith("#section:") for t in all_tags)
        assert "#section:1.1" in all_tags

    def test_type_tag_present(self, importer, bible_file):
        importer.import_source(bible_file)
        all_tags = [tag for call in importer._client.create.call_args_list
                    for tag in call.kwargs["tags"]]
        assert "#type:principle" in all_tags
        assert "#type:anti_pattern" in all_tags

    def test_returns_import_result(self, importer, bible_file):
        result = importer.import_source(bible_file)
        assert isinstance(result, ImportResult)
        assert result.imported > 0
        assert result.skipped >= 0

    def test_errors_collected_not_raised(self, importer, bible_file):
        importer._client.create.side_effect = RuntimeError("db error")
        result = importer.import_source(bible_file)
        assert result.imported == 0
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestBibleDryRun:
    def test_dry_run_returns_preview(self, importer, bible_file):
        preview = importer.dry_run(bible_file)
        assert isinstance(preview, ImportPreview)

    def test_dry_run_does_not_write(self, importer, bible_file):
        importer.dry_run(bible_file)
        importer._client.create.assert_not_called()

    def test_dry_run_counts_match_import(self, importer, bible_file):
        preview = importer.dry_run(bible_file)
        # Reset mock for actual import
        importer._client.list.return_value = []
        importer._client.create.side_effect = lambda **kwargs: Memory(
            id="x", content=kwargs.get("content", ""), importance=0.9, tags=[], project_id="t"
        )
        result = importer.import_source(bible_file)
        assert preview.would_import == result.imported


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestBibleDedup:
    def test_duplicate_content_is_skipped(self, importer, bible_file):
        import hashlib
        # Pre-populate with hash of first principle content
        sections = importer._parse_bible_sections(SAMPLE_BIBLE)
        first = sections[0]["content"]
        existing_hash = hashlib.sha256(first.strip().encode()).hexdigest()[:16]
        importer._existing_hashes = {existing_hash}

        result = importer.import_source(bible_file)
        assert result.skipped >= 1
        assert result.imported < 6

    def test_fresh_content_is_imported(self, importer, bible_file):
        importer._client.list.return_value = []  # no existing memories
        result = importer.import_source(bible_file)
        assert result.imported == 6
        assert result.skipped == 0
