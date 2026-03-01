"""Tests for search_utils — shared match reason and snippet extraction utilities."""

import pytest

from memory_system.search_utils import match_reasons, extract_snippet


class TestMatchReasons:
    """Tests for match_reasons()."""

    def test_body_match_found(self):
        """Query substring in content produces 'body match'."""
        reasons = match_reasons("python", "I love python programming", ["dev"], "engineering")
        assert "body match" in reasons

    def test_body_match_case_insensitive(self):
        """Body match is case-insensitive."""
        reasons = match_reasons("Python", "i love python programming", ["dev"], "engineering")
        assert "body match" in reasons

    def test_tag_match_found(self):
        """Query substring in a tag produces 'tag match: #tag'."""
        reasons = match_reasons("python", "some content", ["python", "dev"], "engineering")
        assert "tag match: #python" in reasons

    def test_tag_match_case_insensitive(self):
        """Tag match is case-insensitive."""
        reasons = match_reasons("PYTHON", "some content", ["python", "dev"], "engineering")
        assert "tag match: #python" in reasons

    def test_domain_match_found(self):
        """Query substring in domain produces 'domain match: domain'."""
        reasons = match_reasons("eng", "some content", ["dev"], "engineering")
        assert "domain match: engineering" in reasons

    def test_multiple_match_reasons(self):
        """Query matching body, tag, and domain returns all three."""
        reasons = match_reasons("python", "python rocks", ["python"], "python-dev")
        assert len(reasons) == 3
        assert "body match" in reasons
        assert "tag match: #python" in reasons
        assert "domain match: python-dev" in reasons

    def test_no_match_returns_empty(self):
        """No matches at all returns empty list."""
        reasons = match_reasons("rust", "python rocks", ["python"], "engineering")
        assert reasons == []

    def test_multiple_tag_matches(self):
        """Multiple tags matching query each produce a reason."""
        reasons = match_reasons("test", "content", ["test", "testing", "dev"], "eng")
        tag_reasons = [r for r in reasons if r.startswith("tag match")]
        assert len(tag_reasons) == 2


class TestExtractSnippet:
    """Tests for extract_snippet()."""

    def test_snippet_centered_on_match(self):
        """Snippet is centered around the query match position."""
        content = "A" * 100 + "FINDME" + "B" * 100
        snippet = extract_snippet(content, "FINDME", window=40)
        assert "FINDME" in snippet

    def test_snippet_no_match_returns_beginning(self):
        """When query not found, returns beginning of content."""
        content = "This is some content that does not contain the query term"
        snippet = extract_snippet(content, "zzzzz", window=20)
        assert snippet.startswith("This is some content")

    def test_snippet_ellipsis_both_sides(self):
        """Snippet gets ellipsis on both sides when match is in middle."""
        content = "X" * 200 + "FINDME" + "Y" * 200
        snippet = extract_snippet(content, "FINDME", window=40)
        assert snippet.startswith("...")
        assert snippet.endswith("...")

    def test_snippet_no_leading_ellipsis_at_start(self):
        """No leading ellipsis when match is at the start."""
        content = "FINDME" + "Y" * 200
        snippet = extract_snippet(content, "FINDME", window=40)
        assert not snippet.startswith("...")

    def test_snippet_no_trailing_ellipsis_at_end(self):
        """No trailing ellipsis when match is at the end."""
        content = "X" * 10 + "FINDME"
        snippet = extract_snippet(content, "FINDME", window=40)
        assert not snippet.endswith("...")

    def test_snippet_short_content_no_ellipsis(self):
        """Short content that fits in window has no ellipsis."""
        content = "short"
        snippet = extract_snippet(content, "zzz", window=120)
        assert snippet == "short"

    def test_snippet_case_insensitive_search(self):
        """Snippet extraction finds match case-insensitively."""
        content = "A" * 100 + "FindMe" + "B" * 100
        snippet = extract_snippet(content, "findme", window=40)
        assert "FindMe" in snippet

    def test_snippet_respects_window_size(self):
        """Snippet length is bounded by the window parameter."""
        content = "X" * 500
        snippet = extract_snippet(content, "XXX", window=60)
        # Snippet body (without ellipsis) should be roughly window-sized
        clean = snippet.replace("...", "")
        assert len(clean) <= 60 + 10  # small tolerance for query length
