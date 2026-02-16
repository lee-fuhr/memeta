"""
Feature 42: Meeting Intelligence Tests

Link memories to meeting transcripts, extract context from meetings,
generate pre-meeting briefs based on past conversations.
"""

import pytest
import tempfile
from pathlib import Path

from memory_system.wild.integrations import (
    link_memory_to_meeting,
    get_meeting_memories,
    generate_meeting_brief
)


class TestMemoryMeetingLinks:
    """Tests for linking memories to meetings"""

    def test_link_memory_no_matching_meeting(self):
        """Handles no matching meeting gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            transcripts_db = Path(tmpdir) / "transcripts.db"

            result = link_memory_to_meeting(
                memory_id="test-mem-1",
                meeting_title="Nonexistent Meeting",
                db_path=db_path,
                transcripts_db=transcripts_db
            )
            assert result['status'] == 'not_found'


class TestMeetingMemoryRetrieval:
    """Tests for retrieving memories linked to meetings"""

    def test_get_memories_for_nonexistent_meeting(self):
        """Returns empty list for nonexistent meeting"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            memories = get_meeting_memories(
                meeting_id="nonexistent-123",
                db_path=db_path
            )
            assert memories == []


class TestMeetingBriefGeneration:
    """Tests for generating meeting briefs"""

    def test_generate_brief_no_data(self):
        """Handles no meeting history gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            transcripts_db = Path(tmpdir) / "transcripts.db"

            brief = generate_meeting_brief(
                participant_name="John Doe",
                db_path=db_path,
                transcripts_db=transcripts_db
            )
            assert brief['status'] == 'no_data'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
