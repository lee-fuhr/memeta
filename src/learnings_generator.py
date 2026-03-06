"""
CLAUDE.md learnings generator — surfaces accumulated learnings as auto-generated rules.

Selects high-importance, high-confidence, recently-accessed memories and
groups them by knowledge_domain into a formatted section for CLAUDE.md.
Uses strip-and-regenerate pattern (same as correction_graduator.py).
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from memory_system.memory_ts_client import Memory, MemoryTSClient

logger = logging.getLogger(__name__)

# Markers for the auto-generated block
START_MARKER = "<!-- AUTO-GENERATED: learnings -->"
END_MARKER = "<!-- END AUTO-GENERATED: learnings -->"

# Default CLAUDE.md path
_claude_md_env = os.environ.get("MEMORY_SYSTEM_CLAUDE_MD")
DEFAULT_CLAUDE_MD_PATH: Optional[Path] = (
    Path(_claude_md_env) if _claude_md_env
    else None
)


class LearningsGenerator:
    """
    Generates CLAUDE.md learnings section from accumulated memories.
    """

    def __init__(
        self,
        memory_client: Optional[MemoryTSClient] = None,
        memory_dir: Optional[Path] = None,
        claude_md_path: Optional[Path] = None,
        min_importance: float = 0.7,
        min_confidence: float = 0.7,
    ):
        if memory_client is not None:
            self.memory_client = memory_client
        elif memory_dir is not None:
            self.memory_client = MemoryTSClient(memory_dir=memory_dir)
        else:
            self.memory_client = MemoryTSClient()

        self.claude_md_path = Path(claude_md_path) if claude_md_path else DEFAULT_CLAUDE_MD_PATH
        self.min_importance = min_importance
        self.min_confidence = min_confidence

    def select_memories(self) -> list[Memory]:
        """
        Select memories qualifying for the learnings section.

        Criteria:
        - importance >= min_importance (default 0.7)
        - confidence_score >= min_confidence (default 0.7)
        - Not tagged #graduated (already in corrections section)
        - status == "active"
        - context_type != "correction" (handled by correction_graduator)
        """
        all_memories = self.memory_client.list()
        selected = []

        for mem in all_memories:
            if mem.importance < self.min_importance:
                continue
            if mem.confidence_score < self.min_confidence:
                continue
            if "#graduated" in mem.tags:
                continue
            if mem.status != "active":
                continue
            if mem.context_type == "correction":
                continue
            selected.append(mem)

        return selected

    def group_by_category(self, memories: list[Memory]) -> dict[str, list[Memory]]:
        """Group memories by knowledge_domain."""
        groups: dict[str, list[Memory]] = {}
        for mem in memories:
            domain = mem.knowledge_domain or "general"
            groups.setdefault(domain, []).append(mem)

        # Sort within each group by importance (highest first)
        for domain in groups:
            groups[domain].sort(key=lambda m: m.importance, reverse=True)

        return groups

    def deduplicate(self, memories: list[Memory]) -> list[Memory]:
        """Remove near-duplicate memories. Keep highest importance version."""
        seen_hashes: dict[str, Memory] = {}
        for mem in memories:
            # Normalize: lowercase, strip whitespace
            normalized = mem.content.strip().lower()
            # Use first 200 chars for near-dupe detection
            key = hashlib.sha256(normalized[:200].encode()).hexdigest()[:16]

            if key in seen_hashes:
                # Keep the one with higher importance
                if mem.importance > seen_hashes[key].importance:
                    seen_hashes[key] = mem
            else:
                seen_hashes[key] = mem

        return list(seen_hashes.values())

    def format_memory(self, memory: Memory) -> str:
        """Format a single memory based on its domain."""
        domain = memory.knowledge_domain or "general"
        content = memory.content.strip()

        if domain == "preferences":
            return f"- **Preference:** {content}"
        elif domain == "workflow":
            return f"- **Workflow:** {content}"
        elif domain in ("technical", "development", "testing", "deployment"):
            return f"- `{domain}`: {content}"
        elif domain == "learnings":
            return f"- {content}"
        else:
            return f"- {content}"

    def format_section(self, groups: dict[str, list[Memory]]) -> str:
        """Format the full learnings section content."""
        lines = [START_MARKER, "", "### Accumulated learnings", ""]

        # Sort groups for consistent output
        for domain in sorted(groups.keys()):
            memories = groups[domain]
            if not memories:
                continue

            # Domain heading
            heading = domain.replace("_", " ")
            heading = heading[0].upper() + heading[1:] if heading else heading
            lines.append(f"**{heading}**")
            lines.append("")

            for mem in memories:
                lines.append(self.format_memory(mem))

            lines.append("")

        lines.append(END_MARKER)
        return "\n".join(lines)

    def generate(self) -> str:
        """Full pipeline: select -> deduplicate -> group -> format. Returns section content."""
        memories = self.select_memories()
        if not memories:
            return f"{START_MARKER}\n\n*No learnings qualifying yet.*\n\n{END_MARKER}"

        deduped = self.deduplicate(memories)
        groups = self.group_by_category(deduped)
        return self.format_section(groups)

    def apply_to_claude_md(self, dry_run: bool = False) -> dict:
        """
        Generate and write learnings section to CLAUDE.md.

        Uses strip-and-regenerate pattern:
        1. If markers exist, replace content between them
        2. If no markers, append section at end
        3. If dry_run, return content without writing

        Returns dict with 'content', 'memory_count', 'written' (bool).
        """
        memories = self.select_memories()
        deduped = self.deduplicate(memories)

        if not memories:
            section = f"{START_MARKER}\n\n*No learnings qualifying yet.*\n\n{END_MARKER}"
        else:
            groups = self.group_by_category(deduped)
            section = self.format_section(groups)

        result = {
            "content": section,
            "memory_count": len(deduped),
            "written": False,
        }

        if dry_run:
            return result

        if self.claude_md_path is None or not self.claude_md_path.exists():
            result["error"] = f"CLAUDE.md not found: {self.claude_md_path}"
            return result

        existing = self.claude_md_path.read_text(encoding="utf-8")

        start_idx = existing.find(START_MARKER)
        end_idx = existing.find(END_MARKER)

        if start_idx != -1 and end_idx != -1:
            # Replace between markers (inclusive of markers themselves)
            new_content = existing[:start_idx] + section + existing[end_idx + len(END_MARKER):]
        else:
            # Append at end
            new_content = existing.rstrip() + "\n\n" + section + "\n"

        self.claude_md_path.write_text(new_content, encoding="utf-8")
        result["written"] = True

        return result
