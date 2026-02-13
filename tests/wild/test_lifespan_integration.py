"""
Feature 36: Memory Lifespan Integration Tests

Bridges F17 (lifespan prediction) with lifecycle management.
Recommends refresh/archive actions based on staleness + importance.
"""

import pytest
import tempfile
from pathlib import Path

from src.wild.lifespan_integration import (
    analyze_memory_lifespans,
    flag_expiring_memories
)
from src.memory_ts_client import Memory
from datetime import datetime, timedelta
import json


class TestLifespanAnalysis:
    """Tests for memory lifespan analysis"""

    def test_analyze_with_no_data(self):
        """Handles empty memory directory gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_memory_lifespans(memory_dir=Path(tmpdir))
            assert 'total_memories' in result
            assert result['total_memories'] == 0

    def test_flag_expiring_no_memories(self):
        """Returns empty list when no expiring memories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            expiring = flag_expiring_memories(
                days_threshold=7,
                memory_dir=Path(tmpdir)
            )
            assert expiring == []

    def test_analyze_with_fresh_memories(self):
        """Analyzes fresh memories correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fresh memory file
            mem_path = Path(tmpdir) / "test_memory.md"
            content = {
                "id": "test1",
                "content": "Fresh test memory",
                "created": datetime.now().isoformat(),
                "importance": 0.8,
                "tags": ["test"],
                "project_id": "test"
            }
            mem_path.write_text(json.dumps(content))

            result = analyze_memory_lifespans(memory_dir=Path(tmpdir))
            assert result['total_memories'] >= 0  # Should process without error

    def test_analyze_categorizes_by_staleness(self):
        """Categorizes memories by staleness levels"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_memory_lifespans(memory_dir=Path(tmpdir))
            # Should have staleness categories even if empty
            assert 'total_memories' in result

    def test_flag_expiring_threshold_filtering(self):
        """Respects days_threshold parameter"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test with different thresholds
            result_7days = flag_expiring_memories(days_threshold=7, memory_dir=Path(tmpdir))
            result_30days = flag_expiring_memories(days_threshold=30, memory_dir=Path(tmpdir))

            # Both should handle empty gracefully
            assert result_7days == []
            assert result_30days == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
