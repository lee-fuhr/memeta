"""
Directed forgetting with intent markers.

Based on Bjork (1972) directed forgetting from cognitive psychology.
During extraction, detects intent markers in conversation that indicate
whether information should be retained or discarded:

- **Forget markers:** "never mind", "scratch that", "that's wrong",
  "ignore that", "disregard", "forget it", "actually, no"
- **Remember markers:** "remember this", "note this", "important:",
  "key takeaway", "don't forget", "note for future"

Memories with forget markers get minimum importance (0.1) and fastest decay.
Memories with remember markers get importance boost (+0.3, capped at 1.0).

This module is a helper that other modules call — it does not directly
modify memory files.

Usage:
    from memory_system.directed_forgetting import DirectedForgetting

    df = DirectedForgetting()
    directives = df.scan_conversation(messages)
    directive = df.get_directive_for_content(content, messages, position)
    importance = df.apply_importance_modifier(base_importance, directive)
"""

from __future__ import annotations

import re


class DirectedForgetting:
    """Detect user intent markers to boost or suppress memory importance."""

    # ── Forget patterns ───────────────────────────────────────────────────

    FORGET_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bnever\s+mind\b", re.IGNORECASE),
        re.compile(r"\bscratch\s+that\b", re.IGNORECASE),
        re.compile(r"\bthat'?s\s+wrong\b", re.IGNORECASE),
        re.compile(r"\bignore\s+that\b", re.IGNORECASE),
        re.compile(r"\bdisregard\b", re.IGNORECASE),
        re.compile(r"\bforget\s+it\b", re.IGNORECASE),
        re.compile(r"\bactually,?\s*no\b", re.IGNORECASE),
    ]

    # ── Remember patterns ─────────────────────────────────────────────────

    REMEMBER_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bremember\s+this\b", re.IGNORECASE),
        re.compile(r"\bnote\s+this\b", re.IGNORECASE),
        re.compile(r"\bimportant\s*:", re.IGNORECASE),
        re.compile(r"\bkey\s+takeaway\b", re.IGNORECASE),
        re.compile(r"\bdon'?t\s+forget\b", re.IGNORECASE),
        re.compile(r"\bnote\s+for\s+future\b", re.IGNORECASE),
    ]

    # ── Constants ─────────────────────────────────────────────────────────

    FORGET_IMPORTANCE: float = 0.1
    REMEMBER_BOOST: float = 0.3
    MAX_IMPORTANCE: float = 1.0

    # ── Public API ────────────────────────────────────────────────────────

    def extract_directives_from_text(self, text: str) -> list[dict]:
        """
        Find all forget/remember markers in a text block.

        Args:
            text: Raw text to scan.

        Returns:
            List of dicts: [{type: 'forget'|'remember', marker: str, position: int}]
        """
        if not text:
            return []

        results: list[dict] = []

        for pattern in self.FORGET_PATTERNS:
            for match in pattern.finditer(text):
                results.append({
                    "type": "forget",
                    "marker": match.group(),
                    "position": match.start(),
                })

        for pattern in self.REMEMBER_PATTERNS:
            for match in pattern.finditer(text):
                results.append({
                    "type": "remember",
                    "marker": match.group(),
                    "position": match.start(),
                })

        # Sort by position in text for stable ordering
        results.sort(key=lambda r: r["position"])
        return results

    def scan_conversation(self, messages: list[dict]) -> list[dict]:
        """
        Scan messages for intent markers.

        Only scans user messages — directives come from the user, not
        the assistant.

        Args:
            messages: List of {role, content} message dicts.

        Returns:
            List of {position, marker_type, pattern_matched, context}
        """
        results: list[dict] = []

        for idx, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue

            content = msg.get("content")
            if not content:
                continue

            directives = self.extract_directives_from_text(content)
            for d in directives:
                results.append({
                    "position": idx,
                    "marker_type": d["type"],
                    "pattern_matched": d["marker"],
                    "context": content,
                })

        return results

    def get_directive_for_content(
        self,
        content: str,
        messages: list[dict],
        position: int,
        window: int = 3,
    ) -> dict | None:
        """
        Check if content at position has a nearby directive within window.

        Looks at user messages within *window* message positions (forward
        and backward) for the closest forget or remember marker.  A later
        forget directive overrides an earlier remember directive when both
        are within range.

        Args:
            content:  The text whose importance we're evaluating.
            messages: Full conversation message list.
            position: Index of the message containing *content*.
            window:   How many messages away to search.

        Returns:
            {type: 'forget'|'remember', marker: str, distance: int} or None.
        """
        if not messages or position < 0 or position >= len(messages):
            return None

        # Scan the window around the position
        start = max(0, position - window)
        end = min(len(messages), position + window + 1)

        candidates: list[dict] = []

        for idx in range(start, end):
            msg = messages[idx]
            if msg.get("role") != "user":
                continue

            msg_content = msg.get("content")
            if not msg_content:
                continue

            directives = self.extract_directives_from_text(msg_content)
            for d in directives:
                distance = abs(idx - position)
                candidates.append({
                    "type": d["type"],
                    "marker": d["marker"],
                    "distance": distance,
                    "msg_index": idx,
                })

        if not candidates:
            return None

        # A forget directive appearing AFTER the content position carries
        # strong intent — the user said something, then retracted it.
        # These always win over remember directives regardless of distance,
        # because "scratch that" explicitly negates what came before.
        later_forgets = [
            c for c in candidates
            if c["type"] == "forget" and c["msg_index"] > position
        ]
        if later_forgets:
            later_forgets.sort(key=lambda c: c["distance"])
            best = later_forgets[0]
            return {
                "type": best["type"],
                "marker": best["marker"],
                "distance": best["distance"],
            }

        # No later forget — pick closest directive overall.
        # On ties, prefer the one later in conversation (higher msg_index).
        candidates.sort(key=lambda c: (c["distance"], -c["msg_index"]))
        best = candidates[0]

        return {
            "type": best["type"],
            "marker": best["marker"],
            "distance": best["distance"],
        }

    def apply_importance_modifier(
        self,
        base_importance: float,
        directive: dict | None,
    ) -> float:
        """
        Apply importance modifier based on directive.

        - Forget  -> 0.1 (minimum importance)
        - Remember -> min(base + 0.3, 1.0) (boosted, capped)
        - None    -> base (unchanged)

        Args:
            base_importance: The original importance score.
            directive:       Output of get_directive_for_content, or None.

        Returns:
            Adjusted importance score.
        """
        if directive is None:
            return base_importance

        if directive["type"] == "forget":
            return self.FORGET_IMPORTANCE

        if directive["type"] == "remember":
            return min(base_importance + self.REMEMBER_BOOST, self.MAX_IMPORTANCE)

        # Unknown directive type — pass through
        return base_importance
