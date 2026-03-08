"""BibleImporter — Build Bible → Memeta memory import.

Parses a Build Bible markdown file and imports principles (1.x),
patterns (2.x), and anti-patterns (6.x) as typed memories.

Section type mapping:
  1.x  → principle    (importance 0.90)
  2.x  → pattern      (importance 0.85)
  6.x  → anti_pattern (importance 0.90)
  7.x+ → skipped (operational reference)
"""
import logging
import re
from pathlib import Path

from memory_system.importers.base import BaseImporter, ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory

logger = logging.getLogger(__name__)


# Section number prefix → section type
_SECTION_TYPE_MAP: dict[int, str] = {
    1: "principle",
    2: "pattern",
    6: "anti_pattern",
}

_IMPORTANCE_MAP: dict[str, float] = {
    "principle": 0.90,
    "pattern": 0.85,
    "anti_pattern": 0.90,
}

# Matches "### N.M Heading text" where N is the top-level section number
_SUBSECTION_RE = re.compile(r"^###\s+(\d+)\.(\d+)\s+(.+)$", re.MULTILINE)


class BibleImporter(BaseImporter):
    """Import Build Bible sections as typed memories."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_source(self, path: Path) -> ImportResult:
        """Parse the Bible file and write memories for known sections."""
        text = path.read_text(encoding="utf-8")
        sections = self._parse_bible_sections(text)

        imported = 0
        skipped = 0
        errors: list[str] = []
        memories: list[Memory] = []

        for section in sections:
            content = section["content"]
            if self._is_duplicate(content):
                skipped += 1
                continue

            try:
                mem = self._client.create(
                    content=content,
                    project_id=self.project_id,
                    importance=_IMPORTANCE_MAP[section["section_type"]],
                    context_type=section["section_type"],
                    tags=self._build_tags(section),
                )
                memories.append(mem)
                imported += 1
            except Exception as exc:
                logger.warning("Failed to import section %s: %s", section["section_id"], exc)
                errors.append(f"Section {section['section_id']}: {exc}")

        return ImportResult(imported=imported, skipped=skipped, errors=errors, memories=memories)

    def dry_run(self, path: Path) -> ImportPreview:
        """Preview what would be imported without writing anything."""
        text = path.read_text(encoding="utf-8")
        sections = self._parse_bible_sections(text)

        would_import = 0
        would_skip = 0
        sample: list[Memory] = []

        for section in sections:
            if self._is_duplicate(section["content"]):
                would_skip += 1
            else:
                would_import += 1
                if len(sample) < 3:
                    sample.append(Memory(
                        id=f"preview-{section['section_id']}",
                        content=section["content"],
                        importance=_IMPORTANCE_MAP[section["section_type"]],
                        tags=self._build_tags(section),
                        project_id=self.project_id,
                        context_type=section["section_type"],
                    ))

        return ImportPreview(would_import=would_import, would_skip=would_skip, sample_memories=sample)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_bible_sections(self, text: str) -> list[dict]:
        """Extract importable sections from Bible markdown text.

        Returns a list of dicts with keys:
          section_id, section_type, heading, content
        """
        matches = list(_SUBSECTION_RE.finditer(text))
        sections = []

        for match_idx, match in enumerate(matches):
            section_type = _SECTION_TYPE_MAP.get(int(match.group(1)))
            if section_type is None:
                continue

            section_id = f"{match.group(1)}.{match.group(2)}"
            heading = f"{section_id} {match.group(3)}"

            # Content = text between this heading and the next ### heading (or EOF)
            start = match.end()
            end = matches[match_idx + 1].start() if match_idx + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            if not content:
                continue

            sections.append({
                "section_id": section_id,
                "section_type": section_type,
                "heading": heading,
                "content": content,
            })

        return sections

    def _detect_section_type(self, heading: str) -> str | None:
        """Return section type string for a heading, or None if not importable.

        Heading must start with "N.M " where N maps to a known section type.
        """
        m = re.match(r"^(\d+)\.\d+\s", heading)
        if not m:
            return None
        top_num = int(m.group(1))
        return _SECTION_TYPE_MAP.get(top_num)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tags(self, section: dict) -> list[str]:
        return [
            "#source:bible",
            f"#section:{section['section_id']}",
            f"#type:{section['section_type']}",
        ]
