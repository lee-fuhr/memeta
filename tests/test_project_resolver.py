"""
Tests for project_resolver - dynamic project ID derivation

Tests known mappings, fallback decoding, and edge cases.
"""

import pytest

from memory_system.project_resolver import resolve_project_id


class TestKnownMappings:
    """Test exact matches against PROJECT_MAPPING"""

    def test_lfi_root(self):
        """Should resolve LFI root project"""
        assert resolve_project_id("-Users-lee-CC-LFI") == "LFI"

    def test_passive_income(self):
        """Should resolve Passive-Income project"""
        assert resolve_project_id("-Users-lee-CC-Passive-Income") == "Passive-Income"

    def test_personal(self):
        """Should resolve Personal project"""
        assert resolve_project_id("-Users-lee-CC-Personal") == "Personal"

    def test_therapy(self):
        """Should resolve Therapy project"""
        assert resolve_project_id("-Users-lee-CC-Therapy") == "Therapy"

    def test_lfi_ops(self):
        """Should resolve LFI Operations to LFI-Ops"""
        assert resolve_project_id("-Users-lee-CC-LFI---Operations") == "LFI-Ops"

    def test_lfi_ops_memory_system(self):
        """Should resolve memory-system-v1 subdirectory to LFI-Ops"""
        assert resolve_project_id("-Users-lee-CC-LFI---Operations-memory-system-v1") == "LFI-Ops"


class TestFallbackDecoding:
    """Test fallback path decoding for unknown directories"""

    def test_unknown_project_decodes(self):
        """Should decode unknown project from path"""
        result = resolve_project_id("-Users-lee-CC-NewClient")
        assert result == "NewClient"

    def test_unknown_with_subpath(self):
        """Should extract top-level project even with subpath"""
        result = resolve_project_id("-Users-lee-CC-SomeProject---subfolder")
        assert result == "SomeProject"


class TestEdgeCases:
    """Test edge cases and failure modes"""

    def test_empty_string_returns_lfi(self):
        """Empty string should fall back to LFI"""
        assert resolve_project_id("") == "LFI"

    def test_unrecognizable_path_returns_lfi(self):
        """Completely unrecognizable path should fall back to LFI"""
        assert resolve_project_id("gibberish-no-cc-marker") == "LFI"

    def test_google_drive_encoded_path(self):
        """Google Drive paths should still decode"""
        result = resolve_project_id("-Users-lee-Google-Drive-CC-DriveProject")
        # No CC- segment in the standard position, but it should try
        # This path has CC in it so it should pick up "DriveProject"
        assert result == "DriveProject"
