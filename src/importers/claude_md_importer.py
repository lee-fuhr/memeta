"""Import rules and instructions from CLAUDE.md files."""
import re
from pathlib import Path

from memory_system.importers.base import BaseImporter, ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory


class ClaudeMdImporter(BaseImporter):
    """Parses CLAUDE.md structure into individual memory entries."""

    def import_source(self, path: Path) -> ImportResult:
        """Parse CLAUDE.md and create memories from rules/instructions.

        Reads the file, splits by headings, extracts individual rules
        from each section, and creates memory entries.
        """
        content = path.read_text(encoding="utf-8")
        sections = self._parse_sections(content)

        imported = 0
        skipped = 0
        errors: list[str] = []
        memories: list[Memory] = []

        for section in sections:
            if self._is_auto_generated(section["content"]):
                skipped += 1
                continue

            rules = self._extract_rules(section["content"])
            if not rules:
                continue

            heading = section["heading"]
            domain = self._domain_from_heading(heading)
            heading_slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            tags = ["#source:claude-md", f"#heading:{heading_slug}"]

            for rule in rules:
                if self._is_duplicate(rule):
                    skipped += 1
                    continue

                try:
                    mem = self._client.create(
                        content=rule,
                        project_id=self.project_id,
                        tags=tags,
                        importance=0.85,
                        context_type="directive",
                        knowledge_domain=domain,
                    )
                    memories.append(mem)
                    imported += 1
                except Exception as exc:
                    errors.append(f"{heading}: {exc}")

        return ImportResult(
            imported=imported,
            skipped=skipped,
            errors=errors,
            memories=memories,
        )

    def dry_run(self, path: Path) -> ImportPreview:
        """Preview what would be imported without writing."""
        content = path.read_text(encoding="utf-8")
        sections = self._parse_sections(content)

        would_import = 0
        would_skip = 0
        samples: list[Memory] = []

        for section in sections:
            if self._is_auto_generated(section["content"]):
                would_skip += 1
                continue

            rules = self._extract_rules(section["content"])
            heading = section["heading"]
            domain = self._domain_from_heading(heading)
            heading_slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            tags = ["#source:claude-md", f"#heading:{heading_slug}"]

            for rule in rules:
                if self._is_duplicate(rule):
                    would_skip += 1
                    continue

                would_import += 1
                if len(samples) < 5:
                    samples.append(
                        Memory(
                            id=f"preview-{would_import}",
                            content=rule,
                            importance=0.85,
                            tags=tags,
                            project_id=self.project_id,
                            context_type="directive",
                            knowledge_domain=domain,
                        )
                    )

        return ImportPreview(
            would_import=would_import,
            would_skip=would_skip,
            sample_memories=samples,
        )

    def _parse_sections(self, content: str) -> list[dict]:
        """Parse markdown into sections with headings and content."""
        sections: list[dict] = []
        current_heading = ""
        current_level = 0
        current_content: list[str] = []

        for line in content.split("\n"):
            if line.startswith("## ") or line.startswith("### "):
                # Save previous section
                if current_content:
                    sections.append(
                        {
                            "heading": current_heading,
                            "level": current_level,
                            "content": "\n".join(current_content),
                        }
                    )
                level = 2 if line.startswith("## ") else 3
                current_heading = line.lstrip("#").strip()
                current_level = level
                current_content = []
            else:
                current_content.append(line)

        # Don't forget the last section
        if current_content:
            sections.append(
                {
                    "heading": current_heading,
                    "level": current_level,
                    "content": "\n".join(current_content),
                }
            )

        return sections

    def _extract_rules(self, section_content: str) -> list[str]:
        """Extract individual rules/instructions from section content."""
        rules: list[str] = []
        for line in section_content.split("\n"):
            line = line.strip()
            # Bullet points (- or *)
            if line.startswith("- ") or line.startswith("* "):
                rule = line[2:].strip()
                if len(rule) > 10:
                    rules.append(rule)
            # Bold rules (full line wrapped in **)
            elif line.startswith("**") and line.endswith("**"):
                rule = line.strip("*").strip()
                if len(rule) > 10:
                    rules.append(rule)
        return rules

    def _is_auto_generated(self, content: str) -> bool:
        """Check if section contains auto-generated markers."""
        return "<!-- AUTO-GENERATED" in content

    def _domain_from_heading(self, heading: str) -> str:
        """Map heading text to knowledge domain."""
        heading_lower = heading.lower()
        if any(w in heading_lower for w in ["code", "dev", "implement"]):
            return "development"
        if any(w in heading_lower for w in ["test", "qa", "quality"]):
            return "testing"
        if any(w in heading_lower for w in ["doc", "readme", "changelog"]):
            return "documentation"
        if any(w in heading_lower for w in ["deploy", "ci", "cd", "release"]):
            return "deployment"
        if any(w in heading_lower for w in ["config", "setup", "install"]):
            return "configuration"
        return "workflow"
