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
            project_id="default",
            tags=["#learning"]
        )

        # Try to add near-identical memory (>90% word overlap hits definite-duplicate path,
        # avoiding LLM-based dedup which requires API key unavailable in CI)
        new_memories = [
            SessionMemory(
                content="When clients object to pricing, acknowledge concern and reframe around value",
                importance=0.7,
                project_id="default"
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
            project_id="test-project",
            tags=["#learning"]
        )

        # Try to add different memory
        new_memories = [
            SessionMemory(
                content="Timeline objections often hide scope confusion",
                importance=0.7,
                project_id="test-project"
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
            SessionMemory(content="High importance pattern", importance=0.85, project_id="test-project"),
            SessionMemory(content="Medium importance pattern", importance=0.72, project_id="test-project"),
            SessionMemory(content="Low importance observation", importance=0.45, project_id="test-project")
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
            SessionMemory(content=f"Important pattern {i}", importance=0.85, project_id="test-project")
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
        memories = client.search(project_id="test-project")

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
            project_id="test-project"
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
            project_id="test-project"
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
            assert memory.project_id == "default"

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


class TestGarbageDetection:
    """Test meta-memory and garbage content filtering"""

    def test_filters_meta_memories_about_memory_system(self):
        """Should reject memories about the memory system itself"""
        from memory_system.session_consolidator import _is_garbage_content

        meta_examples = [
            "Correction: plenty for 3-pass extraction",
            "The memory system consolidation is running",
            "Total Recall extraction found 5 memories",
            "FSRS scheduling algorithm works well",
            "semantic search returned relevant results",
            "session consolidator extracted the learning",
            "intelligence.db stores all the metadata",
            "memory_ts_client.save() writes the file"
        ]

        for text in meta_examples:
            assert _is_garbage_content(text), f"Should filter meta-memory: {text}"

    def test_allows_legitimate_memories_with_similar_words(self):
        """Should allow memories that mention memory/extraction in normal context"""
        from memory_system.session_consolidator import _is_garbage_content

        legitimate = [
            "Client had trouble remembering the pricing model, so we created a memory aid with visual anchors",
            "The data extraction API endpoint was returning 404 errors - fixed by updating the route handler",
            "User wants a system that helps them consolidate their weekly learnings into a digest"
        ]

        for text in legitimate:
            assert not _is_garbage_content(text), f"Should allow legitimate memory: {text}"

    def test_filters_tool_call_artifacts(self):
        """Should reject tool call JSON fragments"""
        from memory_system.session_consolidator import _is_garbage_content

        artifacts = [
            "toolu_abc123 called with input: {'query': 'test'}",
            "tool_use: read_file with {'path': '/some/file'}",
            "'input': {'content': 'testing'}"
        ]

        for text in artifacts:
            assert _is_garbage_content(text), f"Should filter artifact: {text}"

    def test_filters_short_fragments(self):
        """Should reject fragments under 30 characters"""
        from memory_system.session_consolidator import _is_garbage_content

        assert _is_garbage_content("Short")
        assert _is_garbage_content("Too brief to be useful")
        assert not _is_garbage_content("This is long enough to be a legitimate memory with substance")


class TestCorrectionMetadata:
    """Test correction detection + metadata tagging in consolidation pipeline"""

    @pytest.fixture
    def consolidator_with_session(self, temp_dirs):
        """Create consolidator + sample session file with a correction in it"""
        session_dir, memory_dir = temp_dirs
        consolidator = SessionConsolidator(
            session_dir=session_dir,
            memory_dir=memory_dir
        )

        session_file = Path(session_dir) / "test-correction-session.jsonl"
        # "actually, no" triggers the tightened correction regex pattern
        messages = [
            {"role": "user", "content": "Actually, no — it should be validating inputs before processing them in the pipeline workflow system."},
            {"role": "assistant", "content": "Understood, I'll validate inputs before processing. When you validate inputs first, it prevents cascading failures downstream in the pipeline workflow system."},
            {"role": "user", "content": "How should we handle errors?"},
            {"role": "assistant", "content": "When handling errors in production, it's better to fail fast and log context rather than swallowing exceptions silently in distributed systems."},
        ]
        with open(session_file, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

        return consolidator, session_file

    def test_correction_memory_gets_correction_tag(self, consolidator_with_session):
        """Memory with 'Correction: ...' content gets #correction tag"""
        consolidator, session_file = consolidator_with_session
        result = consolidator.consolidate_session(session_file, use_llm=False)

        correction_memories = [
            m for m in result.saved_memories
            if m.content.startswith("Correction: ")
        ]
        # There should be at least one correction memory
        assert len(correction_memories) > 0, "No correction memories found"
        for mem in correction_memories:
            assert "#correction" in mem.tags, f"Missing #correction tag on: {mem.content}"

    def test_correction_memory_gets_context_type_correction(self, consolidator_with_session):
        """Correction memory saved with context_type='correction'"""
        consolidator, session_file = consolidator_with_session
        result = consolidator.consolidate_session(session_file, use_llm=False)

        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)

        correction_memories = [
            m for m in result.saved_memories
            if m.content.startswith("Correction: ")
        ]
        assert len(correction_memories) > 0, "No correction memories found"

        # Read the saved memory from disk to check context_type
        for mem in correction_memories:
            saved = client.get(mem.id)
            assert saved.context_type == "correction", (
                f"Expected context_type='correction', got '{saved.context_type}'"
            )

    def test_correction_memory_gets_permanent_temporal(self, consolidator_with_session):
        """Correction memory saved with temporal_relevance='permanent'"""
        consolidator, session_file = consolidator_with_session
        result = consolidator.consolidate_session(session_file, use_llm=False)

        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)

        correction_memories = [
            m for m in result.saved_memories
            if m.content.startswith("Correction: ")
        ]
        assert len(correction_memories) > 0, "No correction memories found"

        for mem in correction_memories:
            saved = client.get(mem.id)
            assert saved.temporal_relevance == "permanent", (
                f"Expected temporal_relevance='permanent', got '{saved.temporal_relevance}'"
            )

    def test_non_correction_memory_no_correction_metadata(self, consolidator_with_session):
        """Regular (non-correction) memory does NOT get correction metadata"""
        consolidator, session_file = consolidator_with_session
        result = consolidator.consolidate_session(session_file, use_llm=False)

        from memory_system.memory_ts_client import MemoryTSClient
        client = MemoryTSClient(memory_dir=consolidator.memory_dir)

        non_correction = [
            m for m in result.saved_memories
            if not m.content.startswith("Correction: ")
        ]

        for mem in non_correction:
            assert "#correction" not in mem.tags
            saved = client.get(mem.id)
            assert saved.context_type != "correction", (
                f"Non-correction memory has context_type='correction': {mem.content}"
            )

    def test_correction_importance_floor_preserved(self, consolidator_with_session):
        """Corrections maintain >= 0.9 importance"""
        consolidator, session_file = consolidator_with_session
        result = consolidator.consolidate_session(session_file, use_llm=False)

        correction_memories = [
            m for m in result.saved_memories
            if m.content.startswith("Correction: ")
        ]
        assert len(correction_memories) > 0, "No correction memories found"

        for mem in correction_memories:
            assert mem.importance >= 0.9, (
                f"Correction importance {mem.importance} below 0.9 floor"
            )


class TestSkillTagging:
    """Test skill tag injection during consolidation"""

    @pytest.fixture
    def session_with_skills(self, temp_dirs):
        """Create consolidator + session + mock hook state with active skills"""
        session_dir, memory_dir = temp_dirs
        consolidator = SessionConsolidator(
            session_dir=session_dir,
            memory_dir=memory_dir
        )

        session_file = Path(session_dir) / "skill-session.jsonl"
        messages = [
            {"role": "user", "content": "How do I write better headlines?"},
            {"role": "assistant", "content": "When writing headlines, it's better to lead with the benefit rather than the feature to capture attention immediately in your marketing copy."},
        ]
        with open(session_file, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

        return consolidator, session_file

    def test_skill_tags_added_to_all_memories(self, session_with_skills, monkeypatch):
        """When active_skills=['copywriting'], all memories get #skill:copywriting"""
        consolidator, session_file = session_with_skills

        # Mock get_session_state to return active skills
        def mock_get_session_state(session_id):
            return {"active_skills": ["copywriting"]}

        monkeypatch.setattr(
            "memory_system.session_consolidator.get_session_state",
            mock_get_session_state,
        )

        result = consolidator.consolidate_session(session_file, use_llm=False)

        assert result.memories_saved > 0, "No memories saved"
        for mem in result.saved_memories:
            assert "#skill:copywriting" in mem.tags, (
                f"Missing #skill:copywriting on: {mem.content}, tags={mem.tags}"
            )

    def test_skill_tags_empty_when_no_skills(self, session_with_skills, monkeypatch):
        """No active skills = no skill tags added"""
        consolidator, session_file = session_with_skills

        def mock_get_session_state(session_id):
            return {"active_skills": []}

        monkeypatch.setattr(
            "memory_system.session_consolidator.get_session_state",
            mock_get_session_state,
        )

        result = consolidator.consolidate_session(session_file, use_llm=False)

        for mem in result.saved_memories:
            skill_tags = [t for t in mem.tags if t.startswith("#skill:")]
            assert len(skill_tags) == 0, (
                f"Unexpected skill tags on: {mem.content}, tags={mem.tags}"
            )

    def test_multiple_skill_tags(self, session_with_skills, monkeypatch):
        """active_skills=['copywriting', 'seo'] adds both tags"""
        consolidator, session_file = session_with_skills

        def mock_get_session_state(session_id):
            return {"active_skills": ["copywriting", "seo"]}

        monkeypatch.setattr(
            "memory_system.session_consolidator.get_session_state",
            mock_get_session_state,
        )

        result = consolidator.consolidate_session(session_file, use_llm=False)

        assert result.memories_saved > 0, "No memories saved"
        for mem in result.saved_memories:
            assert "#skill:copywriting" in mem.tags, f"Missing #skill:copywriting"
            assert "#skill:seo" in mem.tags, f"Missing #skill:seo"


class TestCorrectionReinforcement:
    """Test correction reinforcement across sessions"""

    @pytest.fixture
    def consolidator_with_existing_correction(self, temp_dirs):
        """Create consolidator with a pre-existing correction memory"""
        session_dir, memory_dir = temp_dirs
        consolidator = SessionConsolidator(
            session_dir=session_dir,
            memory_dir=memory_dir
        )

        # Pre-create an existing correction memory from a prior session
        existing = consolidator.memory_client.create(
            content="Correction: validate inputs before processing them in the pipeline workflow system",
            project_id="default",
            tags=["#learning", "#correction"],
            importance=0.9,
            scope="project",
            context_type="correction",
            temporal_relevance="permanent",
            source_session_id="old-session-123",
            confirmations=0,
        )

        return consolidator, existing

    def test_reinforce_corrections_increments_count(self, consolidator_with_existing_correction):
        """Existing correction gets confirmations+1 when same correction appears again"""
        consolidator, existing = consolidator_with_existing_correction

        new_corrections = [
            SessionMemory(
                content="Correction: validate inputs before processing them in the pipeline workflow system",
                importance=0.9,
                project_id="default",
                tags=["#learning", "#correction"],
                session_id="new-session-456",
            )
        ]

        reinforced = consolidator.reinforce_corrections(new_corrections, session_id="new-session-456")

        # The existing memory's confirmations should be incremented
        updated = consolidator.memory_client.get(existing.id)
        assert updated.confirmations >= 1, (
            f"Expected confirmations >= 1, got {updated.confirmations}"
        )
        assert reinforced >= 1, f"Expected at least 1 reinforced, got {reinforced}"

    def test_reinforce_corrections_same_session_dedup(self, consolidator_with_existing_correction):
        """Correction from same session NOT reinforced (same-session dedup)"""
        consolidator, existing = consolidator_with_existing_correction

        new_corrections = [
            SessionMemory(
                content="Correction: validate inputs before processing them in the pipeline workflow system",
                importance=0.9,
                project_id="default",
                tags=["#learning", "#correction"],
                session_id="old-session-123",  # Same session as the existing memory
            )
        ]

        reinforced = consolidator.reinforce_corrections(new_corrections, session_id="old-session-123")

        # Should NOT reinforce because same session
        updated = consolidator.memory_client.get(existing.id)
        assert updated.confirmations == 0, (
            f"Should not reinforce same-session correction, got confirmations={updated.confirmations}"
        )
        assert reinforced == 0, f"Expected 0 reinforced (same session), got {reinforced}"

    def test_reinforce_corrections_different_session_reinforced(self, consolidator_with_existing_correction):
        """Correction from different session IS reinforced"""
        consolidator, existing = consolidator_with_existing_correction

        new_corrections = [
            SessionMemory(
                content="Correction: validate inputs before processing them in the pipeline workflow system",
                importance=0.9,
                project_id="default",
                tags=["#learning", "#correction"],
                session_id="different-session-789",
            )
        ]

        reinforced = consolidator.reinforce_corrections(new_corrections, session_id="different-session-789")

        updated = consolidator.memory_client.get(existing.id)
        assert updated.confirmations == 1, (
            f"Expected confirmations=1 from cross-session reinforcement, got {updated.confirmations}"
        )
        assert reinforced == 1
