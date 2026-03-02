"""
Tests for CLAUDE.md synthesizer - auto-generates rules from 5 signal sources.

Tests rule extraction from corrections, directives, frustrations, preferences,
and workflows. Tests deduplication, formatting, CLAUDE.md update (strip-and-regenerate),
and the full synthesize pipeline.
"""

import pytest
from pathlib import Path

from memory_system.memory_ts_client import MemoryTSClient, Memory
from memory_system.claudemd_synthesizer import (
    Rule,
    CorrectionRuleSource,
    DirectiveRuleSource,
    FrustrationRuleSource,
    PreferenceRuleSource,
    WorkflowRuleSource,
    CLAUDEMDSynthesizer,
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


def create_memory(memory_client, content, context_type="knowledge",
                  confirmations=0, tags=None, importance=0.8):
    """Helper: create a memory with given attributes"""
    if tags is None:
        tags = []
    return memory_client.create(
        content=content,
        project_id="test",
        tags=tags,
        importance=importance,
        context_type=context_type,
        confirmations=confirmations,
    )


# ============================================================================
# CorrectionRuleSource tests
# ============================================================================

class TestCorrectionRuleSource:
    """Test extracting rules from graduation candidates"""

    def test_extracts_rules_from_graduation_candidates(self, memory_dir, memory_client):
        """Corrections with enough confirmations become rules"""
        create_memory(memory_client, "Always use sentence case",
                      context_type="correction", confirmations=3, tags=["#correction"])
        create_memory(memory_client, "Never use title case",
                      context_type="correction", confirmations=4, tags=["#correction"])

        source = CorrectionRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 2
        assert all(r.category == "correction" for r in rules)
        assert all(r.source_type == "CorrectionRuleSource" for r in rules)

    def test_empty_candidates_returns_empty(self, memory_dir):
        """No graduation candidates returns empty list"""
        source = CorrectionRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert rules == []

    def test_confidence_derived_from_confirmations(self, memory_dir, memory_client):
        """Higher confirmations should produce higher confidence"""
        create_memory(memory_client, "Low confirmations rule",
                      context_type="correction", confirmations=3, tags=["#correction"])
        create_memory(memory_client, "High confirmations rule",
                      context_type="correction", confirmations=10, tags=["#correction"])

        source = CorrectionRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        low = [r for r in rules if "Low" in r.text][0]
        high = [r for r in rules if "High" in r.text][0]
        assert high.confidence > low.confidence


# ============================================================================
# DirectiveRuleSource tests
# ============================================================================

class TestDirectiveRuleSource:
    """Test extracting directive rules from memories"""

    def test_detects_directive_patterns(self, memory_dir, memory_client):
        """Memories containing 'always', 'never', 'must', 'don't' are directives"""
        create_memory(memory_client, "Always use sentence case",
                      context_type="directive", confirmations=1, tags=["#directive"])
        create_memory(memory_client, "Never skip tests",
                      context_type="behavioral", confirmations=1, tags=["#behavioral"])
        create_memory(memory_client, "Must validate inputs",
                      context_type="directive", confirmations=1, tags=["#directive"])

        source = DirectiveRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 3
        assert all(r.category == "directive" for r in rules)

    def test_skips_non_directive_memories(self, memory_dir, memory_client):
        """Memories without directive patterns are skipped"""
        create_memory(memory_client, "The sky is blue",
                      context_type="knowledge", confirmations=1, tags=["#knowledge"])

        source = DirectiveRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 0


# ============================================================================
# FrustrationRuleSource tests
# ============================================================================

class TestFrustrationRuleSource:
    """Test extracting rules from frustration patterns"""

    def test_requires_five_plus_confirmations(self, memory_dir, memory_client):
        """Only frustrations with 5+ confirmations become rules"""
        create_memory(memory_client, "Stop using title case",
                      context_type="frustration", confirmations=5,
                      tags=["#frustration"])
        create_memory(memory_client, "Don't add emojis",
                      context_type="correction", confirmations=6,
                      tags=["#frustration"])

        source = FrustrationRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 2
        assert all(r.category == "frustration" for r in rules)

    def test_below_threshold_no_rules(self, memory_dir, memory_client):
        """Frustrations with fewer than 5 confirmations are excluded"""
        create_memory(memory_client, "Minor annoyance",
                      context_type="frustration", confirmations=4,
                      tags=["#frustration"])
        create_memory(memory_client, "Barely noticed",
                      context_type="frustration", confirmations=1,
                      tags=["#frustration"])

        source = FrustrationRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 0


# ============================================================================
# PreferenceRuleSource tests
# ============================================================================

class TestPreferenceRuleSource:
    """Test extracting rules from preference memories"""

    def test_extracts_preferences_with_three_plus_confirmations(self, memory_dir, memory_client):
        """Preferences with 3+ confirmations become rules"""
        create_memory(memory_client, "Use dark mode for all editors",
                      context_type="preference", confirmations=3,
                      tags=["#preference"])
        create_memory(memory_client, "Prefer concise responses",
                      context_type="preference", confirmations=5,
                      tags=["#preference"])

        source = PreferenceRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 2
        assert all(r.category == "preference" for r in rules)

    def test_filters_by_context_type(self, memory_dir, memory_client):
        """Only context_type=='preference' memories are extracted"""
        create_memory(memory_client, "This is knowledge",
                      context_type="knowledge", confirmations=5,
                      tags=["#knowledge"])
        create_memory(memory_client, "This is a preference",
                      context_type="preference", confirmations=3,
                      tags=["#preference"])

        source = PreferenceRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 1
        assert rules[0].text == "This is a preference"


# ============================================================================
# WorkflowRuleSource tests
# ============================================================================

class TestWorkflowRuleSource:
    """Test extracting rules from workflow memories"""

    def test_extracts_workflows_with_three_plus_confirmations(self, memory_dir, memory_client):
        """Workflows with 3+ confirmations become rules"""
        create_memory(memory_client, "Run tests before committing",
                      context_type="workflow", confirmations=3,
                      tags=["#workflow"])
        create_memory(memory_client, "Use TDD for new features",
                      context_type="workflow", confirmations=4,
                      tags=["#workflow"])

        source = WorkflowRuleSource(memory_dir=memory_dir)
        rules = source.extract_rules()

        assert len(rules) == 2
        assert all(r.category == "workflow" for r in rules)


# ============================================================================
# Deduplication tests
# ============================================================================

class TestDeduplication:
    """Test near-duplicate rule removal"""

    def test_removes_high_overlap_rules(self, claude_md_path):
        """Rules with >0.7 word overlap should be deduplicated"""
        rules = [
            Rule(text="Always use sentence case for headings",
                 category="correction", confidence=0.8,
                 source_count=1, source_type="CorrectionRuleSource"),
            Rule(text="Always use sentence case for all headings",
                 category="directive", confidence=0.6,
                 source_count=1, source_type="DirectiveRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        deduped = synth.deduplicate(rules)

        assert len(deduped) == 1

    def test_keeps_higher_confidence_version(self, claude_md_path):
        """When deduplicating, the higher confidence rule survives"""
        rules = [
            Rule(text="Always use sentence case for headings",
                 category="correction", confidence=0.8,
                 source_count=1, source_type="CorrectionRuleSource"),
            Rule(text="Always use sentence case for all headings",
                 category="directive", confidence=0.6,
                 source_count=1, source_type="DirectiveRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        deduped = synth.deduplicate(rules)

        assert deduped[0].confidence == 0.8

    def test_distinct_rules_preserved(self, claude_md_path):
        """Rules with low overlap should all be preserved"""
        rules = [
            Rule(text="Always use sentence case",
                 category="correction", confidence=0.8,
                 source_count=1, source_type="CorrectionRuleSource"),
            Rule(text="Run tests before committing code",
                 category="workflow", confidence=0.7,
                 source_count=1, source_type="WorkflowRuleSource"),
            Rule(text="Prefer dark mode for all editors",
                 category="preference", confidence=0.6,
                 source_count=1, source_type="PreferenceRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        deduped = synth.deduplicate(rules)

        assert len(deduped) == 3

    def test_all_duplicates_single_rule(self, claude_md_path):
        """Multiple near-identical rules collapse to one"""
        rules = [
            Rule(text="use sentence case for headings and titles",
                 category="correction", confidence=0.9,
                 source_count=1, source_type="CorrectionRuleSource"),
            Rule(text="use sentence case for all headings and titles",
                 category="directive", confidence=0.7,
                 source_count=1, source_type="DirectiveRuleSource"),
            Rule(text="use sentence case for headings titles",
                 category="frustration", confidence=0.5,
                 source_count=1, source_type="FrustrationRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        deduped = synth.deduplicate(rules)

        assert len(deduped) == 1
        assert deduped[0].confidence == 0.9


# ============================================================================
# Format rules tests
# ============================================================================

class TestFormatRules:
    """Test formatting rules as markdown"""

    def test_groups_by_category(self, claude_md_path):
        """Rules should be grouped under category headings"""
        rules = [
            Rule(text="Always use sentence case", category="correction",
                 confidence=0.8, source_count=1, source_type="CorrectionRuleSource"),
            Rule(text="Run tests first", category="workflow",
                 confidence=0.7, source_count=1, source_type="WorkflowRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        output = synth.format_rules(rules)

        assert "### Correction" in output
        assert "### Workflow" in output

    def test_empty_rules_empty_string(self, claude_md_path):
        """No rules produces empty string"""
        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        output = synth.format_rules([])

        assert output == ""

    def test_includes_confidence_indicator(self, claude_md_path):
        """Each rule should show a confidence indicator"""
        rules = [
            Rule(text="Always use sentence case", category="correction",
                 confidence=0.9, source_count=1, source_type="CorrectionRuleSource"),
        ]

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        output = synth.format_rules(rules)

        # Should contain some confidence info (exact format flexible)
        assert "Always use sentence case" in output
        # Confidence shown as percentage or stars or similar
        assert "90%" in output or "0.9" in output


# ============================================================================
# Update CLAUDE.md tests
# ============================================================================

class TestUpdateClaudeMd:
    """Test strip-and-regenerate for CLAUDE.md"""

    def test_strip_and_regenerate_idempotent(self, claude_md_path):
        """Calling update twice with same content produces same file"""
        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        content = "### Correction\n\n- Always use sentence case (90%)\n"

        synth.update_claude_md(content)
        after_first = claude_md_path.read_text()

        synth.update_claude_md(content)
        after_second = claude_md_path.read_text()

        assert after_first == after_second

    def test_appends_markers_if_missing(self, claude_md_path):
        """If no markers exist, append them at end of file"""
        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        content = "### Correction\n\n- Always use sentence case (90%)\n"

        result = synth.update_claude_md(content)

        assert result is True
        file_content = claude_md_path.read_text()
        assert "<!-- AUTO-GENERATED: learnings -->" in file_content
        assert "<!-- END AUTO-GENERATED: learnings -->" in file_content
        assert "# Project instructions" in file_content

    def test_preserves_content_outside_markers(self, claude_md_path):
        """Content before and after markers should be preserved"""
        before = "# Project instructions\n\nSome existing content.\n"
        markers = ("\n<!-- AUTO-GENERATED: learnings -->\n"
                   "### Old\n\n- Old rule\n"
                   "<!-- END AUTO-GENERATED: learnings -->\n")
        after = "\n## Other section\n\nMore content here.\n"
        claude_md_path.write_text(before + markers + after)

        synth = CLAUDEMDSynthesizer(sources=[], claude_md_path=claude_md_path)
        new_content = "### Correction\n\n- New rule (90%)\n"

        synth.update_claude_md(new_content)

        file_content = claude_md_path.read_text()
        assert "# Project instructions" in file_content
        assert "Some existing content." in file_content
        assert "## Other section" in file_content
        assert "More content here." in file_content
        assert "- New rule (90%)" in file_content
        assert "- Old rule" not in file_content


# ============================================================================
# Synthesize (full pipeline) tests
# ============================================================================

class TestSynthesize:
    """Test the full synthesis pipeline"""

    def test_full_pipeline_integration(self, memory_dir, memory_client, claude_md_path):
        """End-to-end: sources produce rules, dedup, format, update file"""
        create_memory(memory_client, "Always use sentence case",
                      context_type="correction", confirmations=3,
                      tags=["#correction"])
        create_memory(memory_client, "Prefer dark mode",
                      context_type="preference", confirmations=3,
                      tags=["#preference"])

        sources = [
            CorrectionRuleSource(memory_dir=memory_dir),
            PreferenceRuleSource(memory_dir=memory_dir),
        ]
        synth = CLAUDEMDSynthesizer(sources=sources, claude_md_path=claude_md_path)
        result = synth.synthesize()

        assert result["rules_count"] >= 2
        assert result["updated"] is True
        assert "correction" in result["categories"]
        assert "preference" in result["categories"]

        file_content = claude_md_path.read_text()
        assert "<!-- AUTO-GENERATED: learnings -->" in file_content
        assert "Always use sentence case" in file_content
        assert "Prefer dark mode" in file_content

    def test_empty_sources_no_update(self, memory_dir, claude_md_path):
        """No rules from any source means no file update"""
        sources = [
            CorrectionRuleSource(memory_dir=memory_dir),
            PreferenceRuleSource(memory_dir=memory_dir),
        ]
        synth = CLAUDEMDSynthesizer(sources=sources, claude_md_path=claude_md_path)
        original = claude_md_path.read_text()

        result = synth.synthesize()

        assert result["rules_count"] == 0
        assert result["updated"] is False
        assert claude_md_path.read_text() == original
