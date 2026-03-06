"""
Tests for learnings generator - generates CLAUDE.md learnings section from high-value memories.

Tests the full pipeline: memory selection, deduplication, grouping by domain,
formatting, and CLAUDE.md integration using strip-and-regenerate pattern.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from memory_system.memory_ts_client import Memory, MemoryTSClient
from memory_system.learnings_generator import (
    LearningsGenerator,
    START_MARKER,
    END_MARKER,
)


@pytest.fixture
def memory_dir(tmp_path):
    """Create temporary memory directory"""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def claude_md_path(tmp_path):
    """Create temporary CLAUDE.md"""
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Project instructions\n\nSome existing content.\n")
    return path


@pytest.fixture
def memory_client(memory_dir):
    """Create memory-ts client with temp directory"""
    return MemoryTSClient(memory_dir=memory_dir)


@pytest.fixture
def generator(memory_client, claude_md_path):
    """Create learnings generator with default thresholds"""
    return LearningsGenerator(
        memory_client=memory_client,
        claude_md_path=claude_md_path,
        min_importance=0.7,
        min_confidence=0.7,
    )


def create_memory(
    memory_client,
    content,
    importance=0.8,
    confidence_score=0.8,
    knowledge_domain="learnings",
    context_type="knowledge",
    tags=None,
    status="active",
):
    """Helper: create a memory with given attributes"""
    if tags is None:
        tags = ["#learning"]
    mem = memory_client.create(
        content=content,
        project_id="test-project",
        tags=tags,
        importance=importance,
        context_type=context_type,
        confidence_score=confidence_score,
        knowledge_domain=knowledge_domain,
        status=status,
    )
    return mem


# ============================================================================
# Memory selection tests (4 tests)
# ============================================================================

class TestSelectMemories:
    """Test memory selection criteria for learnings section"""

    def test_importance_threshold_filters(self, generator, memory_client):
        """Memories below min_importance should be excluded"""
        create_memory(memory_client, "High importance", importance=0.9)
        create_memory(memory_client, "At threshold", importance=0.7)
        create_memory(memory_client, "Below threshold", importance=0.6)
        create_memory(memory_client, "Low importance", importance=0.3)

        selected = generator.select_memories()

        contents = [m.content for m in selected]
        assert "High importance" in contents
        assert "At threshold" in contents
        assert "Below threshold" not in contents
        assert "Low importance" not in contents

    def test_confidence_threshold_filters(self, generator, memory_client):
        """Memories below min_confidence should be excluded"""
        create_memory(memory_client, "High confidence", confidence_score=0.9)
        create_memory(memory_client, "At threshold", confidence_score=0.7)
        create_memory(memory_client, "Below threshold", confidence_score=0.6)

        selected = generator.select_memories()

        contents = [m.content for m in selected]
        assert "High confidence" in contents
        assert "At threshold" in contents
        assert "Below threshold" not in contents

    def test_graduated_memories_excluded(self, generator, memory_client):
        """Memories tagged #graduated should be excluded (already in corrections)"""
        create_memory(memory_client, "Normal memory", tags=["#learning"])
        create_memory(
            memory_client,
            "Graduated memory",
            tags=["#learning", "#graduated"],
        )

        selected = generator.select_memories()

        contents = [m.content for m in selected]
        assert "Normal memory" in contents
        assert "Graduated memory" not in contents

    def test_corrections_excluded(self, generator, memory_client):
        """Correction-type memories should be excluded (handled by correction_graduator)"""
        create_memory(memory_client, "Knowledge memory", context_type="knowledge")
        create_memory(memory_client, "Correction memory", context_type="correction")

        selected = generator.select_memories()

        contents = [m.content for m in selected]
        assert "Knowledge memory" in contents
        assert "Correction memory" not in contents


# ============================================================================
# Category grouping tests (4 tests)
# ============================================================================

class TestGroupByCategory:
    """Test grouping memories by knowledge_domain"""

    def test_groups_by_domain(self, generator, memory_client):
        """Memories should be grouped by their knowledge_domain"""
        m1 = create_memory(memory_client, "Pref A", knowledge_domain="preferences")
        m2 = create_memory(memory_client, "Work A", knowledge_domain="workflow")
        m3 = create_memory(memory_client, "Pref B", knowledge_domain="preferences")

        groups = generator.group_by_category([m1, m2, m3])

        assert "preferences" in groups
        assert "workflow" in groups
        assert len(groups["preferences"]) == 2
        assert len(groups["workflow"]) == 1

    def test_unknown_domain_becomes_general(self, generator, memory_client):
        """Memories with no knowledge_domain should go to 'general'"""
        mem = create_memory(memory_client, "No domain memory")
        mem.knowledge_domain = None

        groups = generator.group_by_category([mem])

        assert "general" in groups
        assert len(groups["general"]) == 1

    def test_empty_categories_allowed(self, generator):
        """Empty input produces empty groups"""
        groups = generator.group_by_category([])

        assert groups == {}

    def test_sorted_by_importance_within_group(self, generator, memory_client):
        """Memories within each group should be sorted by importance (highest first)"""
        m1 = create_memory(memory_client, "Low imp", importance=0.7, knowledge_domain="workflow")
        m2 = create_memory(memory_client, "High imp", importance=0.95, knowledge_domain="workflow")
        m3 = create_memory(memory_client, "Mid imp", importance=0.85, knowledge_domain="workflow")

        groups = generator.group_by_category([m1, m2, m3])

        importances = [m.importance for m in groups["workflow"]]
        assert importances == sorted(importances, reverse=True)


# ============================================================================
# Formatting tests (5 tests)
# ============================================================================

class TestFormatting:
    """Test formatting of individual memories and full section"""

    def test_preference_format(self, generator, memory_client):
        """Preference domain should use '**Preference:**' prefix"""
        mem = create_memory(memory_client, "Use dark mode", knowledge_domain="preferences")

        result = generator.format_memory(mem)

        assert result == "- **Preference:** Use dark mode"

    def test_workflow_format(self, generator, memory_client):
        """Workflow domain should use '**Workflow:**' prefix"""
        mem = create_memory(memory_client, "Run tests first", knowledge_domain="workflow")

        result = generator.format_memory(mem)

        assert result == "- **Workflow:** Run tests first"

    def test_technical_format(self, generator, memory_client):
        """Technical domains should use backtick prefix"""
        mem = create_memory(memory_client, "Use pytest fixtures", knowledge_domain="technical")

        result = generator.format_memory(mem)

        assert result == "- `technical`: Use pytest fixtures"

    def test_generic_format(self, generator, memory_client):
        """Unknown domains should use plain bullet"""
        mem = create_memory(memory_client, "Something general", knowledge_domain="misc")

        result = generator.format_memory(mem)

        assert result == "- Something general"

    def test_section_format_has_markers_and_headings(self, generator, memory_client):
        """Full section should have markers, heading, and domain headings"""
        m1 = create_memory(memory_client, "Pref item", knowledge_domain="preferences")
        m2 = create_memory(memory_client, "Tech item", knowledge_domain="technical")

        groups = generator.group_by_category([m1, m2])
        section = generator.format_section(groups)

        assert START_MARKER in section
        assert END_MARKER in section
        assert "### Accumulated learnings" in section
        assert "**Preferences**" in section
        assert "**Technical**" in section

    def test_domain_headings_use_sentence_case(self, generator, memory_client):
        """Domain headings should use sentence case, not title case"""
        m1 = create_memory(memory_client, "Item", knowledge_domain="code_quality")

        groups = generator.group_by_category([m1])
        section = generator.format_section(groups)

        # Sentence case: "Code quality" not "Code Quality"
        assert "**Code quality**" in section
        assert "**Code Quality**" not in section


# ============================================================================
# Deduplication tests (3 tests)
# ============================================================================

class TestDeduplicate:
    """Test near-duplicate removal"""

    def test_exact_duplicates_removed(self, generator, memory_client):
        """Exact duplicate content should be deduplicated"""
        m1 = create_memory(memory_client, "Always run tests before committing", importance=0.8)
        m2 = create_memory(memory_client, "Always run tests before committing", importance=0.7)

        result = generator.deduplicate([m1, m2])

        assert len(result) == 1
        # Should keep the higher importance one
        assert result[0].importance == 0.8

    def test_near_duplicates_removed(self, generator, memory_client):
        """Near-duplicates (same first 200 chars) should be deduplicated"""
        prefix = "A" * 200
        m1 = create_memory(memory_client, prefix + " version one", importance=0.7)
        m2 = create_memory(memory_client, prefix + " version two", importance=0.9)

        result = generator.deduplicate([m1, m2])

        assert len(result) == 1
        assert result[0].importance == 0.9  # kept higher importance

    def test_non_duplicates_preserved(self, generator, memory_client):
        """Distinct memories should all be preserved"""
        m1 = create_memory(memory_client, "First unique memory")
        m2 = create_memory(memory_client, "Second unique memory")
        m3 = create_memory(memory_client, "Third unique memory")

        result = generator.deduplicate([m1, m2, m3])

        assert len(result) == 3


# ============================================================================
# Section generation / CLAUDE.md integration tests (4 tests)
# ============================================================================

class TestSectionGeneration:
    """Test generate() and apply_to_claude_md()"""

    def test_fresh_file_markers_appended(self, generator, memory_client, claude_md_path):
        """CLAUDE.md without markers should get section appended at end"""
        create_memory(memory_client, "Important learning")

        result = generator.apply_to_claude_md()

        assert result["written"] is True
        content = claude_md_path.read_text()
        assert START_MARKER in content
        assert END_MARKER in content
        assert "Important learning" in content
        assert "# Project instructions" in content  # original preserved

    def test_existing_markers_content_replaced(self, generator, memory_client, claude_md_path):
        """CLAUDE.md with existing markers should get content replaced between them"""
        initial = claude_md_path.read_text()
        initial += (
            f"\n{START_MARKER}\n\n*Old learnings content.*\n\n{END_MARKER}\n"
        )
        claude_md_path.write_text(initial)

        create_memory(memory_client, "New learning")

        result = generator.apply_to_claude_md()

        assert result["written"] is True
        content = claude_md_path.read_text()
        assert "New learning" in content
        assert "Old learnings content" not in content

    def test_markers_preserved_in_correct_position(self, generator, memory_client, claude_md_path):
        """After replacement, markers should still be present and well-formed"""
        initial = claude_md_path.read_text()
        initial += (
            f"\n{START_MARKER}\n\n*Old content.*\n\n{END_MARKER}\n\n## Footer\n"
        )
        claude_md_path.write_text(initial)

        create_memory(memory_client, "Replacement learning")

        generator.apply_to_claude_md()

        content = claude_md_path.read_text()
        start_idx = content.index(START_MARKER)
        end_idx = content.index(END_MARKER)
        assert start_idx < end_idx
        assert "## Footer" in content  # content after markers preserved

    def test_dry_run_returns_content_without_writing(self, generator, memory_client, claude_md_path):
        """dry_run=True should return content but not modify CLAUDE.md"""
        original_content = claude_md_path.read_text()
        create_memory(memory_client, "Dry run learning")

        result = generator.apply_to_claude_md(dry_run=True)

        assert result["written"] is False
        assert result["memory_count"] >= 1
        assert START_MARKER in result["content"]
        assert claude_md_path.read_text() == original_content  # file unchanged


# ============================================================================
# CLI / initialization tests (2 tests)
# ============================================================================

class TestInitialization:
    """Test constructor and path configuration"""

    def test_default_claude_md_path(self, memory_dir):
        """Default path is None when MEMORY_SYSTEM_CLAUDE_MD env var is not set"""
        gen = LearningsGenerator(memory_dir=memory_dir)

        # Without env var, default is None (user must configure)
        assert gen.claude_md_path is None

    def test_custom_path_via_argument(self, memory_dir, tmp_path):
        """Custom claude_md_path should override default"""
        custom_path = tmp_path / "custom" / "CLAUDE.md"
        custom_path.parent.mkdir(parents=True)
        custom_path.write_text("# Custom\n")

        gen = LearningsGenerator(
            memory_dir=memory_dir,
            claude_md_path=custom_path,
        )

        assert gen.claude_md_path == custom_path


# ============================================================================
# Edge case tests (2 tests)
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_no_qualifying_memories_message(self, generator):
        """No qualifying memories should produce placeholder message"""
        section = generator.generate()

        assert START_MARKER in section
        assert END_MARKER in section
        assert "No learnings qualifying yet" in section

    def test_claude_md_missing_returns_error(self, memory_client, tmp_path):
        """Missing CLAUDE.md should return error in result dict, not raise"""
        missing_path = tmp_path / "nonexistent" / "CLAUDE.md"
        gen = LearningsGenerator(
            memory_client=memory_client,
            claude_md_path=missing_path,
        )

        # Create a qualifying memory so generate() doesn't short-circuit
        memory_client.create(
            content="Test learning",
            project_id="test-project",
            tags=["#learning"],
            importance=0.9,
            confidence_score=0.9,
            knowledge_domain="learnings",
        )

        result = gen.apply_to_claude_md()

        assert result["written"] is False
        assert "error" in result


# ============================================================================
# Non-interference with corrections block tests (3 tests)
# ============================================================================

class TestNonInterference:
    """Test that learnings block doesn't conflict with corrections block"""

    def test_learnings_markers_differ_from_corrections(self):
        """Learnings markers must be different from corrections markers"""
        from memory_system.correction_graduator import (
            START_MARKER as CORR_START,
            END_MARKER as CORR_END,
        )

        assert START_MARKER != CORR_START
        assert END_MARKER != CORR_END

    def test_preserves_corrections_block(self, generator, memory_client, claude_md_path):
        """Writing learnings should not disturb corrections block"""
        corr_start = "<!-- AUTO-GENERATED: corrections -->"
        corr_end = "<!-- END AUTO-GENERATED: corrections -->"
        initial = claude_md_path.read_text()
        initial += (
            f"\n{corr_start}\n## Learned corrections\n\n"
            f"- Always use sentence case\n{corr_end}\n"
        )
        claude_md_path.write_text(initial)

        create_memory(memory_client, "New learning item")
        generator.apply_to_claude_md()

        content = claude_md_path.read_text()
        # Corrections block must still be intact
        assert corr_start in content
        assert corr_end in content
        assert "- Always use sentence case" in content
        # Learnings block also present
        assert START_MARKER in content
        assert END_MARKER in content
        assert "New learning item" in content

    def test_both_blocks_can_coexist(self, generator, memory_client, claude_md_path):
        """Both corrections and learnings blocks should coexist without corruption"""
        corr_start = "<!-- AUTO-GENERATED: corrections -->"
        corr_end = "<!-- END AUTO-GENERATED: corrections -->"

        initial = (
            "# Project instructions\n\n"
            f"{corr_start}\n## Learned corrections\n\n"
            f"- Correction A\n{corr_end}\n\n"
            f"{START_MARKER}\n\n*Old learnings.*\n\n{END_MARKER}\n"
        )
        claude_md_path.write_text(initial)

        create_memory(memory_client, "Updated learning")
        generator.apply_to_claude_md()

        content = claude_md_path.read_text()
        # Both blocks present
        assert corr_start in content
        assert corr_end in content
        assert START_MARKER in content
        assert END_MARKER in content
        # Corrections untouched
        assert "- Correction A" in content
        # Learnings updated
        assert "Updated learning" in content
        assert "Old learnings" not in content


# ============================================================================
# Inactive status test (1 test)
# ============================================================================

class TestInactiveStatus:
    """Test that only active memories are selected"""

    def test_inactive_memories_excluded(self, generator, memory_client):
        """Memories with status != 'active' should be excluded"""
        create_memory(memory_client, "Active memory", status="active")
        create_memory(memory_client, "Archived memory", status="archived")

        selected = generator.select_memories()

        contents = [m.content for m in selected]
        assert "Active memory" in contents
        assert "Archived memory" not in contents


# ============================================================================
# Performance / correctness tests (2 tests)
# ============================================================================

class TestPerformance:
    """Test that apply_to_claude_md doesn't do redundant work"""

    def test_apply_does_not_double_select(self, generator, memory_client, claude_md_path):
        """apply_to_claude_md should call select_memories once, not twice"""
        create_memory(memory_client, "Test memory")

        original_select = generator.select_memories
        call_count = [0]

        def counting_select():
            call_count[0] += 1
            return original_select()

        generator.select_memories = counting_select
        generator.apply_to_claude_md()

        assert call_count[0] == 1, f"select_memories called {call_count[0]} times, expected 1"
