"""
Feature 39: Notion Integration Tests

Export memories to Notion database.
Track sync state, handle API rate limits.
"""

import pytest
import tempfile
from pathlib import Path

from memory_system.wild.integrations import (
    export_to_notion,
    get_notion_sync_status
)


class TestNotionExport:
    """Tests for Notion export functionality"""

    def test_export_requires_database_id(self):
        """Export validates database_id parameter"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_to_notion(
                notion_database_id=None,
                memory_dir=Path(tmpdir)
            )
            assert result['status'] == 'error'
            assert 'database_id' in result['message'].lower()


class TestNotionSync:
    """Tests for Notion sync status tracking"""

    def test_sync_status_no_history(self):
        """Returns no sync history when never synced"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            status = get_notion_sync_status(db_path=db_path)
            assert status['last_sync'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
