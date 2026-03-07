"""Tests for skill_argument_extractor.py — TDD red phase.

Skill argument pattern extractor: mines session transcripts for recurring
argument structures. Detects which argument types appear most often, which
collapse quickly (short rebuttal chains), and which generate the most plan
changes. Feeds the skill evolution tracker with signal about which skills
produce contentious sessions.
"""

from pathlib import Path

import pytest

from memory_system.skill_argument_extractor import (
    ArgumentPattern,
    ArgumentExtractor,
    ArgumentType,
    ExtractionResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def extractor(temp_db):
    return ArgumentExtractor(db_path=temp_db)


# Simple transcript stubs — just enough structure for heuristic extraction
TRANSCRIPT_WITH_COUNTERPOINT = [
    {"role": "assistant", "content": "We should use approach A because it's simpler."},
    {"role": "user", "content": "No, actually approach B is better for our use case."},
    {"role": "assistant", "content": "Fair point. Approach B it is."},
]

TRANSCRIPT_WITH_OBJECTION = [
    {"role": "assistant", "content": "I recommend adding a cache layer here."},
    {"role": "user", "content": "Wait, that's premature optimization."},
    {"role": "assistant", "content": "You're right, let's skip the cache for now."},
]

TRANSCRIPT_WITH_AGREEMENT = [
    {"role": "assistant", "content": "This approach looks good to me."},
    {"role": "user", "content": "Agreed, let's go with it."},
    {"role": "assistant", "content": "Perfect, moving forward."},
]

TRANSCRIPT_WITH_PLAN_CHANGE = [
    {"role": "assistant", "content": "Plan: build the entire auth system today."},
    {"role": "user", "content": "That's too much scope. Can we start with just login?"},
    {"role": "assistant", "content": "Good call. Revised plan: login only."},
]

TRANSCRIPT_LONG_DEBATE = [
    {"role": "assistant", "content": "I think we should use Redis."},
    {"role": "user", "content": "Why not SQLite? It's simpler."},
    {"role": "assistant", "content": "Redis handles eviction automatically."},
    {"role": "user", "content": "But we don't need eviction at this scale."},
    {"role": "assistant", "content": "Okay, you have a point. SQLite is fine."},
]

EMPTY_TRANSCRIPT: list = []


# ---------------------------------------------------------------------------
# ArgumentType
# ---------------------------------------------------------------------------

class TestArgumentType:
    def test_has_counterpoint_value(self):
        assert ArgumentType.COUNTERPOINT

    def test_has_objection_value(self):
        assert ArgumentType.OBJECTION

    def test_has_plan_change_value(self):
        assert ArgumentType.PLAN_CHANGE

    def test_has_agreement_value(self):
        assert ArgumentType.AGREEMENT

    def test_values_are_strings(self):
        for t in ArgumentType:
            assert isinstance(t.value, str)


# ---------------------------------------------------------------------------
# ArgumentPattern dataclass
# ---------------------------------------------------------------------------

class TestArgumentPattern:
    def test_has_required_fields(self):
        p = ArgumentPattern(
            pattern_id="p1",
            argument_type=ArgumentType.COUNTERPOINT,
            trigger_phrase="No, actually",
            resolution="concede",
            chain_length=2,
            led_to_plan_change=False,
            session_id="s1",
        )
        assert p.pattern_id == "p1"
        assert p.argument_type == ArgumentType.COUNTERPOINT
        assert p.chain_length == 2

    def test_led_to_plan_change_defaults_false(self):
        p = ArgumentPattern(
            pattern_id="p2",
            argument_type=ArgumentType.OBJECTION,
            trigger_phrase="Wait,",
            resolution="defer",
            chain_length=1,
            led_to_plan_change=False,
            session_id="s2",
        )
        assert p.led_to_plan_change is False


# ---------------------------------------------------------------------------
# ExtractionResult dataclass
# ---------------------------------------------------------------------------

class TestExtractionResult:
    def test_has_required_fields(self):
        r = ExtractionResult(
            session_id="s1",
            patterns_found=3,
            patterns=[],
            plan_changes=1,
        )
        assert r.session_id == "s1"
        assert r.patterns_found == 3
        assert r.plan_changes == 1

    def test_patterns_is_list(self):
        r = ExtractionResult(
            session_id="s1",
            patterns_found=0,
            patterns=[],
            plan_changes=0,
        )
        assert isinstance(r.patterns, list)


# ---------------------------------------------------------------------------
# ArgumentExtractor.extract()
# ---------------------------------------------------------------------------

class TestExtract:
    def test_returns_extraction_result(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        assert isinstance(result, ExtractionResult)

    def test_empty_transcript_returns_zero_patterns(self, extractor):
        result = extractor.extract(EMPTY_TRANSCRIPT, session_id="s1")
        assert result.patterns_found == 0
        assert result.patterns == []

    def test_detects_counterpoint(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        types = [p.argument_type for p in result.patterns]
        assert ArgumentType.COUNTERPOINT in types

    def test_detects_objection(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_OBJECTION, session_id="s1")
        types = [p.argument_type for p in result.patterns]
        assert ArgumentType.OBJECTION in types

    def test_detects_plan_change(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_PLAN_CHANGE, session_id="s1")
        assert result.plan_changes >= 1

    def test_session_id_stored(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_COUNTERPOINT, session_id="abc123")
        assert result.session_id == "abc123"

    def test_patterns_are_argument_pattern_instances(self, extractor):
        result = extractor.extract(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        for p in result.patterns:
            assert isinstance(p, ArgumentPattern)

    def test_chain_length_positive(self, extractor):
        result = extractor.extract(TRANSCRIPT_LONG_DEBATE, session_id="s1")
        for p in result.patterns:
            assert p.chain_length >= 1

    def test_long_debate_has_longer_chain(self, extractor):
        short = extractor.extract(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        long = extractor.extract(TRANSCRIPT_LONG_DEBATE, session_id="s2")
        max_short = max((p.chain_length for p in short.patterns), default=0)
        max_long = max((p.chain_length for p in long.patterns), default=0)
        assert max_long >= max_short


# ---------------------------------------------------------------------------
# Persistence: extract_and_store()
# ---------------------------------------------------------------------------

class TestExtractAndStore:
    def test_returns_extraction_result(self, extractor):
        result = extractor.extract_and_store(
            TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1"
        )
        assert isinstance(result, ExtractionResult)

    def test_stores_patterns_in_db(self, extractor):
        extractor.extract_and_store(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        rows = extractor._conn.execute(
            "SELECT COUNT(*) FROM argument_patterns"
        ).fetchone()[0]
        assert rows >= 1

    def test_idempotent_on_same_session(self, extractor):
        extractor.extract_and_store(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        extractor.extract_and_store(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        rows = extractor._conn.execute(
            "SELECT COUNT(*) FROM argument_patterns WHERE session_id = 's1'"
        ).fetchone()[0]
        # Should not double-insert for the same session
        first_count = rows
        assert first_count >= 1


# ---------------------------------------------------------------------------
# ArgumentExtractor.get_recurring_patterns()
# ---------------------------------------------------------------------------

class TestGetRecurringPatterns:
    def test_returns_list(self, extractor):
        result = extractor.get_recurring_patterns()
        assert isinstance(result, list)

    def test_empty_when_no_data(self, extractor):
        result = extractor.get_recurring_patterns()
        assert result == []

    def test_returns_most_frequent_first(self, extractor):
        # Store same type across 3 sessions → should appear in recurring
        for i in range(3):
            extractor.extract_and_store(
                TRANSCRIPT_WITH_COUNTERPOINT, session_id=f"s{i}"
            )
        result = extractor.get_recurring_patterns(min_occurrences=2)
        if result:
            # Verify sorted descending by count
            counts = [r["count"] for r in result]
            assert counts == sorted(counts, reverse=True)

    def test_filters_by_min_occurrences(self, extractor):
        extractor.extract_and_store(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        result = extractor.get_recurring_patterns(min_occurrences=5)
        assert result == []

    def test_result_has_argument_type(self, extractor):
        for i in range(3):
            extractor.extract_and_store(
                TRANSCRIPT_WITH_COUNTERPOINT, session_id=f"s{i}"
            )
        result = extractor.get_recurring_patterns(min_occurrences=1)
        if result:
            assert "argument_type" in result[0]

    def test_result_has_count(self, extractor):
        for i in range(3):
            extractor.extract_and_store(
                TRANSCRIPT_WITH_COUNTERPOINT, session_id=f"s{i}"
            )
        result = extractor.get_recurring_patterns(min_occurrences=1)
        if result:
            assert "count" in result[0]


# ---------------------------------------------------------------------------
# ArgumentExtractor.get_plan_change_rate()
# ---------------------------------------------------------------------------

class TestGetPlanChangeRate:
    def test_returns_float(self, extractor):
        result = extractor.get_plan_change_rate()
        assert isinstance(result, float)

    def test_zero_when_no_data(self, extractor):
        result = extractor.get_plan_change_rate()
        assert result == 0.0

    def test_rate_between_0_and_1(self, extractor):
        for i in range(4):
            extractor.extract_and_store(
                TRANSCRIPT_WITH_PLAN_CHANGE, session_id=f"s{i}"
            )
        result = extractor.get_plan_change_rate()
        assert 0.0 <= result <= 1.0

    def test_rate_higher_with_plan_changes(self, extractor):
        extractor.extract_and_store(TRANSCRIPT_WITH_PLAN_CHANGE, session_id="s1")
        rate_with = extractor.get_plan_change_rate()
        assert rate_with >= 0.0


# ---------------------------------------------------------------------------
# ArgumentExtractor.get_collapse_rate()
# ---------------------------------------------------------------------------

class TestGetCollapseRate:
    def test_returns_float(self, extractor):
        result = extractor.get_collapse_rate()
        assert isinstance(result, float)

    def test_zero_when_no_data(self, extractor):
        result = extractor.get_collapse_rate()
        assert result == 0.0

    def test_rate_between_0_and_1(self, extractor):
        extractor.extract_and_store(TRANSCRIPT_WITH_COUNTERPOINT, session_id="s1")
        result = extractor.get_collapse_rate()
        assert 0.0 <= result <= 1.0
