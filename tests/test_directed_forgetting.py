"""
Tests for directed_forgetting.py

Cognitive psychology — Bjork (1972) directed forgetting.
Detects intent markers in conversation to boost or suppress memory importance.
"""

import pytest
from memory_system.directed_forgetting import DirectedForgetting


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def df():
    """Fresh DirectedForgetting instance."""
    return DirectedForgetting()


@pytest.fixture
def conversation_with_forget():
    """Conversation where user tells assistant to forget something."""
    return [
        {"role": "user", "content": "The API endpoint is /v2/users"},
        {"role": "assistant", "content": "Got it, /v2/users for the user endpoint."},
        {"role": "user", "content": "Actually, never mind, scratch that. It's /v3/users now."},
        {"role": "assistant", "content": "Understood, the endpoint is /v3/users."},
    ]


@pytest.fixture
def conversation_with_remember():
    """Conversation where user explicitly asks to remember something."""
    return [
        {"role": "user", "content": "Remember this: the deploy key rotates every 90 days."},
        {"role": "assistant", "content": "Noted — deploy key rotates every 90 days."},
        {"role": "user", "content": "And the staging server is at staging.example.com"},
        {"role": "assistant", "content": "Got it."},
    ]


@pytest.fixture
def conversation_mixed():
    """Conversation with both forget and remember markers."""
    return [
        {"role": "user", "content": "The database password is hunter2"},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Forget it, that's wrong. The real password is different."},
        {"role": "assistant", "content": "Understood, disregarding that."},
        {"role": "user", "content": "Important: always use parameterized queries for this DB."},
        {"role": "assistant", "content": "Will do — parameterized queries only."},
    ]


# ── Pattern detection: extract_directives_from_text ───────────────────────────


class TestExtractDirectivesFromText:
    """Test finding markers in raw text."""

    def test_forget_never_mind(self, df):
        result = df.extract_directives_from_text("Oh, never mind that approach.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_scratch_that(self, df):
        result = df.extract_directives_from_text("Scratch that, let's try something else.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_thats_wrong(self, df):
        result = df.extract_directives_from_text("Wait, that's wrong. The port is 8080.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_ignore_that(self, df):
        result = df.extract_directives_from_text("Ignore that last part about caching.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_disregard(self, df):
        result = df.extract_directives_from_text("Please disregard the previous config.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_forget_it(self, df):
        result = df.extract_directives_from_text("Forget it, that was outdated info.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_forget_actually_no(self, df):
        result = df.extract_directives_from_text("Actually, no — use the other endpoint.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_remember_remember_this(self, df):
        result = df.extract_directives_from_text("Remember this: deploy on Tuesdays only.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_remember_note_this(self, df):
        result = df.extract_directives_from_text("Note this for later — the API rate limit is 100/min.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_remember_important_colon(self, df):
        result = df.extract_directives_from_text("Important: never deploy on Fridays.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_remember_key_takeaway(self, df):
        result = df.extract_directives_from_text("The key takeaway is to always test in staging first.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_remember_dont_forget(self, df):
        result = df.extract_directives_from_text("Don't forget — the SSL cert expires in March.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_remember_note_for_future(self, df):
        result = df.extract_directives_from_text("Note for future: client prefers PDF reports.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_no_markers(self, df):
        result = df.extract_directives_from_text("The server runs on port 3000.")
        assert len(result) == 0

    def test_empty_string(self, df):
        result = df.extract_directives_from_text("")
        assert len(result) == 0

    def test_case_insensitive_forget(self, df):
        result = df.extract_directives_from_text("NEVER MIND, use the old config.")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_case_insensitive_remember(self, df):
        result = df.extract_directives_from_text("REMEMBER THIS: always backup before deploy.")
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_multiple_markers_in_text(self, df):
        text = "Scratch that. Actually, important: use the new API version."
        result = df.extract_directives_from_text(text)
        assert len(result) == 2
        types = {r["type"] for r in result}
        assert "forget" in types
        assert "remember" in types

    def test_marker_has_position(self, df):
        result = df.extract_directives_from_text("Oh wait, scratch that please.")
        assert len(result) == 1
        assert "position" in result[0]
        assert isinstance(result[0]["position"], int)
        assert result[0]["position"] >= 0

    def test_marker_has_matched_text(self, df):
        result = df.extract_directives_from_text("Never mind, wrong approach.")
        assert len(result) == 1
        assert "marker" in result[0]
        assert len(result[0]["marker"]) > 0


# ── Conversation scanning: scan_conversation ──────────────────────────────────


class TestScanConversation:
    """Test scanning full message lists for directives."""

    def test_finds_forget_in_conversation(self, df, conversation_with_forget):
        results = df.scan_conversation(conversation_with_forget)
        forget_results = [r for r in results if r["marker_type"] == "forget"]
        assert len(forget_results) >= 1

    def test_finds_remember_in_conversation(self, df, conversation_with_remember):
        results = df.scan_conversation(conversation_with_remember)
        remember_results = [r for r in results if r["marker_type"] == "remember"]
        assert len(remember_results) >= 1

    def test_finds_both_in_mixed_conversation(self, df, conversation_mixed):
        results = df.scan_conversation(conversation_mixed)
        types = {r["marker_type"] for r in results}
        assert "forget" in types
        assert "remember" in types

    def test_returns_position(self, df, conversation_with_forget):
        results = df.scan_conversation(conversation_with_forget)
        assert len(results) > 0
        for r in results:
            assert "position" in r
            assert isinstance(r["position"], int)

    def test_returns_context(self, df, conversation_with_forget):
        results = df.scan_conversation(conversation_with_forget)
        assert len(results) > 0
        for r in results:
            assert "context" in r
            assert isinstance(r["context"], str)
            assert len(r["context"]) > 0

    def test_returns_pattern_matched(self, df, conversation_with_forget):
        results = df.scan_conversation(conversation_with_forget)
        assert len(results) > 0
        for r in results:
            assert "pattern_matched" in r
            assert isinstance(r["pattern_matched"], str)

    def test_empty_conversation(self, df):
        results = df.scan_conversation([])
        assert results == []

    def test_no_markers_conversation(self, df):
        msgs = [
            {"role": "user", "content": "How do I deploy?"},
            {"role": "assistant", "content": "Run deploy.sh."},
        ]
        results = df.scan_conversation(msgs)
        assert results == []

    def test_only_scans_user_messages(self, df):
        """Directives come from the user, not the assistant."""
        msgs = [
            {"role": "user", "content": "Tell me about the config."},
            {"role": "assistant", "content": "Never mind that, let me explain differently."},
        ]
        results = df.scan_conversation(msgs)
        # Assistant saying 'never mind' should not count
        assert len(results) == 0


# ── Proximity directive: get_directive_for_content ────────────────────────────


class TestGetDirectiveForContent:
    """Test checking if content has a nearby directive within a window."""

    def test_forget_directive_nearby(self, df, conversation_with_forget):
        # Message 0 content ("The API endpoint is /v2/users") has a forget
        # directive at position 2 ("scratch that") — distance 2
        directive = df.get_directive_for_content(
            content="The API endpoint is /v2/users",
            messages=conversation_with_forget,
            position=0,
            window=3,
        )
        assert directive is not None
        assert directive["type"] == "forget"

    def test_remember_directive_nearby(self, df, conversation_with_remember):
        # "the deploy key rotates every 90 days" is at position 0 which contains
        # the remember marker itself
        directive = df.get_directive_for_content(
            content="the deploy key rotates every 90 days",
            messages=conversation_with_remember,
            position=0,
            window=3,
        )
        assert directive is not None
        assert directive["type"] == "remember"

    def test_no_directive_when_far_away(self, df):
        msgs = [
            {"role": "user", "content": "The server is on port 3000."},
            {"role": "assistant", "content": "Noted."},
            {"role": "user", "content": "And the DB is postgres."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "The cache is Redis."},
            {"role": "assistant", "content": "OK."},
            {"role": "user", "content": "Actually, never mind about something else."},
        ]
        # Position 0 is far from the forget at position 6 (distance 6 > window 3)
        directive = df.get_directive_for_content(
            content="The server is on port 3000.",
            messages=msgs,
            position=0,
            window=3,
        )
        assert directive is None

    def test_returns_distance(self, df, conversation_with_forget):
        directive = df.get_directive_for_content(
            content="The API endpoint is /v2/users",
            messages=conversation_with_forget,
            position=0,
            window=3,
        )
        assert directive is not None
        assert "distance" in directive
        assert isinstance(directive["distance"], int)

    def test_no_directive_in_empty_messages(self, df):
        directive = df.get_directive_for_content(
            content="anything",
            messages=[],
            position=0,
            window=3,
        )
        assert directive is None

    def test_window_default(self, df, conversation_with_forget):
        """Default window should work (3 messages)."""
        directive = df.get_directive_for_content(
            content="The API endpoint is /v2/users",
            messages=conversation_with_forget,
            position=0,
        )
        assert directive is not None

    def test_closest_directive_wins(self, df):
        """When multiple directives exist, the closest one should be returned."""
        msgs = [
            {"role": "user", "content": "Important: use SSL everywhere."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user", "content": "Scratch that, HTTP is fine internally."},
        ]
        directive = df.get_directive_for_content(
            content="use SSL everywhere",
            messages=msgs,
            position=0,
            window=3,
        )
        # The forget ("scratch that") at position 2 is closer than the remember
        # in position 0 itself, but position 0 also contains "important:"
        # For the content at position 0, a later forget should override
        assert directive is not None
        assert directive["type"] == "forget"


# ── Importance modification: apply_importance_modifier ────────────────────────


class TestApplyImportanceModifier:
    """Test importance score adjustments."""

    def test_forget_sets_minimum(self, df):
        result = df.apply_importance_modifier(0.8, {"type": "forget", "marker": "scratch that", "distance": 1})
        assert result == pytest.approx(0.1)

    def test_forget_overrides_high_importance(self, df):
        result = df.apply_importance_modifier(1.0, {"type": "forget", "marker": "never mind", "distance": 1})
        assert result == pytest.approx(0.1)

    def test_remember_boosts_importance(self, df):
        result = df.apply_importance_modifier(0.5, {"type": "remember", "marker": "remember this", "distance": 0})
        assert result == pytest.approx(0.8)

    def test_remember_caps_at_one(self, df):
        result = df.apply_importance_modifier(0.9, {"type": "remember", "marker": "important:", "distance": 0})
        assert result == pytest.approx(1.0)

    def test_remember_from_low_base(self, df):
        result = df.apply_importance_modifier(0.2, {"type": "remember", "marker": "note this", "distance": 1})
        assert result == pytest.approx(0.5)

    def test_no_directive_returns_base(self, df):
        result = df.apply_importance_modifier(0.7, None)
        assert result == pytest.approx(0.7)

    def test_zero_base_with_remember(self, df):
        result = df.apply_importance_modifier(0.0, {"type": "remember", "marker": "key takeaway", "distance": 0})
        assert result == pytest.approx(0.3)

    def test_zero_base_with_forget(self, df):
        result = df.apply_importance_modifier(0.0, {"type": "forget", "marker": "forget it", "distance": 1})
        assert result == pytest.approx(0.1)

    def test_negative_base_with_no_directive(self, df):
        """Edge case: negative base should pass through unchanged."""
        result = df.apply_importance_modifier(-0.1, None)
        assert result == pytest.approx(-0.1)


# ── Edge cases and robustness ─────────────────────────────────────────────────


class TestEdgeCases:
    """Robustness and boundary conditions."""

    def test_partial_marker_no_match(self, df):
        """Substrings that look like markers but aren't."""
        result = df.extract_directives_from_text("I never mind the gap in coverage.")
        # "never mind" should still match — it's a phrase
        assert len(result) >= 1

    def test_forget_in_quoted_context(self, df):
        """Forget marker in a quote — still detected (conservative approach)."""
        result = df.extract_directives_from_text('He said "scratch that" during the meeting.')
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_messages_missing_content_key(self, df):
        """Gracefully handle messages without 'content' key."""
        msgs = [
            {"role": "user"},
            {"role": "assistant", "content": "response"},
        ]
        results = df.scan_conversation(msgs)
        assert isinstance(results, list)

    def test_messages_with_none_content(self, df):
        """Gracefully handle messages with None content."""
        msgs = [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "response"},
        ]
        results = df.scan_conversation(msgs)
        assert isinstance(results, list)

    def test_very_long_text(self, df):
        """Handle large text blocks without error."""
        text = "Some normal text. " * 1000 + "Remember this: key fact. " + "More text. " * 1000
        result = df.extract_directives_from_text(text)
        assert len(result) == 1
        assert result[0]["type"] == "remember"

    def test_unicode_text(self, df):
        """Handle unicode without errors."""
        result = df.extract_directives_from_text("Never mind the cafe — 日本語テキスト")
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_newlines_in_text(self, df):
        """Markers spanning or near newlines."""
        text = "First line.\nScratch that.\nThird line."
        result = df.extract_directives_from_text(text)
        assert len(result) == 1
        assert result[0]["type"] == "forget"

    def test_position_out_of_range(self, df):
        """Position beyond message list should return None."""
        msgs = [{"role": "user", "content": "Hello"}]
        directive = df.get_directive_for_content("Hello", msgs, position=10, window=3)
        assert directive is None
