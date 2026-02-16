"""
Feature 38: Obsidian Integration Tests

Bidirectional sync with Obsidian vaults.
Export memories as markdown, import Obsidian notes as memories.
"""

import pytest
import tempfile
from pathlib import Path

from memory_system.wild.integrations import (
    export_to_obsidian,
    import_from_obsidian,
    sync_obsidian_vault
)


class TestObsidianExport:
    """Tests for exporting memories to Obsidian"""

    def test_export_creates_vault_structure(self):
        """Creates proper Obsidian vault structure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault"
            export_to_obsidian(vault_path=vault_path)

            # Verify vault was created
            assert vault_path.exists()


class TestObsidianImport:
    """Tests for importing Obsidian notes"""

    def test_import_empty_vault(self):
        """Handles empty vault gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault"
            vault_path.mkdir()

            imported = import_from_obsidian(vault_path=vault_path)
            assert imported['count'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
