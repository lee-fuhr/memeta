"""
Tests for memory_ts_client.py - TDD approach (RED phase)

Testing memory-ts API wrapper for:
- Creating memories
- Searching/querying memories
- Updating memories
- Getting specific memories
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from memory_system.memory_ts_client import (
    MemoryTSClient,
    Memory,
    MemoryNotFoundError,
    MemoryTSError
)


@pytest.fixture
def temp_memory_dir():
    """Create temporary directory for test memories"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_memory_dir):
    """Create client pointing to temp directory"""
    return MemoryTSClient(memory_dir=temp_memory_dir)


class TestMemoryCreation:
    """Test creating new memories"""

    def test_create_basic_memory(self, client):
        """Create memory with required fields"""
        memory = client.create(
            content="Test learning about patterns",
            project_id="LFI",
            tags=["#learning", "#test"]
        )

        assert memory.id is not None
        assert "Test learning" in memory.content
        assert memory.project_id == "LFI"
        assert "#learning" in memory.tags

    def test_create_memory_with_importance(self, client):
        """Create memory with custom importance"""
        memory = client.create(
            content="Important pattern",
            project_id="LFI",
            importance=0.85,
            tags=["#learning"]
        )

        assert memory.importance == 0.85

    def test_create_memory_with_scope(self, client):
        """Create memory with scope (project/global)"""
        memory = client.create(
            content="Project-specific pattern",
            project_id="LFI",
            scope="project",
            tags=["#learning"]
        )

        assert memory.scope == "project"

    def test_create_memory_auto_generates_id(self, client):
        """Memory ID is auto-generated timestamp-based"""
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#test"]
        )

        # ID should be timestamp-hash format
        assert "-" in memory.id
        parts = memory.id.split("-")
        assert len(parts) == 2

    def test_create_memory_writes_file(self, client, temp_memory_dir):
        """Memory is written to disk as markdown file"""
        memory = client.create(
            content="Test content",
            project_id="LFI",
            tags=["#test"]
        )

        # File should exist
        memory_file = Path(temp_memory_dir) / f"{memory.id}.md"
        assert memory_file.exists()

        # File should contain YAML frontmatter
        content = memory_file.read_text()
        assert "---" in content
        assert "id:" in content
        assert "Test content" in content


class TestMemorySearch:
    """Test searching and querying memories"""

    def test_search_by_tag(self, client):
        """Search memories by tag"""
        # Create some test memories
        client.create(content="Pattern 1", project_id="LFI", tags=["#learning", "#pattern"])
        client.create(content="Pattern 2", project_id="LFI", tags=["#learning", "#bug"])

        results = client.search(tags=["#pattern"])
        assert len(results) == 1
        assert "Pattern 1" in results[0].content

    def test_search_by_content(self, client):
        """Search memories by content text"""
        client.create(content="Client preferred direct language", project_id="LFI", tags=["#learning"])
        client.create(content="Updated button color", project_id="LFI", tags=["#learning"])

        results = client.search(content="direct language")
        assert len(results) == 1
        assert "direct language" in results[0].content

    def test_search_by_scope(self, client):
        """Search memories by scope"""
        client.create(content="Project pattern", project_id="LFI", scope="project", tags=["#learning"])
        client.create(content="Global pattern", project_id="LFI", scope="global", tags=["#learning"])

        results = client.search(scope="global")
        assert len(results) == 1
        assert "Global pattern" in results[0].content

    def test_search_by_project(self, client):
        """Search memories by project_id"""
        client.create(content="LFI pattern", project_id="LFI", tags=["#learning"])
        client.create(content="Other pattern", project_id="OtherProject", tags=["#learning"])

        results = client.search(project_id="LFI")
        assert len(results) == 1
        assert "LFI pattern" in results[0].content

    def test_search_returns_empty_for_no_matches(self, client):
        """Search returns empty list when nothing matches"""
        results = client.search(tags=["#nonexistent"])
        assert len(results) == 0


class TestMemoryRetrieval:
    """Test getting specific memories"""

    def test_get_memory_by_id(self, client):
        """Get specific memory by ID"""
        created = client.create(
            content="Specific memory",
            project_id="LFI",
            tags=["#test"]
        )

        retrieved = client.get(created.id)
        assert retrieved.id == created.id
        assert retrieved.content == created.content

    def test_get_nonexistent_memory_raises_error(self, client):
        """Getting nonexistent memory raises MemoryNotFoundError"""
        with pytest.raises(MemoryNotFoundError):
            client.get("nonexistent-id")


class TestMemoryUpdate:
    """Test updating existing memories"""

    def test_update_memory_importance(self, client):
        """Update memory importance score"""
        memory = client.create(
            content="Test pattern",
            project_id="LFI",
            importance=0.7,
            tags=["#learning"]
        )

        updated = client.update(memory.id, importance=0.85)
        assert updated.importance == 0.85

    def test_update_memory_scope(self, client):
        """Update memory scope (promote project → global)"""
        memory = client.create(
            content="Pattern",
            project_id="LFI",
            scope="project",
            tags=["#learning"]
        )

        updated = client.update(memory.id, scope="global")
        assert updated.scope == "global"

    def test_update_memory_tags(self, client):
        """Update memory tags (add #promoted)"""
        memory = client.create(
            content="Pattern",
            project_id="LFI",
            tags=["#learning"]
        )

        updated = client.update(memory.id, tags=["#learning", "#promoted"])
        assert "#promoted" in updated.tags

    def test_update_memory_content(self, client):
        """Update memory content"""
        memory = client.create(
            content="Original content",
            project_id="LFI",
            tags=["#test"]
        )

        updated = client.update(memory.id, content="Updated content")
        assert updated.content == "Updated content"

    def test_update_nonexistent_memory_raises_error(self, client):
        """Updating nonexistent memory raises MemoryNotFoundError"""
        with pytest.raises(MemoryNotFoundError):
            client.update("nonexistent-id", importance=0.9)


class TestMemoryModel:
    """Test Memory data model"""

    def test_memory_has_required_fields(self, client):
        """Memory object has all required fields"""
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#test"]
        )

        assert hasattr(memory, 'id')
        assert hasattr(memory, 'content')
        assert hasattr(memory, 'importance')
        assert hasattr(memory, 'tags')
        assert hasattr(memory, 'project_id')
        assert hasattr(memory, 'scope')
        assert hasattr(memory, 'created')
        assert hasattr(memory, 'updated')

    def test_memory_timestamps_are_iso_format(self, client):
        """Memory timestamps are ISO 8601 formatted"""
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#test"]
        )

        # Should be parseable as ISO datetime
        created_dt = datetime.fromisoformat(memory.created)
        updated_dt = datetime.fromisoformat(memory.updated)
        assert isinstance(created_dt, datetime)
        assert isinstance(updated_dt, datetime)

    def test_memory_default_scope_is_project(self, client):
        """New memories default to project scope"""
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#test"]
        )

        assert memory.scope == "project"

    def test_memory_default_importance(self, client):
        """New memories get default importance if not specified"""
        memory = client.create(
            content="Test",
            project_id="LFI",
            tags=["#test"]
        )

        assert 0.3 <= memory.importance <= 1.0


class TestPathTraversal:
    """Test path traversal protection in memory operations"""

    def test_get_sanitizes_path_traversal(self, client):
        """Memory ID with path traversal is sanitized, not executed"""
        # ../../etc/passwd → etcpasswd (safe, just not found)
        with pytest.raises(MemoryNotFoundError):
            client.get("../../etc/passwd")

    def test_get_sanitizes_slashes(self, client):
        """Memory ID with slashes gets sanitized"""
        with pytest.raises(MemoryNotFoundError):
            client.get("foo/bar")

    def test_get_rejects_empty_after_sanitization(self, client):
        """Memory ID that's empty after sanitization should be rejected"""
        with pytest.raises(ValueError, match="Invalid memory_id"):
            client.get("/../..")

    def test_safe_path_stays_under_memory_dir(self, client):
        """Resolved path should always be under the memory directory"""
        path = client._safe_memory_path("normal-id-123")
        assert str(path).startswith(str(client.memory_dir.resolve()))


class TestFileCorruption:
    """Test handling of corrupted memory files"""

    def test_read_memory_no_frontmatter(self, temp_memory_dir):
        """Should raise error for file without YAML frontmatter"""
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        bad_file = Path(temp_memory_dir) / "bad.md"
        bad_file.write_text("Just plain content, no frontmatter")

        with pytest.raises(MemoryTSError, match="Invalid memory file format"):
            client._read_memory(bad_file)

    def test_read_memory_empty_frontmatter(self, temp_memory_dir):
        """Should handle file with empty frontmatter"""
        client = MemoryTSClient(memory_dir=temp_memory_dir)
        empty_fm = Path(temp_memory_dir) / "empty-fm.md"
        empty_fm.write_text("---\n---\nSome content")

        memory = client._read_memory(empty_fm)
        assert memory.content == "Some content"

    def test_search_skips_corrupt_files(self, temp_memory_dir):
        """Search should skip files that can't be parsed"""
        client = MemoryTSClient(memory_dir=temp_memory_dir)

        # Create one good memory
        client.create(content="Valid memory", project_id="LFI", tags=["#test"])

        # Create one corrupt file
        bad_file = Path(temp_memory_dir) / "corrupt.md"
        bad_file.write_text("Not a valid memory file")

        # Search should still return the good one
        results = client.search()
        assert len(results) >= 1
