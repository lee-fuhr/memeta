"""
Tests for extraction_patterns.py — correction detection and boost logic

Testing:
- detect_corrections() function (new detection-only seam)
- New correction patterns (behavioral directives, frustration signals)
- Updated correction boost (1.5x with 0.9 floor)
- Backward compatibility with extract_memories_patterns
"""

import pytest
from memory_system.extraction_patterns import (
    detect_corrections,
    extract_memories_patterns,
    CORRECTION_PATTERNS,
    calculate_importance,
)


def _memory_factory(content, importance, project_id):
    """Simple memory factory for testing extract_memories_patterns."""
    return {
        "content": content,
        "importance": importance,
        "project_id": project_id,
    }


class TestDetectCorrectionsAlwaysNever:
    """Test behavioral directive detection (always/never patterns)"""

    def test_detect_corrections_always_directive(self):
        """'always use sentence case for headings.' detected as behavioral_directive"""
        conversation = "user: always use sentence case for headings."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "behavioral_directive"), None
        )
        assert match is not None
        assert match["importance"] >= 0.9

    def test_detect_corrections_never_directive(self):
        """'never use title case.' detected as behavioral_directive"""
        conversation = "user: never use title case for file names."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "behavioral_directive"), None
        )
        assert match is not None
        assert match["importance"] >= 0.9


class TestDetectCorrectionsFrustration:
    """Test frustration signal detection"""

    def test_detect_corrections_i_told_you(self):
        """'I told you to use sentence case.' detected as frustration_signal"""
        conversation = "user: I told you to use sentence case."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "frustration_signal"), None
        )
        assert match is not None

    def test_detect_corrections_stop_doing(self):
        """'stop doing that.' detected as frustration_signal"""
        conversation = "user: stop doing that thing with the formatting."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "frustration_signal"), None
        )
        assert match is not None

    def test_detect_corrections_for_nth_time(self):
        """'for the third time, use lowercase.' detected as frustration_signal"""
        conversation = "user: for the third time, use lowercase."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "frustration_signal"), None
        )
        assert match is not None


class TestDetectCorrectionsExistingAndEdge:
    """Test existing patterns still work and edge cases"""

    def test_detect_corrections_existing_patterns_still_work(self):
        """'actually it should be lowercase.' still detected"""
        conversation = "user: actually it should be lowercase and not uppercase."
        results = detect_corrections(conversation)
        assert len(results) >= 1
        match = next(
            (r for r in results if r["pattern_type"] == "explicit_correction"), None
        )
        assert match is not None

    def test_detect_corrections_empty_conversation(self):
        """Empty conversation returns empty list"""
        results = detect_corrections("")
        assert results == []

    def test_detect_corrections_no_corrections(self):
        """Normal conversation with no corrections returns empty list"""
        conversation = (
            "user: Can you help me with this task?\n"
            "assistant: Sure, what do you need?\n"
            "user: I need to write a function.\n"
        )
        results = detect_corrections(conversation)
        assert results == []


class TestCorrectionBoost:
    """Test updated correction importance boost (1.5x, floor 0.9, cap 1.0)"""

    def test_correction_boost_is_1_5x(self):
        """Corrections now get 1.5x boost"""
        # Build a conversation with a correction that has known base importance
        # "actually it should be" triggers existing CORRECTION_PATTERNS
        conversation = (
            "user: actually it should be using the production-critical "
            "pattern across multiple clients for the universal approach."
        )
        memories = extract_memories_patterns(
            conversation, "test-project", _memory_factory
        )
        # Find correction memory
        correction_mems = [m for m in memories if m["content"].startswith("Correction:")]
        if correction_mems:
            mem = correction_mems[0]
            # The content after "Correction: " is the raw text
            raw_content = mem["content"].replace("Correction: ", "")
            base = calculate_importance(raw_content)
            # Boost should be 1.5x (not old 1.2x), capped at 1.0, floor 0.9
            expected = max(0.9, min(1.0, base * 1.5))
            assert abs(mem["importance"] - expected) < 0.001

    def test_correction_importance_floor_0_9(self):
        """Corrections never go below 0.9 importance"""
        # Even with low base importance, corrections should have floor of 0.9
        conversation = (
            "user: actually it should be the simple thing where you "
            "just do the basic update to the regular file format."
        )
        memories = extract_memories_patterns(
            conversation, "test-project", _memory_factory
        )
        correction_mems = [m for m in memories if m["content"].startswith("Correction:")]
        for mem in correction_mems:
            assert mem["importance"] >= 0.9

    def test_correction_importance_cap_1_0(self):
        """Corrections capped at 1.0"""
        # Even high-importance correction content should cap at 1.0
        conversation = (
            "user: actually it should be the CRITICAL URGENT production "
            "pattern across multiple clients that broke the universal system."
        )
        memories = extract_memories_patterns(
            conversation, "test-project", _memory_factory
        )
        correction_mems = [m for m in memories if m["content"].startswith("Correction:")]
        for mem in correction_mems:
            assert mem["importance"] <= 1.0

    def test_extract_memories_patterns_corrections_boosted(self):
        """extract_memories_patterns still works but with new 1.5x boost"""
        conversation = (
            "user: actually it should be using the better approach where "
            "we apply the pattern across all the different client projects."
        )
        memories = extract_memories_patterns(
            conversation, "test-project", _memory_factory
        )
        # Should still produce memories (backward compatibility)
        assert isinstance(memories, list)
        # If corrections found, they should have boosted importance
        correction_mems = [m for m in memories if m["content"].startswith("Correction:")]
        for mem in correction_mems:
            # With 1.5x boost and 0.9 floor, importance should be >= 0.9
            assert mem["importance"] >= 0.9
