"""
Tests for emotional tagging and flashbulb prioritization

Tests the heuristic emotional analysis of session context:
- Valence detection (-1.0 to +1.0)
- Arousal detection (0.0 to 1.0)
- Signal identification (what triggered the emotional tag)
- Flashbulb memory identification (high-arousal memories)
- Decay multiplier calculation
- Emotional distribution statistics
- Database persistence and retrieval

Based on Brown & Kulik (1977) flashbulb memory + McGaugh (2004)
amygdala-mediated consolidation.
"""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta

from memory_system.emotional_tagging import EmotionalTagger, EmotionalTag


@pytest.fixture
def db_path():
    """Create a temporary database path for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tagger(db_path):
    """Create an EmotionalTagger with a temporary database."""
    return EmotionalTagger(db_path=db_path)


def _msgs(*contents):
    """Helper: create message dicts from strings."""
    return [{"content": c} for c in contents]


# ── Test class: exclamation mark arousal ──────────────────────────────────


class TestExclamationArousal:
    """Exclamation marks should increase arousal by +0.1 each, cap 0.5."""

    def test_single_exclamation(self, tagger):
        result = tagger.analyze_context(_msgs("It works!"))
        assert result["arousal"] >= 0.1

    def test_multiple_exclamations(self, tagger):
        result = tagger.analyze_context(_msgs("Wow!!! Amazing!!!"))
        # 6 exclamation marks * 0.1 = 0.6, but capped at 0.5
        assert result["arousal"] >= 0.5
        assert "exclamation_marks" in result["signals"]

    def test_exclamation_cap(self, tagger):
        result = tagger.analyze_context(_msgs("!" * 20))
        # Should not exceed the cap contribution from exclamation marks alone
        assert result["arousal"] <= 1.0


# ── Test class: ALL CAPS arousal ──────────────────────────────────────────


class TestAllCapsArousal:
    """ALL CAPS words add +0.15 arousal each, cap 0.5."""

    def test_single_caps_word(self, tagger):
        result = tagger.analyze_context(_msgs("This is BROKEN"))
        assert result["arousal"] >= 0.15

    def test_multiple_caps_words(self, tagger):
        result = tagger.analyze_context(_msgs("THIS IS TOTALLY BROKEN NOW"))
        # 5 caps words * 0.15 = 0.75, capped at 0.5 for this signal
        assert result["arousal"] >= 0.5
        assert "all_caps_words" in result["signals"]

    def test_short_caps_ignored(self, tagger):
        """Single-char caps like 'I' or 'A' should not count."""
        result = tagger.analyze_context(_msgs("I am A person"))
        # 'I' and 'A' are too short to count as ALL CAPS emphasis
        assert result["arousal"] < 0.15 or "all_caps_words" not in result["signals"]


# ── Test class: frustration keywords ──────────────────────────────────────


class TestFrustrationKeywords:
    """Frustration keywords: +0.3 arousal, -0.5 valence."""

    def test_bug_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("There's a bug in the parser"))
        assert result["arousal"] >= 0.3
        assert result["valence"] < 0.0
        assert "frustration_keywords" in result["signals"]

    def test_error_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Getting an error on line 42"))
        assert result["arousal"] >= 0.3
        assert result["valence"] < 0.0

    def test_crash_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("The server keeps crashing"))
        assert result["arousal"] >= 0.3
        assert result["valence"] < 0.0

    def test_broken_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Everything is broken"))
        assert result["arousal"] >= 0.3
        assert result["valence"] < 0.0

    def test_failed_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("The deploy failed again"))
        assert result["arousal"] >= 0.3
        assert result["valence"] < 0.0


# ── Test class: success keywords ──────────────────────────────────────────


class TestSuccessKeywords:
    """Success keywords: +0.3 arousal, +0.7 valence."""

    def test_works_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("It works!"))
        assert result["arousal"] >= 0.3
        assert result["valence"] > 0.0
        assert "success_keywords" in result["signals"]

    def test_finally_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Finally got it working"))
        assert result["arousal"] >= 0.3
        assert result["valence"] > 0.0

    def test_solved_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Solved the memory leak"))
        assert result["arousal"] >= 0.3
        assert result["valence"] > 0.0

    def test_fixed_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Fixed the authentication issue"))
        assert result["arousal"] >= 0.3
        assert result["valence"] > 0.0

    def test_got_it_keyword(self, tagger):
        result = tagger.analyze_context(_msgs("Oh I got it now"))
        assert result["arousal"] >= 0.3
        assert result["valence"] > 0.0


# ── Test class: correction markers ────────────────────────────────────────


class TestCorrectionMarkers:
    """Correction markers: +0.2 arousal, -0.3 valence."""

    def test_actually_marker(self, tagger):
        result = tagger.analyze_context(_msgs("Actually, that's not right"))
        assert result["arousal"] >= 0.2
        assert result["valence"] < 0.0
        assert "correction_markers" in result["signals"]

    def test_wait_no_marker(self, tagger):
        result = tagger.analyze_context(_msgs("Wait, no, that's not right at all"))
        assert result["arousal"] >= 0.2
        assert result["valence"] < 0.0

    def test_no_thats_wrong_marker(self, tagger):
        result = tagger.analyze_context(_msgs("No that's wrong, it should be X"))
        assert result["arousal"] >= 0.2
        assert result["valence"] < 0.0


# ── Test class: rapid message pace ────────────────────────────────────────


class TestRapidMessagePace:
    """Rapid pace (>5 msgs/min) adds +0.4 arousal."""

    def test_rapid_pace_detected(self, tagger):
        now = datetime.now()
        # 6 messages in 1 minute = rapid pace
        timestamps = [
            (now + timedelta(seconds=i * 8)).isoformat()
            for i in range(6)
        ]
        result = tagger.analyze_context(
            _msgs("msg1", "msg2", "msg3", "msg4", "msg5", "msg6"),
            timestamps=timestamps,
        )
        assert result["arousal"] >= 0.4
        assert "rapid_message_pace" in result["signals"]

    def test_slow_pace_not_detected(self, tagger):
        now = datetime.now()
        # 3 messages in 3 minutes = slow pace
        timestamps = [
            (now + timedelta(seconds=i * 60)).isoformat()
            for i in range(3)
        ]
        result = tagger.analyze_context(
            _msgs("msg1", "msg2", "msg3"),
            timestamps=timestamps,
        )
        assert "rapid_message_pace" not in result["signals"]


# ── Test class: question clusters ─────────────────────────────────────────


class TestQuestionClusters:
    """3+ questions in 5 messages: +0.2 arousal."""

    def test_question_cluster_detected(self, tagger):
        result = tagger.analyze_context(_msgs(
            "Why isn't this working?",
            "Did you check the logs?",
            "What error are you seeing?",
            "Have you tried restarting?",
            "Is the config correct?",
        ))
        assert result["arousal"] >= 0.2
        assert "question_cluster" in result["signals"]

    def test_few_questions_no_cluster(self, tagger):
        result = tagger.analyze_context(_msgs(
            "This is a statement.",
            "Another statement.",
            "One question?",
            "Yet another statement.",
            "More context here.",
        ))
        assert "question_cluster" not in result["signals"]


# ── Test class: valence clamping ──────────────────────────────────────────


class TestValenceClamping:
    """Valence must be clamped to [-1.0, +1.0]."""

    def test_extreme_positive_clamped(self, tagger):
        """Multiple positive signals should not exceed +1.0."""
        result = tagger.analyze_context(_msgs(
            "It works! Finally! Got it! Solved! Fixed!"
        ))
        assert result["valence"] <= 1.0

    def test_extreme_negative_clamped(self, tagger):
        """Multiple negative signals should not go below -1.0."""
        result = tagger.analyze_context(_msgs(
            "Bug crash error broken failed. Actually wait no that's wrong."
        ))
        assert result["valence"] >= -1.0


# ── Test class: arousal clamping ──────────────────────────────────────────


class TestArousalClamping:
    """Arousal must be clamped to [0.0, 1.0]."""

    def test_extreme_arousal_clamped(self, tagger):
        """Stacking all arousal signals should not exceed 1.0."""
        now = datetime.now()
        timestamps = [
            (now + timedelta(seconds=i * 5)).isoformat()
            for i in range(8)
        ]
        result = tagger.analyze_context(
            _msgs(
                "BUG!!! CRASH!!! ERROR!!!",
                "WHY IS THIS BROKEN?!",
                "What happened?",
                "How do we fix this?",
                "Is anyone looking at this?",
                "EVERYTHING FAILED!!!",
                "Actually wait, no that's wrong",
                "It works! Finally!",
            ),
            timestamps=timestamps,
        )
        assert result["arousal"] <= 1.0
        assert result["arousal"] >= 0.0

    def test_neutral_message_zero_arousal(self, tagger):
        """A completely neutral message should have low arousal."""
        result = tagger.analyze_context(_msgs("the configuration file is located in the src directory"))
        assert result["arousal"] >= 0.0
        assert result["arousal"] < 0.2


# ── Test class: tag_memory and get_tag ────────────────────────────────────


class TestTagMemoryPersistence:
    """Tag creation and retrieval from database."""

    def test_tag_memory_returns_emotional_tag(self, tagger):
        tag = tagger.tag_memory("mem_001", _msgs("It works! Finally!"))
        assert isinstance(tag, EmotionalTag)
        assert tag.memory_id == "mem_001"
        assert tag.valence > 0.0
        assert tag.arousal > 0.0
        assert len(tag.signals) > 0
        assert tag.created_at is not None

    def test_get_tag_retrieves_stored(self, tagger):
        tagger.tag_memory("mem_002", _msgs("Bug crash error"))
        retrieved = tagger.get_tag("mem_002")
        assert retrieved is not None
        assert retrieved.memory_id == "mem_002"
        assert retrieved.valence < 0.0

    def test_get_tag_returns_none_for_missing(self, tagger):
        assert tagger.get_tag("nonexistent") is None

    def test_tag_memory_overwrites_existing(self, tagger):
        tagger.tag_memory("mem_003", _msgs("Bug error crash"))
        tag1 = tagger.get_tag("mem_003")

        tagger.tag_memory("mem_003", _msgs("It works! Finally!"))
        tag2 = tagger.get_tag("mem_003")

        assert tag1.valence < 0.0
        assert tag2.valence > 0.0


# ── Test class: high arousal memories ─────────────────────────────────────


class TestHighArousalMemories:
    """get_high_arousal_memories returns memories above threshold."""

    def test_returns_high_arousal(self, tagger):
        tagger.tag_memory("high_1", _msgs("BUG!!! CRASH!!! EVERYTHING BROKEN!!!"))
        tagger.tag_memory("low_1", _msgs("the config is in the src directory"))

        high = tagger.get_high_arousal_memories(threshold=0.5)
        ids = [t.memory_id for t in high]
        assert "high_1" in ids
        assert "low_1" not in ids

    def test_empty_when_none_qualify(self, tagger):
        tagger.tag_memory("calm_1", _msgs("simple note about a setting"))
        assert tagger.get_high_arousal_memories(threshold=0.9) == []


# ── Test class: decay multiplier ──────────────────────────────────────────


class TestDecayMultiplier:
    """Decay multiplier: 1.5x for arousal > 0.5, else 1.0x."""

    def test_high_arousal_gets_1_5x(self, tagger):
        tagger.tag_memory("intense", _msgs("BUG!!! CRASH!!! EVERYTHING IS BROKEN!!!"))
        mult = tagger.get_decay_multiplier("intense")
        assert mult == 1.5

    def test_low_arousal_gets_1_0x(self, tagger):
        tagger.tag_memory("calm", _msgs("updated the readme"))
        mult = tagger.get_decay_multiplier("calm")
        assert mult == 1.0

    def test_untagged_gets_1_0x(self, tagger):
        """Memory with no tag defaults to 1.0x."""
        mult = tagger.get_decay_multiplier("no_tag")
        assert mult == 1.0


# ── Test class: emotional distribution ────────────────────────────────────


class TestEmotionalDistribution:
    """get_emotional_distribution returns summary stats."""

    def test_distribution_with_mixed_tags(self, tagger):
        tagger.tag_memory("pos", _msgs("It works! Finally! Got it!"))
        tagger.tag_memory("neg", _msgs("Bug error crash broken"))
        tagger.tag_memory("neutral", _msgs("the file is in the directory"))

        dist = tagger.get_emotional_distribution()
        assert dist["positive_count"] >= 1
        assert dist["negative_count"] >= 1
        assert "neutral_count" in dist
        assert "high_arousal_count" in dist
        assert "mean_valence" in dist
        assert "mean_arousal" in dist

    def test_empty_distribution(self, tagger):
        dist = tagger.get_emotional_distribution()
        assert dist["positive_count"] == 0
        assert dist["negative_count"] == 0
        assert dist["neutral_count"] == 0
        assert dist["high_arousal_count"] == 0


# ── Test class: flashbulb memories ────────────────────────────────────────


class TestFlashbulbMemories:
    """get_flashbulb_memories returns very high arousal memories."""

    def test_flashbulb_detection(self, tagger):
        now = datetime.now()
        timestamps = [
            (now + timedelta(seconds=i * 5)).isoformat()
            for i in range(6)
        ]
        # Stack: rapid pace + frustration + caps + exclamations
        tagger.tag_memory(
            "flashbulb_1",
            _msgs(
                "BUG!!! THE WHOLE SYSTEM CRASHED!!!",
                "EVERYTHING IS BROKEN!!!",
                "Why is this happening?",
                "What went wrong?",
                "How do we fix this?",
                "The error is in the DEPLOY PIPELINE!!!",
            ),
            timestamps=timestamps,
        )
        tagger.tag_memory("boring", _msgs("updated a comment"))

        flashbulbs = tagger.get_flashbulb_memories(min_arousal=0.7)
        ids = [t.memory_id for t in flashbulbs]
        assert "flashbulb_1" in ids
        assert "boring" not in ids


# ── Test class: combined signals ──────────────────────────────────────────


class TestCombinedSignals:
    """Multiple signal types interact correctly."""

    def test_frustration_with_caps_and_exclamation(self, tagger):
        result = tagger.analyze_context(_msgs("THIS IS BROKEN!!!"))
        assert result["arousal"] >= 0.5
        assert result["valence"] < 0.0
        # Should detect multiple signal types
        assert len(result["signals"]) >= 2

    def test_success_with_exclamation(self, tagger):
        result = tagger.analyze_context(_msgs("It works!!!"))
        assert result["valence"] > 0.0
        assert result["arousal"] >= 0.3

    def test_neutral_text(self, tagger):
        result = tagger.analyze_context(
            _msgs("the config file uses yaml format for frontmatter")
        )
        assert abs(result["valence"]) < 0.3
        assert result["arousal"] < 0.3


# ── Test class: edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_messages(self, tagger):
        result = tagger.analyze_context([])
        assert result["valence"] == 0.0
        assert result["arousal"] == 0.0
        assert result["signals"] == []

    def test_empty_content(self, tagger):
        result = tagger.analyze_context(_msgs(""))
        assert result["valence"] == 0.0
        assert result["arousal"] == 0.0

    def test_none_timestamps(self, tagger):
        """Passing None for timestamps should not crash."""
        result = tagger.analyze_context(_msgs("hello world"), timestamps=None)
        assert isinstance(result["arousal"], float)

    def test_signals_is_list_of_strings(self, tagger):
        tag = tagger.tag_memory("sig_test", _msgs("Bug found!"))
        assert isinstance(tag.signals, list)
        for s in tag.signals:
            assert isinstance(s, str)

    def test_created_at_is_iso_format(self, tagger):
        tag = tagger.tag_memory("time_test", _msgs("test"))
        # Should be parseable as ISO datetime
        datetime.fromisoformat(tag.created_at)
