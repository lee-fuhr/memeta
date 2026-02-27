"""
Skill registry scanner — discovers skills from the filesystem and syncs to database.

Scans the skills directory (cfg.skills_dir), parses SKILL.md files to extract
metadata (name, description, keywords), and syncs discovered skills to the
skill_registry table in intelligence.db.

Usage:
    from memory_system.wild.skill_registry_scanner import SkillRegistryScanner

    scanner = SkillRegistryScanner()
    result = scanner.sync_to_db()
    print(f"Found {result['total']} skills ({result['new']} new)")

    all_skills = scanner.get_all_skills()
    skill = scanner.get_skill("copywriting")
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.wild.intelligence_db import IntelligenceDB


STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "this", "that", "not", "can", "will", "you", "your", "use", "using",
    "e.g", "etc", "i.e", "also", "when", "how", "what", "which", "if",
    "do", "does", "has", "have", "had", "been", "being", "its", "all",
    "more", "about", "into", "over", "such", "no", "so", "up", "out",
    "then", "than", "them", "they", "their", "these", "those", "each",
    "any", "some", "may", "should", "would", "could",
})


@dataclass
class SkillInfo:
    """Metadata extracted from a skill's SKILL.md file."""
    name: str
    path: str
    description: str
    keywords: list[str] = field(default_factory=list)


class SkillRegistryScanner:
    """Scans skills directory and syncs discovered skills to the database."""

    def __init__(self, skills_dir: Optional[Path] = None, db_path: Optional[Path] = None):
        self.skills_dir = skills_dir or cfg.skills_dir
        self.db = IntelligenceDB(db_path=db_path)

    def scan_skills(self) -> list[SkillInfo]:
        """Scan skills directory and return discovered skills.

        Looks for directories containing SKILL.md files.
        Returns empty list if directory doesn't exist or is empty.
        """
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            return []

        skills = []
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if skill_md.exists():
                skills.append(self.parse_skill_md(skill_md))
        return skills

    def parse_skill_md(self, skill_md_path: Path) -> SkillInfo:
        """Parse a SKILL.md file to extract skill metadata.

        Extracts: name (from directory name), description (first paragraph
        after title), keywords (from triggers, capabilities mentioned).
        """
        name = skill_md_path.parent.name
        path = str(skill_md_path.parent)

        try:
            text = skill_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return SkillInfo(name=name, path=path, description="", keywords=[])

        if not text.strip():
            return SkillInfo(name=name, path=path, description="", keywords=[])

        description = self._extract_description(text)
        keywords = self._extract_keywords(text)

        return SkillInfo(name=name, path=path, description=description, keywords=keywords)

    def sync_to_db(self) -> dict:
        """Scan skills and sync to database.

        Returns: {"new": count, "updated": count, "total": count}
        New skills get inserted. Existing skills get path/description/keywords
        updated. Preserves: use_count, last_used, decay_score, flagged_for_review.
        """
        skills = self.scan_skills()
        if not skills:
            return {"new": 0, "updated": 0, "total": 0}

        new_count = 0
        updated_count = 0
        cursor = self.db.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        for skill in skills:
            # Check if skill already exists
            row = cursor.execute(
                "SELECT id, use_count, last_used, decay_score, flagged_for_review, flag_dismissed_at, first_seen "
                "FROM skill_registry WHERE skill_name = ?",
                (skill.name,)
            ).fetchone()

            keywords_json = json.dumps(skill.keywords)

            if row is None:
                # New skill
                cursor.execute(
                    "INSERT INTO skill_registry "
                    "(skill_name, skill_path, description, keywords, first_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (skill.name, skill.path, skill.description, keywords_json, now)
                )
                new_count += 1
            else:
                # Update existing, preserving runtime fields
                cursor.execute(
                    "UPDATE skill_registry "
                    "SET skill_path = ?, description = ?, keywords = ? "
                    "WHERE skill_name = ?",
                    (skill.path, skill.description, keywords_json, skill.name)
                )
                updated_count += 1

        self.db.conn.commit()
        return {"new": new_count, "updated": updated_count, "total": new_count + updated_count}

    def get_all_skills(self) -> list[dict]:
        """Get all skills from database as dicts."""
        cursor = self.db.conn.cursor()
        rows = cursor.execute("SELECT * FROM skill_registry ORDER BY skill_name").fetchall()
        return [dict(row) for row in rows]

    def get_skill(self, skill_name: str) -> Optional[dict]:
        """Get a single skill by name from database."""
        cursor = self.db.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM skill_registry WHERE skill_name = ?",
            (skill_name,)
        ).fetchone()
        return dict(row) if row else None

    def _extract_description(self, text: str) -> str:
        """Extract description from SKILL.md.

        Returns the first non-empty paragraph after the title line (# heading).
        """
        lines = text.split("\n")
        found_title = False
        paragraph_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip until we find the title
            if not found_title:
                if stripped.startswith("# "):
                    found_title = True
                continue

            # After title, skip blank lines until first paragraph
            if not paragraph_lines:
                if not stripped:
                    continue
                # Stop if we hit another heading
                if stripped.startswith("#"):
                    break
                paragraph_lines.append(stripped)
            else:
                # Continue paragraph until blank line or heading
                if not stripped or stripped.startswith("#"):
                    break
                paragraph_lines.append(stripped)

        return " ".join(paragraph_lines)

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from SKILL.md content.

        Strategy: collect meaningful words from trigger descriptions,
        capability lists, and section headers. Filters common stop words
        and deduplicates.
        """
        keywords = []
        in_keyword_section = False

        for line in text.split("\n"):
            stripped = line.strip()

            # Detect keyword-rich sections
            if stripped.startswith("## "):
                section_name = stripped[3:].strip().lower()
                in_keyword_section = section_name in {
                    "triggers", "capabilities", "features", "use cases",
                    "when to use", "keywords",
                }
                continue

            # Extract words from list items in keyword sections
            if in_keyword_section and stripped.startswith("- "):
                item_text = stripped[2:].strip()
                words = re.findall(r'[a-zA-Z]{3,}', item_text.lower())
                for word in words:
                    if word not in STOP_WORDS and word not in keywords:
                        keywords.append(word)

        return keywords
