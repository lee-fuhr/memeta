"""
Tests for log rotation

Tests line counting, gzip archiving, truncation, and threshold behavior.
"""

import gzip
import pytest

from memory_system.log_rotation import maybe_rotate_log


@pytest.fixture
def log_file(tmp_path):
    """Create a temporary log file"""
    return tmp_path / "test_events.jsonl"


class TestLogRotation:
    """Test log file rotation"""

    def test_no_rotation_below_threshold(self, log_file):
        """Should not rotate when line count is below max_lines"""
        # Write 5 lines (below default 10,000)
        log_file.write_text("".join(f'{{"line": {i}}}\n' for i in range(5)))

        result = maybe_rotate_log(log_file, max_lines=10)

        assert result is False
        assert log_file.read_text() != ""  # File unchanged

    def test_rotation_creates_gzipped_archive(self, log_file):
        """Should create gzipped archive when threshold exceeded"""
        lines = [f'{{"event": "test", "n": {i}}}\n' for i in range(15)]
        log_file.write_text("".join(lines))

        result = maybe_rotate_log(log_file, max_lines=10)

        assert result is True

        # Find the archive file
        archives = list(log_file.parent.glob("test_events-*.jsonl.gz"))
        assert len(archives) == 1

    def test_original_file_emptied_after_rotation(self, log_file):
        """Original file should be empty after rotation"""
        lines = [f'{{"event": "test", "n": {i}}}\n' for i in range(15)]
        log_file.write_text("".join(lines))

        maybe_rotate_log(log_file, max_lines=10)

        assert log_file.read_text() == ""

    def test_archive_contains_original_content(self, log_file):
        """Archive should contain all original content"""
        original_content = "".join(
            f'{{"event": "test", "n": {i}}}\n' for i in range(15)
        )
        log_file.write_text(original_content)

        maybe_rotate_log(log_file, max_lines=10)

        archives = list(log_file.parent.glob("test_events-*.jsonl.gz"))
        with gzip.open(archives[0], "rt") as f:
            archived_content = f.read()

        assert archived_content == original_content

    def test_no_rotation_for_nonexistent_file(self, tmp_path):
        """Should handle nonexistent file gracefully"""
        result = maybe_rotate_log(tmp_path / "nonexistent.jsonl")
        assert result is False

    def test_exact_threshold_no_rotation(self, log_file):
        """Should not rotate when line count equals max_lines exactly"""
        lines = [f'{{"event": "test", "n": {i}}}\n' for i in range(10)]
        log_file.write_text("".join(lines))

        result = maybe_rotate_log(log_file, max_lines=10)

        assert result is False
