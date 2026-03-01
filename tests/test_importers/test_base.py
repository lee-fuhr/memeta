"""Tests for base importer interface."""
import pytest
from memory_system.importers.base import BaseImporter, ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory


class TestImportResult:
    """Test ImportResult dataclass."""

    def test_import_result_defaults(self):
        """ImportResult has correct default values for errors and memories."""
        result = ImportResult(imported=5, skipped=2)
        assert result.imported == 5
        assert result.skipped == 2
        assert result.errors == []
        assert result.memories == []

    def test_import_result_with_errors(self):
        """ImportResult stores errors when provided."""
        result = ImportResult(imported=3, skipped=1, errors=["bad file"])
        assert result.errors == ["bad file"]


class TestImportPreview:
    """Test ImportPreview dataclass."""

    def test_import_preview_defaults(self):
        """ImportPreview has correct default values."""
        preview = ImportPreview(would_import=10, would_skip=3)
        assert preview.would_import == 10
        assert preview.would_skip == 3
        assert preview.sample_memories == []


class TestBaseImporter:
    """Test BaseImporter ABC."""

    def test_base_importer_cannot_be_instantiated(self):
        """BaseImporter is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseImporter()
