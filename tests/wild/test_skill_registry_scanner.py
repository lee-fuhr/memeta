"""Tests for skill registry scanner — scans skills directory and syncs to database."""

import pytest
import tempfile
import os
import json

from memory_system.wild.skill_registry_scanner import SkillRegistryScanner, SkillInfo


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def temp_skills_dir(tmp_path):
    """Create a temp skills directory with sample SKILL.md files."""
    # Create a sample skill
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# Test skill\n\nA skill for testing things.\n\n"
        "## Triggers\n- Testing code\n- Running tests\n"
    )
    # Create another skill
    skill_dir2 = tmp_path / "another-skill"
    skill_dir2.mkdir()
    (skill_dir2 / "SKILL.md").write_text(
        "# Another skill\n\nHelps with other tasks.\n\n"
        "## Capabilities\n- Data analysis\n- Report generation\n"
    )
    return tmp_path


@pytest.fixture
def scanner(temp_db, temp_skills_dir):
    """Create SkillRegistryScanner with temp database and skills directory."""
    return SkillRegistryScanner(skills_dir=temp_skills_dir, db_path=temp_db)


# --- Initialization ---

def test_initialization(temp_db, temp_skills_dir):
    """Scanner initializes with provided skills_dir and db_path."""
    scanner = SkillRegistryScanner(skills_dir=temp_skills_dir, db_path=temp_db)
    assert scanner.skills_dir == temp_skills_dir
    assert scanner.db is not None


# --- scan_skills ---

def test_scan_skills_finds_skills_with_skill_md(scanner):
    """scan_skills returns SkillInfo for directories containing SKILL.md."""
    skills = scanner.scan_skills()
    names = sorted(s.name for s in skills)
    assert names == ["another-skill", "test-skill"]
    assert all(isinstance(s, SkillInfo) for s in skills)


def test_scan_skills_ignores_dirs_without_skill_md(scanner, temp_skills_dir):
    """Directories without SKILL.md are ignored."""
    no_skill = temp_skills_dir / "no-skill-here"
    no_skill.mkdir()
    (no_skill / "README.md").write_text("# Not a skill\n")

    skills = scanner.scan_skills()
    names = [s.name for s in skills]
    assert "no-skill-here" not in names


def test_scan_skills_empty_directory(temp_db, tmp_path):
    """scan_skills returns empty list for empty directory."""
    empty_dir = tmp_path / "empty-skills"
    empty_dir.mkdir()
    scanner = SkillRegistryScanner(skills_dir=empty_dir, db_path=temp_db)
    assert scanner.scan_skills() == []


def test_scan_skills_nonexistent_directory(temp_db, tmp_path):
    """scan_skills returns empty list for nonexistent directory."""
    nonexistent = tmp_path / "does-not-exist"
    scanner = SkillRegistryScanner(skills_dir=nonexistent, db_path=temp_db)
    assert scanner.scan_skills() == []


# --- parse_skill_md ---

def test_parse_skill_md_basic(scanner, temp_skills_dir):
    """parse_skill_md extracts name, path, description, and keywords."""
    skill_md = temp_skills_dir / "test-skill" / "SKILL.md"
    info = scanner.parse_skill_md(skill_md)
    assert info.name == "test-skill"
    assert info.path == str(skill_md.parent)
    assert "testing" in info.description.lower()
    assert len(info.keywords) > 0


def test_parse_skill_md_with_triggers(scanner, temp_skills_dir):
    """parse_skill_md extracts keywords from Triggers section."""
    skill_md = temp_skills_dir / "test-skill" / "SKILL.md"
    info = scanner.parse_skill_md(skill_md)
    # Should extract keywords from trigger lines
    kw_lower = [k.lower() for k in info.keywords]
    assert any("test" in k for k in kw_lower)


def test_parse_skill_md_minimal_content(scanner, tmp_path):
    """parse_skill_md handles minimal content (just a title)."""
    skill_dir = tmp_path / "minimal-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Minimal skill\n")
    info = scanner.parse_skill_md(skill_dir / "SKILL.md")
    assert info.name == "minimal-skill"
    assert info.description == ""


def test_parse_skill_md_empty_file(scanner, tmp_path):
    """parse_skill_md handles empty SKILL.md files gracefully."""
    skill_dir = tmp_path / "empty-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("")
    info = scanner.parse_skill_md(skill_dir / "SKILL.md")
    assert info.name == "empty-skill"
    assert info.description == ""
    assert info.keywords == []


# --- _extract_description ---

def test_extract_description_first_paragraph(scanner):
    """Extract first non-empty paragraph after title as description."""
    text = "# My skill\n\nThis is the description paragraph.\n\n## Section\nMore content.\n"
    desc = scanner._extract_description(text)
    assert desc == "This is the description paragraph."


def test_extract_description_no_content(scanner):
    """Returns empty string when no description paragraph exists."""
    text = "# Just a title\n"
    desc = scanner._extract_description(text)
    assert desc == ""


# --- _extract_keywords ---

def test_extract_keywords_from_triggers(scanner):
    """Extract keywords from trigger-style content."""
    text = (
        "# My skill\n\nDescription here.\n\n"
        "## Triggers\n- Creating documents\n- Editing spreadsheets\n- Running reports\n"
    )
    keywords = scanner._extract_keywords(text)
    assert len(keywords) > 0
    kw_lower = [k.lower() for k in keywords]
    assert any("document" in k for k in kw_lower) or any("creating" in k for k in kw_lower)


def test_extract_keywords_deduplicates(scanner):
    """Extracted keywords contain no duplicates."""
    text = (
        "# Skill\n\nDescription.\n\n"
        "## Triggers\n- Testing code\n- Testing applications\n"
        "## Capabilities\n- Testing systems\n"
    )
    keywords = scanner._extract_keywords(text)
    assert len(keywords) == len(set(keywords))


# --- sync_to_db ---

def test_sync_to_db_new_skills(scanner):
    """sync_to_db inserts new skills and returns correct counts."""
    result = scanner.sync_to_db()
    assert result["new"] == 2
    assert result["updated"] == 0
    assert result["total"] == 2


def test_sync_to_db_updates_existing(scanner):
    """sync_to_db updates description/keywords on re-sync."""
    scanner.sync_to_db()

    # Modify a SKILL.md
    skill_md = scanner.skills_dir / "test-skill" / "SKILL.md"
    skill_md.write_text(
        "# Test skill\n\nUpdated description for testing.\n\n"
        "## Triggers\n- New trigger\n"
    )

    result = scanner.sync_to_db()
    assert result["updated"] == 2  # both re-synced (one changed, one unchanged)
    assert result["new"] == 0

    skill = scanner.get_skill("test-skill")
    assert "updated description" in skill["description"].lower()


def test_sync_to_db_preserves_use_count(scanner):
    """sync_to_db preserves use_count, last_used, and decay_score on re-sync."""
    scanner.sync_to_db()

    # Manually update use_count in the database
    import sqlite3
    conn = sqlite3.connect(str(scanner.db.db_path))
    conn.execute(
        "UPDATE skill_registry SET use_count = 42, last_used = '2026-02-20' WHERE skill_name = 'test-skill'"
    )
    conn.commit()
    conn.close()

    # Re-sync
    scanner.sync_to_db()

    skill = scanner.get_skill("test-skill")
    assert skill["use_count"] == 42
    assert skill["last_used"] == "2026-02-20"


def test_sync_to_db_empty_dir(temp_db, tmp_path):
    """sync_to_db returns zeros for empty skills directory."""
    empty_dir = tmp_path / "empty-skills"
    empty_dir.mkdir()
    scanner = SkillRegistryScanner(skills_dir=empty_dir, db_path=temp_db)
    result = scanner.sync_to_db()
    assert result == {"new": 0, "updated": 0, "total": 0}


# --- get_all_skills ---

def test_get_all_skills(scanner):
    """get_all_skills returns all skills from database after sync."""
    scanner.sync_to_db()
    skills = scanner.get_all_skills()
    assert len(skills) == 2
    names = sorted(s["skill_name"] for s in skills)
    assert names == ["another-skill", "test-skill"]


# --- get_skill ---

def test_get_skill_found(scanner):
    """get_skill returns a skill dict when found."""
    scanner.sync_to_db()
    skill = scanner.get_skill("test-skill")
    assert skill is not None
    assert skill["skill_name"] == "test-skill"
    assert "skill_path" in skill
    assert "description" in skill
    assert "keywords" in skill


def test_get_skill_not_found(scanner):
    """get_skill returns None when skill doesn't exist."""
    scanner.sync_to_db()
    assert scanner.get_skill("nonexistent-skill") is None
