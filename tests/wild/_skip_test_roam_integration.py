"""
Feature 40: Roam Research Integration Tests

Export memories to Roam Research format (nested bullets, backlinks).
"""

import pytest
import tempfile
from pathlib import Path

from memory_system.wild.integrations import (
    export_to_roam,
    format_memory_as_roam
)


class TestRoamExport:
    """Tests for Roam export functionality"""

    def test_export_creates_roam_format(self):
        """Exports create Roam-compatible markdown"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "roam-export.md"
            result = export_to_roam(
                output_path=output_path,
                memory_dir=Path(tmpdir)
            )
            assert result['status'] == 'success'


class TestRoamFormatting:
    """Tests for Roam markdown formatting"""

    def test_format_includes_backlinks(self):
        """Formatted memories include proper backlinks"""
        from memory_system.memory_ts_client import Memory
        mem = Memory(
            id="test1",
            content="Test memory",
            importance=0.8,
            tags=["client", "decision"],
            project_id="test"
        )
        formatted = format_memory_as_roam(mem)
        # Roam uses [[tag]] syntax for backlinks
        assert '[[' in formatted and ']]' in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
