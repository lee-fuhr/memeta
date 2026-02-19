"""
Memory compressor — rule-based compression for memory content.

Removes filler words, hedging language, and redundant phrasing to produce
denser, more retrievable memory text. No LLM calls — pure regex/string ops.

Usage:
    from memory_system.memory_compressor import MemoryCompressor

    mc = MemoryCompressor()
    result = mc.compress("I think basically the API is essentially broken")
    # result['compressed'] == "The API is broken"
    # result['compression_ratio'] == 0.58  (smaller = more compressed)
"""

import math
import re
from typing import Dict, List


# ── Filler patterns (removed wholesale) ─────────────────────────────────────
# Each entry is compiled as a case-insensitive regex that matches the phrase
# surrounded by word boundaries (or start/end of string).

_FILLER_PHRASES = [
    # Filler adverbs
    r"\bbasically\b",
    r"\bessentially\b",
    r"\bactually\b",
    r"\breally\b",
    r"\bvery\b",
    r"\bquite\b",
    r"\bsomewhat\b",
    r"\brather\b",
    r"\bjust\b",
    # Hedging phrases
    r"\bi think\b",
    r"\bi believe\b",
    r"\bit seems like\b",
    r"\bit seems\b",
    r"\bas mentioned\b",
    r"\bas mentioned earlier\b",
    r"\bas mentioned before\b",
    r"\bgoing forward\b",
    r"\bat the end of the day\b",
    r"\bin my opinion\b",
    r"\bto be honest\b",
    r"\bfor what it's worth\b",
    r"\bin terms of\b",
    r"\bkind of\b",
    r"\bsort of\b",
    # Hedging modals
    r"\bmight be\b",
    r"\bcould be\b",
    r"\bpossibly\b",
    r"\bperhaps\b",
    r"\bmaybe\b",
    r"\bprobably\b",
]

_FILLER_RES = [re.compile(p, re.IGNORECASE) for p in _FILLER_PHRASES]

# Sentence-ending punctuation for splitting
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')

# Collapse multiple spaces into one
_MULTI_SPACE_RE = re.compile(r'  +')


class MemoryCompressor:
    """Rule-based memory content compressor."""

    def __init__(self) -> None:
        self._total_compressed: int = 0
        self._total_original_tokens: int = 0
        self._total_compressed_tokens: int = 0

    # ── Public API ───────────────────────────────────────────────────────────

    def extract_atomic_facts(self, content: str) -> List[str]:
        """
        Split content into atomic facts (one per sentence).

        - Splits on sentence boundaries (. ! ?)
        - Strips whitespace
        - Filters empty strings
        - Deduplicates (preserves order, case-insensitive)
        """
        if not content or not content.strip():
            return []

        # Split on sentence boundaries
        raw_sentences = _SENTENCE_SPLIT_RE.split(content.strip())

        facts: List[str] = []
        seen: set = set()

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            key = sentence.lower()
            if key in seen:
                continue

            seen.add(key)
            facts.append(sentence)

        return facts

    def compress(self, content: str) -> Dict:
        """
        Compress content by removing filler and hedging patterns.

        Returns:
            dict with keys:
                compressed: str — the compressed text
                facts: List[str] — atomic facts extracted from compressed text
                compression_ratio: float — len(compressed)/len(original), 0-1
                original_tokens: int — estimated token count of original
                compressed_tokens: int — estimated token count of compressed
        """
        if not content or not content.strip():
            return {
                "compressed": "",
                "facts": [],
                "compression_ratio": 1.0,
                "original_tokens": 0,
                "compressed_tokens": 0,
            }

        original = content.strip()
        original_tokens = self.estimate_tokens(original)

        # Apply filler removal
        compressed = original
        for pattern in _FILLER_RES:
            compressed = pattern.sub("", compressed)

        # Clean up artifacts: collapse whitespace, fix double punctuation
        compressed = _MULTI_SPACE_RE.sub(" ", compressed)
        compressed = compressed.strip()

        # Fix leading lowercase after filler removal left a dangling start
        # e.g. "I think the API is broken" -> " the API is broken" -> "The API is broken"
        if compressed:
            compressed = compressed[0].upper() + compressed[1:]

        # Fix sentences that now start with lowercase after a period
        compressed = re.sub(
            r'([.!?]\s+)([a-z])',
            lambda m: m.group(1) + m.group(2).upper(),
            compressed,
        )

        # Remove orphan commas at sentence start: ", The foo" -> "The foo"
        compressed = re.sub(r'^,\s*', '', compressed)
        compressed = re.sub(r'([.!?]\s+),\s*', r'\1', compressed)

        compressed_tokens = self.estimate_tokens(compressed)

        # Track stats
        self._total_compressed += 1
        self._total_original_tokens += original_tokens
        self._total_compressed_tokens += compressed_tokens

        # Compute ratio (guard against zero-length original)
        if len(original) > 0:
            ratio = len(compressed) / len(original)
        else:
            ratio = 1.0

        facts = self.extract_atomic_facts(compressed)

        return {
            "compressed": compressed,
            "facts": facts,
            "compression_ratio": round(ratio, 4),
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
        }

    def compress_batch(self, memories: List[Dict]) -> List[Dict]:
        """
        Compress a batch of memory dicts.

        Each memory dict must have a 'content' key. Adds 'compressed_content'
        key with the compression result dict.

        Args:
            memories: list of dicts, each with at least a 'content' key

        Returns:
            Same list with 'compressed_content' added to each dict
        """
        results = []
        for memory in memories:
            mem_copy = dict(memory)
            content = mem_copy.get("content", "")
            mem_copy["compressed_content"] = self.compress(content)
            results.append(mem_copy)
        return results

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Approximation: ceil(word_count * 1.3)
        """
        if not text or not text.strip():
            return 0
        word_count = len(text.split())
        return math.ceil(word_count * 1.3)

    def get_stats(self) -> Dict:
        """
        Return cumulative compression statistics.

        Returns:
            dict with keys:
                total_compressed: int — number of texts compressed
                avg_ratio: float — average compression ratio (0-1)
                total_tokens_saved: int — total estimated tokens saved
        """
        if self._total_compressed == 0:
            return {
                "total_compressed": 0,
                "avg_ratio": 0.0,
                "total_tokens_saved": 0,
            }

        # avg_ratio = total compressed chars / total original chars
        # But we track tokens, not chars. Use token ratio as proxy.
        if self._total_original_tokens > 0:
            avg_ratio = self._total_compressed_tokens / self._total_original_tokens
        else:
            avg_ratio = 1.0

        return {
            "total_compressed": self._total_compressed,
            "avg_ratio": round(avg_ratio, 4),
            "total_tokens_saved": self._total_original_tokens - self._total_compressed_tokens,
        }
