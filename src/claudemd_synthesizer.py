"""
CLAUDE.md synthesizer - auto-generates rules from 5 signal sources.

Collects rules from corrections, directives, frustrations, preferences, and
workflows. Deduplicates near-duplicate rules by word overlap, formats them
grouped by category, and updates CLAUDE.md using strip-and-regenerate for
idempotent writes.

Uses different markers from correction_graduator to avoid conflicts:
  <!-- AUTO-GENERATED: learnings -->
  <!-- END AUTO-GENERATED: learnings -->
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol

from .correction_graduator import CorrectionGraduator
from .memory_ts_client import MemoryTSClient

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """A synthesized rule extracted from memory signals."""
    text: str
    category: str       # "correction", "directive", "frustration", "preference", "workflow"
    confidence: float   # 0.0-1.0
    source_count: int   # How many sources support this rule
    source_type: str    # Which RuleSource generated it


class RuleSource(Protocol):
    """Protocol for rule extraction sources."""
    def extract_rules(self) -> List[Rule]: ...


class CorrectionRuleSource:
    """Wraps CorrectionGraduator.find_graduation_candidates()"""

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
    ):
        if memory_client is not None:
            self._graduator = CorrectionGraduator(memory_client=memory_client)
        elif memory_dir is not None:
            self._graduator = CorrectionGraduator(memory_dir=memory_dir)
        else:
            self._graduator = CorrectionGraduator()

    def extract_rules(self) -> List[Rule]:
        candidates = self._graduator.find_graduation_candidates()
        rules = []
        for mem in candidates:
            confidence = min(1.0, 0.5 + (mem.confirmations * 0.05))
            rules.append(Rule(
                text=mem.content,
                category="correction",
                confidence=confidence,
                source_count=1,
                source_type="CorrectionRuleSource",
            ))
        return rules


class DirectiveRuleSource:
    """Queries memories with directive or behavioral context_type."""

    DIRECTIVE_PATTERNS = ("always", "never", "must", "don't")

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
    ):
        if memory_client is not None:
            self._client = memory_client
        elif memory_dir is not None:
            self._client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self._client = MemoryTSClient()

    def extract_rules(self) -> List[Rule]:
        all_memories = self._client.list()
        rules = []
        for mem in all_memories:
            if mem.context_type not in ("directive", "behavioral"):
                continue
            content_lower = mem.content.lower()
            if not any(pat in content_lower for pat in self.DIRECTIVE_PATTERNS):
                continue
            confidence = min(1.0, 0.6 + (mem.confirmations * 0.05))
            rules.append(Rule(
                text=mem.content,
                category="directive",
                confidence=confidence,
                source_count=1,
                source_type="DirectiveRuleSource",
            ))
        return rules


class FrustrationRuleSource:
    """Queries frustration patterns with 5+ confirmations."""

    FRUSTRATION_THRESHOLD = 5

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
    ):
        if memory_client is not None:
            self._client = memory_client
        elif memory_dir is not None:
            self._client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self._client = MemoryTSClient()

    def extract_rules(self) -> List[Rule]:
        all_memories = self._client.list()
        rules = []
        for mem in all_memories:
            if "#frustration" not in mem.tags:
                continue
            if mem.confirmations < self.FRUSTRATION_THRESHOLD:
                continue
            confidence = min(1.0, 0.5 + (mem.confirmations * 0.04))
            rules.append(Rule(
                text=mem.content,
                category="frustration",
                confidence=confidence,
                source_count=1,
                source_type="FrustrationRuleSource",
            ))
        return rules


class PreferenceRuleSource:
    """Queries memories with context_type=='preference', confirmations>=3."""

    PREFERENCE_THRESHOLD = 3

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
    ):
        if memory_client is not None:
            self._client = memory_client
        elif memory_dir is not None:
            self._client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self._client = MemoryTSClient()

    def extract_rules(self) -> List[Rule]:
        all_memories = self._client.list()
        rules = []
        for mem in all_memories:
            if mem.context_type != "preference":
                continue
            if mem.confirmations < self.PREFERENCE_THRESHOLD:
                continue
            confidence = min(1.0, 0.5 + (mem.confirmations * 0.05))
            rules.append(Rule(
                text=mem.content,
                category="preference",
                confidence=confidence,
                source_count=1,
                source_type="PreferenceRuleSource",
            ))
        return rules


class WorkflowRuleSource:
    """Queries memories with context_type=='workflow', confirmations>=3."""

    WORKFLOW_THRESHOLD = 3

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
    ):
        if memory_client is not None:
            self._client = memory_client
        elif memory_dir is not None:
            self._client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self._client = MemoryTSClient()

    def extract_rules(self) -> List[Rule]:
        all_memories = self._client.list()
        rules = []
        for mem in all_memories:
            if mem.context_type != "workflow":
                continue
            if mem.confirmations < self.WORKFLOW_THRESHOLD:
                continue
            confidence = min(1.0, 0.5 + (mem.confirmations * 0.05))
            rules.append(Rule(
                text=mem.content,
                category="workflow",
                confidence=confidence,
                source_count=1,
                source_type="WorkflowRuleSource",
            ))
        return rules


def _word_overlap(text_a: str, text_b: str) -> float:
    """Calculate word overlap ratio between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    smaller = min(len(words_a), len(words_b))
    return len(intersection) / smaller


class CLAUDEMDSynthesizer:
    """Synthesizes rules from multiple sources into CLAUDE.md."""

    START_MARKER = "<!-- AUTO-GENERATED: learnings -->"
    END_MARKER = "<!-- END AUTO-GENERATED: learnings -->"

    OVERLAP_THRESHOLD = 0.7

    # Display order for categories
    CATEGORY_ORDER = ["correction", "directive", "frustration", "preference", "workflow"]

    def __init__(
        self,
        sources: List[RuleSource],
        claude_md_path: Path,
    ):
        self.sources = sources
        self.claude_md_path = Path(claude_md_path)

    def synthesize(self) -> dict:
        """Full pipeline: collect -> dedup -> format -> update.

        Returns dict with keys: rules_count, categories, updated (bool)
        """
        rules = self.collect_rules()
        rules = self.deduplicate(rules)

        if not rules:
            return {
                "rules_count": 0,
                "categories": [],
                "updated": False,
            }

        formatted = self.format_rules(rules)
        updated = self.update_claude_md(formatted)

        categories = sorted(set(r.category for r in rules))
        return {
            "rules_count": len(rules),
            "categories": categories,
            "updated": updated,
        }

    def collect_rules(self) -> List[Rule]:
        """Gather rules from all sources."""
        all_rules: List[Rule] = []
        for source in self.sources:
            try:
                all_rules.extend(source.extract_rules())
            except Exception as e:
                logger.warning("Rule source %s failed: %s", type(source).__name__, e)
        return all_rules

    def deduplicate(self, rules: List[Rule]) -> List[Rule]:
        """Remove near-duplicate rules.

        Word overlap > 0.7 = duplicate. Keep higher confidence version.
        """
        if not rules:
            return []

        # Sort by confidence descending so we keep higher confidence first
        sorted_rules = sorted(rules, key=lambda r: r.confidence, reverse=True)
        kept: List[Rule] = []

        for rule in sorted_rules:
            is_dup = False
            for existing in kept:
                if _word_overlap(rule.text, existing.text) > self.OVERLAP_THRESHOLD:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(rule)

        return kept

    def format_rules(self, rules: List[Rule]) -> str:
        """Format rules grouped by category.

        Each category gets a ### heading.
        Rules listed as bullet points with confidence indicator.
        """
        if not rules:
            return ""

        # Group by category
        by_category: dict[str, List[Rule]] = {}
        for rule in rules:
            by_category.setdefault(rule.category, []).append(rule)

        lines: List[str] = []
        for cat in self.CATEGORY_ORDER:
            cat_rules = by_category.get(cat)
            if not cat_rules:
                continue
            lines.append(f"### {cat.capitalize()}")
            lines.append("")
            for rule in cat_rules:
                pct = f"{int(rule.confidence * 100)}%"
                lines.append(f"- {rule.text} ({pct})")
            lines.append("")

        return "\n".join(lines)

    def update_claude_md(self, content: str) -> bool:
        """Strip-and-regenerate between markers.

        If markers don't exist, append them at end of file.
        Returns True if file was modified.
        """
        if not self.claude_md_path.exists():
            logger.warning("CLAUDE.md not found at %s", self.claude_md_path)
            return False

        existing = self.claude_md_path.read_text()

        # Build the full block with markers
        block = f"{self.START_MARKER}\n{content}{self.END_MARKER}\n"

        if self.START_MARKER in existing and self.END_MARKER in existing:
            start_idx = existing.index(self.START_MARKER)
            end_idx = existing.index(self.END_MARKER) + len(self.END_MARKER)
            # Consume trailing newline if present
            if end_idx < len(existing) and existing[end_idx] == "\n":
                end_idx += 1
            new_content = existing[:start_idx] + block + existing[end_idx:]
        else:
            separator = "" if existing.endswith("\n") else "\n"
            new_content = existing + separator + "\n" + block

        if new_content == existing:
            return False

        self.claude_md_path.write_text(new_content)
        return True
