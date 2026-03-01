"""Tests for MarkdownDirectoryImporter."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from memory_system.importers.markdown_importer import MarkdownDirectoryImporter
from memory_system.importers.base import ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory


@pytest.fixture
def importer(tmp_path):
    """Create a MarkdownDirectoryImporter with mocked client."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    imp = MarkdownDirectoryImporter(memory_dir=mem_dir, project_id="LFI")
    mock_client = MagicMock()
    mock_client.list.return_value = []
    mock_client.create.return_value = Memory(
        id="test-id",
        content="test",
        importance=0.5,
        tags=[],
        project_id="LFI",
    )
    imp._client = mock_client
    return imp


@pytest.fixture
def source_dir(tmp_path):
    """Create a temporary source directory with markdown files."""
    src = tmp_path / "source"
    src.mkdir()
    return src


class TestMarkdownImportWithFrontmatter:
    """Test importing markdown files with YAML frontmatter."""

    def test_import_with_frontmatter(self, importer, source_dir):
        """Import file with YAML frontmatter extracts metadata correctly."""
        md_file = source_dir / "test-note.md"
        md_file.write_text(
            "---\n"
            "importance: 0.9\n"
            "tags: ['#learning', '#python']\n"
            "domain: development\n"
            "type: directive\n"
            "---\n"
            "\n"
            "Python decorators are powerful for metaprogramming.\n"
        )

        result = importer.import_source(source_dir)

        assert result.imported == 1
        assert result.skipped == 0
        assert result.errors == []
        importer._client.create.assert_called_once()
        call_kwargs = importer._client.create.call_args
        assert call_kwargs.kwargs["importance"] == 0.9
        assert "#learning" in call_kwargs.kwargs["tags"]
        assert "#python" in call_kwargs.kwargs["tags"]

    def test_import_without_frontmatter(self, importer, source_dir):
        """Import plain markdown without frontmatter uses defaults."""
        md_file = source_dir / "plain.md"
        md_file.write_text("Just some plain content without frontmatter.\n")

        result = importer.import_source(source_dir)

        assert result.imported == 1
        assert result.skipped == 0
        importer._client.create.assert_called_once()
        call_kwargs = importer._client.create.call_args
        # Should use guessed importance, not None
        assert isinstance(call_kwargs.kwargs["importance"], float)


class TestMarkdownRecursiveScan:
    """Test recursive directory scanning."""

    def test_nested_directories(self, importer, source_dir):
        """Import recursively scans nested directories."""
        sub = source_dir / "subdir"
        sub.mkdir()
        (source_dir / "top.md").write_text("Top level content.\n")
        (sub / "nested.md").write_text("Nested content in subdirectory.\n")

        result = importer.import_source(source_dir)

        assert result.imported == 2
        assert importer._client.create.call_count == 2


class TestMarkdownImportanceGuessing:
    """Test importance guessing from content characteristics."""

    def test_short_content_low_importance(self, importer, source_dir):
        """Short content gets baseline importance."""
        md_file = source_dir / "short.md"
        md_file.write_text("Brief note.\n")

        result = importer.import_source(source_dir)

        call_kwargs = importer._client.create.call_args
        importance = call_kwargs.kwargs["importance"]
        assert importance <= 0.6  # baseline or slightly above

    def test_long_content_with_code_high_importance(self, importer, source_dir):
        """Long content with code blocks gets higher importance."""
        content = "# Technical guide\n\n" + ("Content line.\n" * 100) + "\n```python\ndef foo():\n    pass\n```\n"
        md_file = source_dir / "technical.md"
        md_file.write_text(content)

        result = importer.import_source(source_dir)

        call_kwargs = importer._client.create.call_args
        importance = call_kwargs.kwargs["importance"]
        assert importance >= 0.7  # boosted by length + code + headings


class TestMarkdownTagExtraction:
    """Test tag extraction from filename patterns."""

    def test_tags_from_filename_patterns(self, importer, source_dir):
        """Filename patterns generate appropriate tags."""
        md_file = source_dir / "api-guide.md"
        md_file.write_text("API reference documentation.\n")

        result = importer.import_source(source_dir)

        call_kwargs = importer._client.create.call_args
        tags = call_kwargs.kwargs["tags"]
        assert "#imported" in tags
        assert "#source:markdown" in tags
        assert "#api" in tags
        assert "#guide" in tags


class TestMarkdownDuplicateDetection:
    """Test duplicate content detection."""

    def test_duplicate_detection_skips_existing(self, importer, source_dir):
        """Duplicate content is detected and skipped."""
        existing_content = "This content already exists in memory."
        # Set up existing memories with matching content
        importer._client.list.return_value = [
            Memory(
                id="existing-1",
                content=existing_content,
                importance=0.5,
                tags=[],
                project_id="LFI",
            )
        ]

        md_file = source_dir / "duplicate.md"
        md_file.write_text(existing_content)

        result = importer.import_source(source_dir)

        assert result.imported == 0
        assert result.skipped == 1
        importer._client.create.assert_not_called()


class TestMarkdownEdgeCases:
    """Test edge cases in markdown importing."""

    def test_empty_files_skipped(self, importer, source_dir):
        """Empty markdown files are skipped."""
        md_file = source_dir / "empty.md"
        md_file.write_text("")

        result = importer.import_source(source_dir)

        assert result.imported == 0
        assert result.skipped == 1
        importer._client.create.assert_not_called()

    def test_binary_files_skipped(self, importer, source_dir):
        """Non-text files (binary) are skipped gracefully."""
        bin_file = source_dir / "image.md"
        bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        result = importer.import_source(source_dir)

        assert result.imported == 0
        # Should either skip or error, not crash
        assert result.skipped >= 0

    def test_utf8_encoding(self, importer, source_dir):
        """UTF-8 encoded files are handled correctly."""
        md_file = source_dir / "unicode.md"
        md_file.write_text("Caf\u00e9 \u2014 Unicode content with \u00fc\u00f6\u00e4 and \u2603\n", encoding="utf-8")

        result = importer.import_source(source_dir)

        assert result.imported == 1
        call_kwargs = importer._client.create.call_args
        assert "Caf\u00e9" in call_kwargs.kwargs["content"]


class TestMarkdownDryRun:
    """Test dry-run preview functionality."""

    def test_dry_run_returns_preview(self, importer, source_dir):
        """Dry run returns counts and sample memories without writing."""
        (source_dir / "one.md").write_text("First file content.\n")
        (source_dir / "two.md").write_text("Second file content.\n")
        (source_dir / "three.md").write_text("Third file content.\n")

        preview = importer.dry_run(source_dir)

        assert isinstance(preview, ImportPreview)
        assert preview.would_import == 3
        assert preview.would_skip == 0
        assert len(preview.sample_memories) <= 5
        # Dry run should NOT call create
        importer._client.create.assert_not_called()


class TestMarkdownProgressCallback:
    """Test progress callback functionality."""

    def test_progress_callback_called(self, importer, source_dir):
        """Progress callback is called with correct counts."""
        (source_dir / "a.md").write_text("Content A.\n")
        (source_dir / "b.md").write_text("Content B.\n")

        progress_calls = []
        importer.set_progress_callback(lambda current, total: progress_calls.append((current, total)))

        importer.import_source(source_dir)

        assert len(progress_calls) >= 2
        # Last call should have current == total
        assert progress_calls[-1][0] == progress_calls[-1][1]


class TestDuplicateCachePerformance:
    """Test that deduplication uses cached hashes (not O(n*m) list calls)."""

    def test_list_called_once_for_multiple_files(self, importer, source_dir):
        """_client.list() should be called once (cached), not per-file."""
        for i in range(5):
            (source_dir / f"note-{i}.md").write_text(f"Unique content number {i}.\n")

        importer.import_source(source_dir)

        # list() should be called exactly once (cached on first _is_duplicate call)
        assert importer._client.list.call_count == 1


class TestFrontmatterSafeParsing:
    """Test that frontmatter parsing doesn't use ast.literal_eval."""

    def test_list_parsing_without_eval(self, importer, source_dir):
        """List values in frontmatter are parsed safely."""
        md_file = source_dir / "tagged.md"
        md_file.write_text(
            "---\n"
            "tags: [learning, python, dev]\n"
            "importance: 0.9\n"
            "---\n"
            "Content with safe list parsing.\n"
        )

        result = importer.import_source(source_dir)

        assert result.imported == 1
        call_kwargs = importer._client.create.call_args
        tags = call_kwargs.kwargs["tags"]
        assert "learning" in tags or "#learning" in [t for t in tags if "learning" in t]

    def test_numeric_only_for_known_fields(self, importer, source_dir):
        """Only known numeric fields are converted to float."""
        md_file = source_dir / "version.md"
        md_file.write_text(
            "---\n"
            "version: 1.0\n"
            "importance: 0.8\n"
            "---\n"
            "Content with version field.\n"
        )

        content, metadata = importer._read_file(md_file)

        # 'version' should stay as string (not a known numeric field)
        assert isinstance(metadata["version"], str)
        # 'importance' should be converted to float
        assert isinstance(metadata["importance"], float)
