"""
Correction graduation - graduates confirmed corrections into CLAUDE.md rules.

When a correction memory reaches confirmations >= 3 (confirmed across 3+ separate
sessions), it "graduates" to become a permanent rule in CLAUDE.md. This ensures
the system learns from repeated user corrections.

Uses strip-and-regenerate pattern for idempotent CLAUDE.md updates, matching
the approach in correction_promoter.py for TOOLS.md.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional

from .memory_ts_client import Memory, MemoryTSClient

logger = logging.getLogger(__name__)

# Markers for the auto-generated block in CLAUDE.md
START_MARKER = "<!-- AUTO-GENERATED: corrections -->"
END_MARKER = "<!-- END AUTO-GENERATED: corrections -->"

# Default CLAUDE.md path
_claude_md_env = os.environ.get("MEMORY_SYSTEM_CLAUDE_MD")
DEFAULT_CLAUDE_MD_PATH: Optional[Path] = (
    Path(_claude_md_env) if _claude_md_env
    else Path.home() / "CC" / "LFI" / "CLAUDE.md"
)


class CorrectionGraduator:
    """
    Graduates confirmed correction memories into CLAUDE.md rules.

    When a correction memory reaches confirmations >= graduation_threshold
    (across separate sessions), it gets written as a permanent imperative
    rule in CLAUDE.md's learned corrections section.
    """

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
        claude_md_path: Optional[Path] = None,
        graduation_threshold: int = 3,
    ):
        """
        Args:
            memory_client: MemoryTSClient instance (preferred)
            memory_dir: Path to memory files (used if memory_client not provided)
            claude_md_path: Path to CLAUDE.md to update. Defaults to env var
                MEMORY_SYSTEM_CLAUDE_MD or ~/CC/LFI/CLAUDE.md
            graduation_threshold: Number of confirmations needed (default 3)
        """
        if memory_client is not None:
            self.memory_client = memory_client
        elif memory_dir is not None:
            self.memory_client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self.memory_client = MemoryTSClient()

        self.claude_md_path = Path(claude_md_path) if claude_md_path else DEFAULT_CLAUDE_MD_PATH
        self.graduation_threshold = graduation_threshold

    def find_graduation_candidates(self) -> List[Memory]:
        """
        Find correction memories eligible for graduation.

        Returns memories where:
        - context_type == "correction"
        - confirmations >= graduation_threshold
        - "#graduated" NOT in tags (prevent re-processing)

        Returns:
            List of Memory objects ready for graduation
        """
        all_memories = self.memory_client.list()

        candidates = []
        for mem in all_memories:
            if mem.context_type != "correction":
                continue
            if mem.confirmations < self.graduation_threshold:
                continue
            if "#graduated" in mem.tags:
                continue
            candidates.append(mem)

        return candidates

    def find_all_graduated(self) -> List[Memory]:
        """
        Find all already-graduated correction memories.

        Used by graduate() to include previously graduated rules when
        regenerating the CLAUDE.md block (strip-and-regenerate pattern).

        Returns:
            List of Memory objects with #graduated tag
        """
        all_memories = self.memory_client.list()

        return [
            mem for mem in all_memories
            if mem.context_type == "correction" and "#graduated" in mem.tags
        ]

    def format_rules(self, memories: List[Memory], categorize: bool = False) -> str:
        """
        Format graduated memories as imperative rules.

        Each memory.content gets converted to a clean imperative rule:
        - Strip "Correction: " prefix if present
        - Capitalize first letter (imperative form)
        - One rule per line, bulleted

        Args:
            memories: List of Memory objects to format
            categorize: Future seam for categorized output (ignored for now)

        Returns:
            Formatted markdown string with the corrections block
        """
        lines = []
        lines.append(START_MARKER)
        lines.append("## Learned corrections")
        lines.append("")

        for mem in memories:
            rule_text = mem.content

            # Strip "Correction: " prefix (case-insensitive)
            if rule_text.lower().startswith("correction: "):
                rule_text = rule_text[len("correction: "):]

            # Capitalize first letter for imperative form
            if rule_text:
                rule_text = rule_text[0].upper() + rule_text[1:]

            lines.append(f"- {rule_text}")

        lines.append(END_MARKER)

        return "\n".join(lines) + "\n"

    def update_claude_md(self, rules_content: str) -> bool:
        """
        Strip old corrections block and write new one to CLAUDE.md.

        Uses <!-- AUTO-GENERATED: corrections --> markers.
        If no markers exist, appends the block at the end of the file.
        Idempotent: calling twice with same content produces same result.

        Returns:
            True if CLAUDE.md was updated, False if no changes needed
        """
        if not self.claude_md_path.exists():
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}")
            return False

        existing = self.claude_md_path.read_text()

        if START_MARKER in existing and END_MARKER in existing:
            # Strip old block and replace
            start_idx = existing.index(START_MARKER)
            end_idx = existing.index(END_MARKER) + len(END_MARKER)

            # Consume trailing newline if present
            if end_idx < len(existing) and existing[end_idx] == "\n":
                end_idx += 1

            new_content = existing[:start_idx] + rules_content + existing[end_idx:]
        else:
            # Append block at end
            separator = "" if existing.endswith("\n") else "\n"
            new_content = existing + separator + "\n" + rules_content

        if new_content == existing:
            return False

        self.claude_md_path.write_text(new_content)
        return True

    def mark_graduated(self, memories: List[Memory]) -> int:
        """
        Add #graduated tag to graduated memories.

        Returns:
            Count of memories newly tagged
        """
        count = 0
        for mem in memories:
            if "#graduated" in mem.tags:
                continue

            new_tags = mem.tags + ["#graduated"]
            self.memory_client.update(mem.id, tags=new_tags)
            count += 1

        return count

    def graduate(self) -> dict:
        """
        Full graduation pipeline:
        1. Find candidates (confirmations >= threshold, not already graduated)
        2. Collect previously graduated corrections
        3. Format ALL graduated corrections as rules (strip-and-regenerate)
        4. Update CLAUDE.md
        5. Mark new candidates as graduated

        Returns:
            dict with keys: candidates_found, rules_written, claude_md_updated
        """
        candidates = self.find_graduation_candidates()

        if not candidates:
            return {
                "candidates_found": 0,
                "rules_written": 0,
                "claude_md_updated": False,
            }

        # Include previously graduated corrections in the regenerated block
        previously_graduated = self.find_all_graduated()
        all_rules = previously_graduated + candidates

        rules_content = self.format_rules(all_rules)
        updated = self.update_claude_md(rules_content)

        if updated:
            graduated_count = self.mark_graduated(candidates)
        else:
            graduated_count = 0

        return {
            "candidates_found": len(candidates),
            "rules_written": len(all_rules),
            "claude_md_updated": updated,
        }
