"""
Tests for agent context function - memory briefings for delegated agents.

TDD: These tests are written FIRST before implementation.
"""

import pytest
from pathlib import Path
import tempfile
import json


@pytest.fixture
def sample_memories():
    """Sample memories with various tags and context types"""
    return [
        {
            "id": "mem-001",
            "content": "Lee prefers TDD workflow with red/green cycles",
            "importance": 0.9,
            "tags": ["development", "workflow", "testing"],
            "context_type": "knowledge",
            "project_id": "test-project"
        },
        {
            "id": "mem-002",
            "content": "Jane Smith is a client, partner Alex, loves hiking",
            "importance": 0.85,
            "tags": ["relationship", "client", "personal"],
            "context_type": "knowledge",
            "project_id": "test-project"
        },
        {
            "id": "mem-003",
            "content": "Correction: Always use sentence case for headings, not title case",
            "importance": 0.95,
            "tags": ["correction", "writing"],
            "context_type": "correction",
            "project_id": "test-project"
        },
        {
            "id": "mem-004",
            "content": "Brand voice: Direct, no fluff, challenge thinking",
            "importance": 0.9,
            "tags": ["brand", "messaging", "voice"],
            "context_type": "knowledge",
            "project_id": "test-project"
        },
        {
            "id": "mem-005",
            "content": "Python venvs should not be in cloud-synced folders",
            "importance": 0.8,
            "tags": ["development", "python", "infrastructure"],
            "context_type": "knowledge",
            "project_id": "test-project"
        },
        {
            "id": "mem-006",
            "content": "Correction: Never use 'any' type in TypeScript - use unknown + type guards",
            "importance": 0.92,
            "tags": ["correction", "typescript", "code-quality"],
            "context_type": "correction",
            "project_id": "test-project"
        },
        {
            "id": "mem-007",
            "content": "Acme Corp focuses on B2B relationship building software",
            "importance": 0.75,
            "tags": ["client", "business", "product"],
            "context_type": "knowledge",
            "project_id": "ConnectionLab"
        },
    ]


@pytest.fixture
def temp_memory_index(sample_memories):
    """Create temporary JSON search index"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_memories, f)
        yield Path(f.name)
    Path(f.name).unlink()


class TestAgentContextBasics:
    """Test basic functionality of get_context_for_agent"""

    def test_returns_tuple(self, sample_memories):
        """Should return tuple of (context_string, memory_ids)"""
        from memory_system.agent_context import get_context_for_agent

        result = get_context_for_agent(
            agent_type="dev",
            task_description="Fix TypeScript type errors",
            memories=sample_memories
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        context_str, memory_ids = result
        assert isinstance(context_str, str)
        assert isinstance(memory_ids, list)

    def test_returns_formatted_context_string(self, sample_memories):
        """Context string should be formatted for agent consumption"""
        from memory_system.agent_context import get_context_for_agent

        context_str, _ = get_context_for_agent(
            agent_type="dev",
            task_description="Build Python API",
            memories=sample_memories
        )

        assert len(context_str) > 0
        assert "RELEVANT MEMORIES" in context_str or "memories" in context_str.lower()

    def test_returns_memory_ids(self, sample_memories):
        """Should return list of memory IDs used in context"""
        from memory_system.agent_context import get_context_for_agent

        _, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Python development",
            memories=sample_memories
        )

        assert len(memory_ids) > 0
        assert all(isinstance(mid, str) for mid in memory_ids)
        assert all(mid.startswith("mem-") for mid in memory_ids)

    def test_respects_top_k_limit(self, sample_memories):
        """Should return at most top_k memories"""
        from memory_system.agent_context import get_context_for_agent

        _, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Development work",
            memories=sample_memories,
            top_k=3
        )

        assert len(memory_ids) <= 3

    def test_handles_empty_memories(self):
        """Should handle empty memory list gracefully"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Some task",
            memories=[]
        )

        assert isinstance(context_str, str)
        assert len(memory_ids) == 0


class TestAgentTypeTagFiltering:
    """Test agent-type-aware tag filtering"""

    def test_dev_agent_gets_dev_tags(self, sample_memories):
        """Dev agent should prioritize development-tagged memories"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Python development",
            memories=sample_memories,
            top_k=5
        )

        # Should include development-tagged memories
        assert "mem-001" in memory_ids or "mem-005" in memory_ids

    def test_brand_agent_gets_brand_tags(self, sample_memories):
        """Brand agent should prioritize brand/messaging-tagged memories"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="brand",
            task_description="Create brand messaging",
            memories=sample_memories,
            top_k=5
        )

        # Should include brand-tagged memory
        assert "mem-004" in memory_ids

    def test_unknown_agent_type_still_works(self, sample_memories):
        """Unknown agent types should fall back to generic filtering"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="unknown-agent",
            task_description="Some task",
            memories=sample_memories
        )

        # Should still return results based on task description
        assert isinstance(context_str, str)
        assert isinstance(memory_ids, list)


class TestCorrectionSurfacing:
    """Test that corrections always surface regardless of tag filter"""

    def test_corrections_always_surface(self, sample_memories):
        """Corrections should appear even if not matching agent tags"""
        from memory_system.agent_context import get_context_for_agent

        # Dev agent asking about TypeScript - correction should surface
        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="TypeScript refactoring",
            memories=sample_memories,
            top_k=5
        )

        # Should include TypeScript correction
        assert "mem-006" in memory_ids

    def test_writing_correction_surfaces_for_writer(self, sample_memories):
        """Writing corrections should surface for writing tasks"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="copywriter",
            task_description="Write blog post headings",
            memories=sample_memories,
            top_k=5
        )

        # Should include sentence case correction
        assert "mem-003" in memory_ids

    def test_corrections_prioritized_by_importance(self, sample_memories):
        """Higher importance corrections should appear first"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="General development",
            memories=sample_memories,
            top_k=3
        )

        # High importance corrections should be included
        correction_ids = [m["id"] for m in sample_memories if m["context_type"] == "correction"]
        assert any(cid in memory_ids for cid in correction_ids)


class TestHybridSearch:
    """Test that function uses hybrid search (not BM25-only)"""

    def test_uses_hybrid_search(self, sample_memories, monkeypatch):
        """Should call hybrid_search from hybrid_search module"""
        from memory_system import agent_context

        hybrid_called = []

        def mock_hybrid(query, memories, top_k=10, **kwargs):
            hybrid_called.append(True)
            # Return scored memories
            return [
                {**m, "hybrid_score": 1.0, "semantic_score": 0.7, "bm25_score": 0.3}
                for m in memories[:top_k]
            ]

        # Mock the module's hybrid_search function
        monkeypatch.setattr(agent_context.hybrid_search_module, "hybrid_search", mock_hybrid)

        agent_context.get_context_for_agent(
            agent_type="dev",
            task_description="Python work",
            memories=sample_memories
        )

        assert len(hybrid_called) > 0, "Should use hybrid_search"


class TestProjectFiltering:
    """Test project-specific filtering"""

    def test_filters_by_project_id(self, sample_memories):
        """Should filter to specific project when specified"""
        from memory_system.agent_context import get_context_for_agent

        _, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Development work",
            memories=sample_memories,
            project_id="test-project"
        )

        # Should not include ConnectionLab memory
        assert "mem-007" not in memory_ids

    def test_no_project_filter_includes_all(self, sample_memories):
        """When no project specified, should consider all memories"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="general",
            task_description="Acme Corp relationship building",
            memories=sample_memories,
            top_k=10
        )

        # Could include ConnectionLab memory if relevant to query
        # (Just verifying it doesn't crash without project filter)
        assert isinstance(memory_ids, list)


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_handles_memories_without_tags(self):
        """Should handle memories missing tags field"""
        from memory_system.agent_context import get_context_for_agent

        memories = [
            {
                "id": "mem-no-tags",
                "content": "Memory without tags",
                "importance": 0.8,
                "context_type": "knowledge",
                "project_id": "test-project"
            }
        ]

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Some task",
            memories=memories
        )

        assert isinstance(context_str, str)
        assert isinstance(memory_ids, list)

    def test_handles_memories_without_context_type(self):
        """Should handle memories missing context_type field"""
        from memory_system.agent_context import get_context_for_agent

        memories = [
            {
                "id": "mem-no-type",
                "content": "Memory without context_type",
                "importance": 0.8,
                "tags": ["test"],
                "project_id": "test-project"
            }
        ]

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="Some task",
            memories=memories
        )

        assert isinstance(context_str, str)

    def test_empty_task_description(self, sample_memories):
        """Should handle empty task description"""
        from memory_system.agent_context import get_context_for_agent

        context_str, memory_ids = get_context_for_agent(
            agent_type="dev",
            task_description="",
            memories=sample_memories
        )

        # Should still work (maybe return corrections or high-importance memories)
        assert isinstance(context_str, str)
        assert isinstance(memory_ids, list)
