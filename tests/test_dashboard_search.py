"""
Tests for dashboard search helpers: _extract_snippet and _match_reasons.
"""
import sys
from pathlib import Path

# Make dashboard/server importable without running Flask
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.server import _extract_snippet, _match_reasons


# ---------------------------------------------------------------------------
# _extract_snippet
# ---------------------------------------------------------------------------

class TestExtractSnippet:
    def test_returns_empty_when_query_not_in_body(self):
        assert _extract_snippet("hello world", "xyz") == ""

    def test_returns_empty_on_empty_body(self):
        assert _extract_snippet("", "foo") == ""

    def test_returns_snippet_containing_query(self):
        body = "This is a sentence about circuit breakers and their role in systems."
        snippet = _extract_snippet(body, "circuit breaker")
        assert "circuit breaker" in snippet.lower()

    def test_snippet_shorter_than_full_body(self):
        body = "a " * 200 + "target" + " b" * 200
        snippet = _extract_snippet(body, "target", window=120)
        assert len(snippet) < len(body)
        assert "target" in snippet

    def test_snippet_adds_ellipsis_when_truncated_start(self):
        body = "x " * 100 + "needle here" + " y" * 100
        snippet = _extract_snippet(body, "needle", window=30)
        assert snippet.startswith("…")

    def test_snippet_adds_ellipsis_when_truncated_end(self):
        body = "needle here" + " y " * 200
        snippet = _extract_snippet(body, "needle", window=20)
        assert snippet.endswith("…")

    def test_no_ellipsis_when_full_body_fits(self):
        body = "short body with needle"
        snippet = _extract_snippet(body, "needle", window=200)
        assert not snippet.startswith("…")
        assert not snippet.endswith("…")

    def test_case_insensitive_match(self):
        body = "We use Circuit Breakers to prevent cascading failures."
        snippet = _extract_snippet(body, "circuit breaker")
        assert snippet  # should find match regardless of case

    def test_newlines_replaced_with_spaces(self):
        body = "line one\nneedle is here\nline three"
        snippet = _extract_snippet(body, "needle")
        assert "\n" not in snippet


# ---------------------------------------------------------------------------
# _match_reasons
# ---------------------------------------------------------------------------

class TestMatchReasons:
    def _make_memory(self, body="", tags=None, domain=""):
        return {
            "_body": body,
            "semantic_tags": tags or [],
            "knowledge_domain": domain,
        }

    def test_body_match(self):
        m = self._make_memory(body="circuit breaker prevents failures")
        reasons = _match_reasons(m, "circuit breaker")
        assert "body" in reasons

    def test_tag_match(self):
        m = self._make_memory(tags=["circuit-breaker", "resilience"])
        reasons = _match_reasons(m, "circuit-breaker")
        assert any("tag" in r for r in reasons)

    def test_domain_match(self):
        m = self._make_memory(domain="DevOps")
        reasons = _match_reasons(m, "devops")
        assert any("domain" in r for r in reasons)

    def test_multiple_matches(self):
        m = self._make_memory(
            body="devops automation",
            domain="DevOps",
        )
        reasons = _match_reasons(m, "devops")
        assert "body" in reasons
        assert any("domain" in r for r in reasons)

    def test_no_match_returns_empty(self):
        m = self._make_memory(body="unrelated text", tags=[], domain="unrelated")
        reasons = _match_reasons(m, "zzznomatch")
        assert reasons == []

    def test_tag_reason_includes_tag_name(self):
        m = self._make_memory(tags=["#learning", "fsrs-scheduler"])
        reasons = _match_reasons(m, "fsrs")
        # Should mention the matched tag name
        assert any("fsrs" in r for r in reasons)

    def test_case_insensitive_tag_match(self):
        m = self._make_memory(tags=["FSRS", "learning"])
        reasons = _match_reasons(m, "fsrs")
        assert any("tag" in r for r in reasons)
