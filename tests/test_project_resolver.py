"""
Tests for project_resolver - dynamic project ID derivation

Tests known mappings, fallback decoding, and edge cases.
"""

import pytest

from memory_system.project_resolver import resolve_project_id


class TestKnownMappings:
    """Test path decoding for common project directory structures"""

    def test_simple_project(self):
        """Should decode simple project segment from path"""
        assert resolve_project_id("-Users-lee-CC-MyCompany") == "MyCompany"

    def test_hyphenated_project(self):
        """Should preserve hyphens within a project name"""
        assert resolve_project_id("-Users-lee-CC-Passive-Income") == "Passive-Income"

    def test_personal(self):
        """Should resolve Personal project"""
        assert resolve_project_id("-Users-lee-CC-Personal") == "Personal"

    def test_therapy(self):
        """Should resolve Therapy project"""
        assert resolve_project_id("-Users-lee-CC-Therapy") == "Therapy"

    def test_project_with_subdir(self):
        """Should extract top-level project when subdir uses triple-dash separator"""
        assert resolve_project_id("-Users-lee-CC-MyCompany---Operations") == "MyCompany"

    def test_project_with_nested_subdir(self):
        """Should extract top-level project from deeply nested path"""
        assert resolve_project_id("-Users-lee-CC-MyCompany---Operations-memory-system-v1") == "MyCompany"


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

    def test_empty_string_returns_default(self):
        """Empty string should fall back to 'default'"""
        assert resolve_project_id("") == "default"

    def test_unrecognizable_path_returns_default(self):
        """Completely unrecognizable path should fall back to 'default'"""
        assert resolve_project_id("gibberish-no-cc-marker") == "default"

    def test_google_drive_encoded_path(self):
        """Google Drive paths should still decode"""
        result = resolve_project_id("-Users-lee-Google-Drive-CC-DriveProject")
        # No CC- segment in the standard position, but it should try
        # This path has CC in it so it should pick up "DriveProject"
        assert result == "DriveProject"
