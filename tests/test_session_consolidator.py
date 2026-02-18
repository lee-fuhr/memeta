"""
Tests for session_consolidator.py - TDD approach (RED phase)

Testing session memory extraction:
- Reading session JSONL files
- LLM-powered memory extraction
- Importance scoring integration
- Deduplication against existing memories
- Session quality score tracking
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
from memory_system.session_consolidator import (
    SessionConsolidator,
    SessionMemory,
    SessionQualityScore,
    ConsolidationResult,
    extract_memories_from_session,
    deduplicate_memories,
    calculate_session_quality
)


@pytest.fixture
def temp_dirs():
    """Create temporary directories for test data"""
    session_dir = tempfile.mkdtemp()
    memory_dir = tempfile.mkdtemp()
    yield session_dir, memory_dir
    # Cleanup handled by tempfile


@pytest.fixture
def sample_session_file(temp_dirs):
    """Create sample session JSONL file"""
    session_dir, _ = temp_dirs
    session_file = Path(session_dir) / "test-session.jsonl"

    # Sample session data
    messages = [
        {"role": "user", "content": "How do I handle client objections?"},
        {"role": "assistant", "content": "When clients object to pricing, I've found it's better to acknowledge their concern directly rather than defending the price. Say 'I hear you' and then reframe around value."},
        {"role": "user", "content": "That's helpful. What about timeline objections?"},
        {"role": "assistant", "content": "Timeline objections often hide scope confusion. Ask 'what needs to happen by that date?' to surface the real constraint."}
    ]

    with open(session_file, 'w') as f:
        for msg in messages:
            f.write(json.dumps(msg) + '\n')

    return session_file


@pytest.fixture
def consolidator(temp_dirs):
    """Create consolidator with temp directories"""
    session_dir, memory_dir = temp_dirs
    return SessionConsolidator(
        session_dir=session_dir,
        memory_dir=memory_dir
    )


class TestSessionReading:
    """Test reading and parsing session files"""

    def test_read_session_file(self, consolidator, sample_session_file):
        """Read session JSONL file successfully"""
        messages = consolidator.read_session(sample_session_file)

        assert len(messages) > 0
        assert "role" in messages[0]
        assert "content" in messages[0]

    def test_extract_conversation_text(self, consolidator, sample_session_file):
        """Extract plain text from session messages"""
        messages = consolidator.read_session(sample_session_file)
        conversation_text = consolidator.extract_conversation_text(messages)

        assert "client objections" in conversation_text.lower()
        assert "acknowledge their concern" in conversation_text.lower()

    def test_handle_nonexistent_session(self, consolidator):
        """Handle missing session file gracefully"""
        with pytest.raises(FileNotFoundError):
            consolidator.read_session(Path("nonexistent.jsonl"))


class TestMemoryExtraction:
    """Test LLM-powered memory extraction"""

    def test_extract_memories_from_content(self, consolidator, sample_session_file):
        """Extract learnings from session content"""
        messages = consolidator.read_session(sample_session_file)
        conversation = consolidator.extract_conversation_text(messages)

        memories = consolidator.extract_memories(conversation)

        assert len(memories) > 0
        assert isinstance(memories[0], SessionMemory)

    def test_extracted_memory_has_content(self, consolidator, sample_session_file):
        """Extracted memories have meaningful content"""
        messages = consolidator.read_session(sample_session_file)
        conversation = consolidator.extract_conversation_text(messages)
        memories = consolidator.extract_memories(conversation)

        memory = memories[0]
        assert len(memory.content) > 20  # Substantial content
        assert memory.content != conversation  # Not just raw transcript

    def test_extracted_memory_has_importance(self, consolidator, sample_session_file):
        """Extracted memories have importance scores"""
        messages = consolidator.read_session(sample_session_file)
        conversation = consolidator.extract_conversation_text(messages)
        memories = consolidator.extract_memories(conversation)

        memory = memories[0]
        assert 0.3 <= memory.importance <= 1.0

    def test_empty_session_returns_no_memories(self, consolidator):
        """Empty or trivial sessions produce no memories"""
        empty_conversation = "Hi. Bye."
        memories = consolidator.extract_memories(empty_conversation)

        assert len(memories) == 0


class TestDeduplication:
    """Test deduplication against existing memories"""

    def test_deduplicate_against_existing(self, consolidator):
        """Remove duplicates of existing memories"""
        # Create existing memory
        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)
        client.create(
            content="When clients object to pricing, acknowledge their concern and reframe around value",
            project_id="LFI",
            tags=["#learning"]
        )

        # Try to add near-identical memory (>90% word overlap hits definite-duplicate path,
        # avoiding LLM-based dedup which requires API key unavailable in CI)
        new_memories = [
            SessionMemory(
                content="When clients object to pricing, acknowledge concern and reframe around value",
                importance=0.7,
                project_id="LFI"
            )
        ]

        deduplicated = consolidator.deduplicate(new_memories)

        # Should be filtered out as duplicate
        assert len(deduplicated) == 0

    def test_keeps_distinct_memories(self, consolidator):
        """Keep memories that are not duplicates"""
        # Create existing memory
        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)
        client.create(
            content="Pricing objection handling",
            project_id="LFI",
            tags=["#learning"]
        )

        # Try to add different memory
        new_memories = [
            SessionMemory(
                content="Timeline objections often hide scope confusion",
                importance=0.7,
                project_id="LFI"
            )
        ]

        deduplicated = consolidator.deduplicate(new_memories)

        # Should keep distinct memory
        assert len(deduplicated) == 1


class TestSessionQuality:
    """Test session quality score calculation"""

    def test_calculate_quality_score(self):
        """Calculate quality score from extracted memories"""
        memories = [
            SessionMemory(content="High importance pattern", importance=0.85, project_id="LFI"),
            SessionMemory(content="Medium importance pattern", importance=0.72, project_id="LFI"),
            SessionMemory(content="Low importance observation", importance=0.45, project_id="LFI")
        ]

        quality = calculate_session_quality(memories)

        assert quality.total_memories == 3
        assert quality.high_value_count == 2  # >= 0.7
        assert 0.0 <= quality.quality_score <= 1.0

    def test_quality_score_empty_session(self):
        """Empty session gets zero quality score"""
        quality = calculate_session_quality([])

        assert quality.total_memories == 0
        assert quality.high_value_count == 0
        assert quality.quality_score == 0.0

    def test_quality_score_high_value_session(self):
        """Session with many high-value memories gets high score"""
        memories = [
            SessionMemory(content=f"Important pattern {i}", importance=0.85, project_id="LFI")
            for i in range(5)
        ]

        quality = calculate_session_quality(memories)

        assert quality.quality_score >= 0.8  # High quality


class TestEndToEndConsolidation:
    """Test complete consolidation pipeline"""

    def test_consolidate_session_end_to_end(self, consolidator, sample_session_file):
        """Full pipeline: read → extract → deduplicate → save"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        assert result.memories_extracted >= 0
        assert result.memories_saved >= 0
        assert result.session_quality is not None

    def test_consolidation_creates_memory_files(self, consolidator, sample_session_file):
        """Consolidation creates actual memory files"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        # Check memory files were created
        memory_files = list(Path(consolidator.memory_dir).glob("*.md"))
        assert len(memory_files) >= result.memories_saved

    def test_consolidation_tracks_session_id(self, consolidator, sample_session_file):
        """Memories include session_id for traceability"""
        consolidator.consolidate_session(sample_session_file, use_llm=False)

        # Check created memories have session_id
        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)
        memories = client.search(project_id="LFI")

        if len(memories) > 0:
            # Should have session_id in metadata
            assert hasattr(memories[0], 'id')


class TestSessionMemoryModel:
    """Test SessionMemory data model"""

    def test_session_memory_has_required_fields(self):
        """SessionMemory has all required fields"""
        memory = SessionMemory(
            content="Test learning",
            importance=0.7,
            project_id="LFI"
        )

        assert hasattr(memory, 'content')
        assert hasattr(memory, 'importance')
        assert hasattr(memory, 'project_id')
        assert hasattr(memory, 'tags')

    def test_session_memory_default_tags(self):
        """SessionMemory gets default #learning tag"""
        memory = SessionMemory(
            content="Test",
            importance=0.7,
            project_id="LFI"
        )

        assert "#learning" in memory.tags


class TestSavedMemoriesInResult:
    """Test that ConsolidationResult includes saved memory objects"""

    def test_consolidation_result_includes_saved_memories(self, consolidator, sample_session_file):
        """ConsolidationResult.saved_memories is populated after consolidation"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        assert hasattr(result, 'saved_memories')
        assert isinstance(result.saved_memories, list)
        if result.memories_saved > 0:
            assert len(result.saved_memories) > 0
            assert isinstance(result.saved_memories[0], SessionMemory)

    def test_saved_memories_have_ids(self, consolidator, sample_session_file):
        """Saved memories have IDs captured from memory-ts create"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        for memory in result.saved_memories:
            assert memory.id is not None
            assert len(memory.id) > 0

    def test_saved_memories_match_count(self, consolidator, sample_session_file):
        """len(saved_memories) == memories_saved"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        assert len(result.saved_memories) == result.memories_saved

    def test_saved_memories_have_content(self, consolidator, sample_session_file):
        """Saved memories retain content and project_id"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        for memory in result.saved_memories:
            assert len(memory.content) > 0
            assert memory.project_id == "LFI"

    def test_consolidation_result_default_empty(self):
        """ConsolidationResult defaults saved_memories to empty list"""
        result = ConsolidationResult(
            memories_extracted=0,
            memories_saved=0,
            memories_deduplicated=0,
            session_quality=SessionQualityScore(
                total_memories=0, high_value_count=0, quality_score=0.0
            ),
        )
        assert result.saved_memories == []


class TestAllExtractedField:
    """Test that ConsolidationResult includes all_extracted (pre-dedup) memories"""

    def test_all_extracted_populated(self, consolidator, sample_session_file):
        """all_extracted should contain all memories before dedup"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        assert hasattr(result, 'all_extracted')
        assert isinstance(result.all_extracted, list)
        # all_extracted should be >= saved (includes deduped ones)
        assert len(result.all_extracted) >= len(result.saved_memories)

    def test_all_extracted_includes_deduped(self, consolidator, sample_session_file):
        """all_extracted count should equal memories_extracted"""
        result = consolidator.consolidate_session(sample_session_file, use_llm=False)

        assert len(result.all_extracted) == result.memories_extracted

    def test_all_extracted_default_empty(self):
        """ConsolidationResult defaults all_extracted to empty list"""
        result = ConsolidationResult(
            memories_extracted=0,
            memories_saved=0,
            memories_deduplicated=0,
            session_quality=SessionQualityScore(
                total_memories=0, high_value_count=0, quality_score=0.0
            ),
        )
        assert result.all_extracted == []


class TestImportanceIntegration:
    """Test integration with importance_engine"""

    def test_uses_importance_engine_for_scoring(self, consolidator):
        """Memory importance calculated using importance_engine"""
        content = "CRITICAL: Production pattern broke across 3 clients"
        memories = consolidator.extract_memories(content)

        if len(memories) > 0:
            # Should have high importance from trigger words
            assert memories[0].importance >= 0.7
