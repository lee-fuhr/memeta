"""
Tests for correction graduator - graduates confirmed corrections to CLAUDE.md rules

Tests graduation pipeline: finding candidates, formatting rules, updating CLAUDE.md,
and marking memories as graduated. Uses strip-and-regenerate pattern for idempotency.
"""

import pytest
from pathlib import Path

from memory_system.memory_ts_client import MemoryTSClient
from memory_system.correction_graduator import CorrectionGraduator


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
def graduator(memory_client, claude_md_path):
    """Create correction graduator"""
    return CorrectionGraduator(
        memory_client=memory_client,
        claude_md_path=claude_md_path,
        graduation_threshold=3,
    )


def create_correction(memory_client, content, confirmations=3, tags=None, context_type="correction"):
    """Helper: create a correction memory with given confirmations"""
    if tags is None:
        tags = ["#correction"]
    mem = memory_client.create(
        content=content,
        project_id="LFI",
        tags=tags,
        importance=0.8,
        context_type=context_type,
        confirmations=confirmations,
    )
    return mem


# ============================================================================
# find_graduation_candidates tests
# ============================================================================

class TestFindCandidates:
    """Test finding correction memories eligible for graduation"""

    def test_find_candidates_returns_eligible(self, graduator, memory_client):
        """Corrections with confirmations >= 3 should be returned"""
        create_correction(memory_client, "Always use sentence case", confirmations=3)
        create_correction(memory_client, "Never use title case", confirmations=4)
        create_correction(memory_client, "Prefer imperative mood", confirmations=5)

        candidates = graduator.find_graduation_candidates()

        assert len(candidates) == 3

    def test_find_candidates_excludes_low_confirmations(self, graduator, memory_client):
        """Corrections with confirmations < 3 should not be returned"""
        create_correction(memory_client, "Almost there", confirmations=2)
        create_correction(memory_client, "Just started", confirmations=1)
        create_correction(memory_client, "No confirmations", confirmations=0)

        candidates = graduator.find_graduation_candidates()

        assert len(candidates) == 0

    def test_find_candidates_excludes_already_graduated(self, graduator, memory_client):
        """Corrections with #graduated tag should be excluded"""
        create_correction(
            memory_client,
            "Already graduated rule",
            confirmations=5,
            tags=["#correction", "#graduated"],
        )

        candidates = graduator.find_graduation_candidates()

        assert len(candidates) == 0

    def test_find_candidates_excludes_non_corrections(self, graduator, memory_client):
        """Non-correction memories should be excluded even with high confirmations"""
        create_correction(
            memory_client,
            "General knowledge fact",
            confirmations=5,
            context_type="knowledge",
        )

        candidates = graduator.find_graduation_candidates()

        assert len(candidates) == 0

    def test_find_candidates_empty_when_none(self, graduator):
        """No correction memories at all returns empty list"""
        candidates = graduator.find_graduation_candidates()

        assert candidates == []


# ============================================================================
# format_rules tests
# ============================================================================

class TestFormatRules:
    """Test formatting graduated memories as imperative rules"""

    def test_format_rules_imperative(self, graduator, memory_client):
        """Should format as bulleted imperative rules"""
        mem1 = create_correction(memory_client, "Always use sentence case")
        mem2 = create_correction(memory_client, "Never use title case")

        result = graduator.format_rules([mem1, mem2])

        assert "- Always use sentence case" in result
        assert "- Never use title case" in result

    def test_format_rules_strips_correction_prefix(self, graduator, memory_client):
        """Should strip 'Correction: ' prefix from content"""
        mem = create_correction(memory_client, "Correction: use sentence case for titles")

        result = graduator.format_rules([mem])

        assert "Correction: " not in result
        assert "- Use sentence case for titles" in result

    def test_format_rules_includes_markers(self, graduator, memory_client):
        """Output should have AUTO-GENERATED markers"""
        mem = create_correction(memory_client, "Always use sentence case")

        result = graduator.format_rules([mem])

        assert "<!-- AUTO-GENERATED: corrections -->" in result
        assert "<!-- END AUTO-GENERATED: corrections -->" in result

    def test_format_rules_empty_list(self, graduator):
        """Empty input should return just the markers with no rules"""
        result = graduator.format_rules([])

        assert "<!-- AUTO-GENERATED: corrections -->" in result
        assert "<!-- END AUTO-GENERATED: corrections -->" in result
        assert "## Learned corrections" in result

    def test_format_rules_categorize_false_ignored(self, graduator, memory_client):
        """categorize=False should be the default and have no effect"""
        mem = create_correction(memory_client, "Always use sentence case")

        result_default = graduator.format_rules([mem])
        result_explicit = graduator.format_rules([mem], categorize=False)

        assert result_default == result_explicit


# ============================================================================
# update_claude_md tests
# ============================================================================

class TestUpdateClaudeMd:
    """Test updating CLAUDE.md with graduated corrections"""

    def test_update_claude_md_inserts_block(self, graduator, claude_md_path, memory_client):
        """CLAUDE.md without markers should get block appended"""
        mem = create_correction(memory_client, "Always use sentence case")
        rules_content = graduator.format_rules([mem])

        result = graduator.update_claude_md(rules_content)

        assert result is True
        content = claude_md_path.read_text()
        assert "<!-- AUTO-GENERATED: corrections -->" in content
        assert "- Always use sentence case" in content
        assert "# Project instructions" in content  # original preserved

    def test_update_claude_md_replaces_existing(self, graduator, claude_md_path, memory_client):
        """CLAUDE.md with old markers should get stripped and regenerated"""
        # Write initial markers block
        initial = claude_md_path.read_text()
        initial += "\n<!-- AUTO-GENERATED: corrections -->\n## Learned corrections\n\n- Old rule\n<!-- END AUTO-GENERATED: corrections -->\n"
        claude_md_path.write_text(initial)

        mem = create_correction(memory_client, "New replacement rule")
        rules_content = graduator.format_rules([mem])

        result = graduator.update_claude_md(rules_content)

        assert result is True
        content = claude_md_path.read_text()
        assert "- New replacement rule" in content
        assert "- Old rule" not in content

    def test_update_claude_md_idempotent(self, graduator, claude_md_path, memory_client):
        """Calling twice with same content should produce same file"""
        mem = create_correction(memory_client, "Always use sentence case")
        rules_content = graduator.format_rules([mem])

        graduator.update_claude_md(rules_content)
        content_after_first = claude_md_path.read_text()

        graduator.update_claude_md(rules_content)
        content_after_second = claude_md_path.read_text()

        assert content_after_first == content_after_second

    def test_update_claude_md_preserves_surrounding(self, graduator, claude_md_path, memory_client):
        """Content before and after markers should be preserved"""
        before = "# Project instructions\n\nSome existing content.\n"
        after = "\n## Other section\n\nMore content here.\n"
        markers = "\n<!-- AUTO-GENERATED: corrections -->\n## Learned corrections\n\n- Old rule\n<!-- END AUTO-GENERATED: corrections -->\n"
        claude_md_path.write_text(before + markers + after)

        mem = create_correction(memory_client, "Updated rule")
        rules_content = graduator.format_rules([mem])

        graduator.update_claude_md(rules_content)

        content = claude_md_path.read_text()
        assert "# Project instructions" in content
        assert "Some existing content." in content
        assert "## Other section" in content
        assert "More content here." in content
        assert "- Updated rule" in content


# ============================================================================
# mark_graduated tests
# ============================================================================

class TestMarkGraduated:
    """Test marking memories with #graduated tag"""

    def test_mark_graduated_adds_tag(self, graduator, memory_client):
        """#graduated should be added to each memory"""
        mem1 = create_correction(memory_client, "Rule one")
        mem2 = create_correction(memory_client, "Rule two")

        graduator.mark_graduated([mem1, mem2])

        updated1 = memory_client.get(mem1.id)
        updated2 = memory_client.get(mem2.id)
        assert "#graduated" in updated1.tags
        assert "#graduated" in updated2.tags

    def test_mark_graduated_count(self, graduator, memory_client):
        """Should return correct count of memories tagged"""
        mem1 = create_correction(memory_client, "Rule one")
        mem2 = create_correction(memory_client, "Rule two")
        mem3 = create_correction(memory_client, "Rule three")

        count = graduator.mark_graduated([mem1, mem2, mem3])

        assert count == 3

    def test_mark_graduated_idempotent(self, graduator, memory_client):
        """Already graduated memories should not get double-tagged"""
        mem = create_correction(
            memory_client,
            "Already graduated",
            tags=["#correction", "#graduated"],
        )

        count = graduator.mark_graduated([mem])

        updated = memory_client.get(mem.id)
        graduated_count = updated.tags.count("#graduated")
        assert graduated_count == 1
        assert count == 0  # nothing new to graduate


# ============================================================================
# graduate (full pipeline) tests
# ============================================================================

class TestGraduateFullPipeline:
    """Test the end-to-end graduation pipeline"""

    def test_graduate_full_pipeline(self, graduator, memory_client, claude_md_path):
        """End-to-end: create corrections, run graduate(), verify CLAUDE.md and tags"""
        create_correction(memory_client, "Always use sentence case", confirmations=3)
        create_correction(memory_client, "Never use title case", confirmations=4)

        result = graduator.graduate()

        assert result["candidates_found"] == 2
        assert result["rules_written"] == 2
        assert result["claude_md_updated"] is True

        # Verify CLAUDE.md has the rules
        content = claude_md_path.read_text()
        assert "- Always use sentence case" in content
        assert "- Never use title case" in content

        # Verify memories are tagged graduated
        all_memories = memory_client.list()
        for mem in all_memories:
            if mem.context_type == "correction" and mem.confirmations >= 3:
                assert "#graduated" in mem.tags

    def test_graduate_no_candidates(self, graduator, claude_md_path):
        """No eligible memories should result in no changes"""
        original = claude_md_path.read_text()

        result = graduator.graduate()

        assert result["candidates_found"] == 0
        assert result["rules_written"] == 0
        assert result["claude_md_updated"] is False
        assert claude_md_path.read_text() == original

    def test_graduate_mixed(self, graduator, memory_client, claude_md_path):
        """Some eligible, some not - only eligible should graduate.
        Previously graduated rules are preserved in the regenerated block."""
        create_correction(memory_client, "Eligible rule", confirmations=3)
        create_correction(memory_client, "Not enough confirmations", confirmations=2)
        create_correction(
            memory_client,
            "Already graduated",
            confirmations=5,
            tags=["#correction", "#graduated"],
        )

        result = graduator.graduate()

        assert result["candidates_found"] == 1
        # rules_written includes both new candidates AND previously graduated
        assert result["rules_written"] == 2
        assert result["claude_md_updated"] is True

        content = claude_md_path.read_text()
        assert "- Eligible rule" in content
        assert "- Already graduated" in content  # previously graduated preserved
        assert "Not enough confirmations" not in content

    def test_graduate_preserves_previous_across_runs(self, graduator, memory_client, claude_md_path):
        """Graduate once, graduate again — first batch must still be in CLAUDE.md.
        This is the critical strip-and-regenerate safety test."""
        # First graduation: two corrections
        create_correction(memory_client, "First batch rule A", confirmations=3)
        create_correction(memory_client, "First batch rule B", confirmations=4)

        result1 = graduator.graduate()
        assert result1["candidates_found"] == 2
        assert result1["rules_written"] == 2
        assert result1["claude_md_updated"] is True

        # Verify both rules present
        content = claude_md_path.read_text()
        assert "- First batch rule A" in content
        assert "- First batch rule B" in content

        # Second graduation: one new correction
        create_correction(memory_client, "Second batch rule C", confirmations=5)

        result2 = graduator.graduate()
        assert result2["candidates_found"] == 1
        # All three rules now (2 previously graduated + 1 new)
        assert result2["rules_written"] == 3
        assert result2["claude_md_updated"] is True

        # All three rules must be present in CLAUDE.md
        content = claude_md_path.read_text()
        assert "- First batch rule A" in content
        assert "- First batch rule B" in content
        assert "- Second batch rule C" in content
