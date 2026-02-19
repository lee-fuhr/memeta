"""
Tests for entity extraction and linking system (Spec 18).

Covers:
- Entity extraction from text (persons, tools, projects)
- Entity linking to memories
- Alias management
- Case-insensitive lookups
- Stats and retrieval
"""

import sqlite3
import sys
import tempfile
import os
import pytest
from pathlib import Path

# The editable install points memory_system to the main worktree.
# Prepend this worktree's src/ so our new module is found first.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from entity_extractor import EntityExtractor


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_entities.db")


@pytest.fixture
def extractor(db_path):
    """Create an EntityExtractor with a temp database."""
    return EntityExtractor(db_path=db_path)


class TestSchemaCreation:
    """Test database schema initialization."""

    def test_creates_entities_table(self, extractor, db_path):
        """entities table exists with correct columns."""
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(entities)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "id" in columns
        assert "name" in columns
        assert "type" in columns
        assert "aliases_json" in columns
        assert "first_seen" in columns
        assert "last_seen" in columns

    def test_creates_memory_entities_table(self, extractor, db_path):
        """memory_entities junction table exists with correct columns."""
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(memory_entities)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "id" in columns
        assert "memory_id" in columns
        assert "entity_id" in columns
        assert "mention_text" in columns
        assert "position" in columns

    def test_entity_name_unique_nocase(self, extractor, db_path):
        """Entity name should be unique with case-insensitive collation."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO entities (name, type, aliases_json, first_seen, last_seen) "
            "VALUES ('Python', 'tool', '[]', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO entities (name, type, aliases_json, first_seen, last_seen) "
                "VALUES ('python', 'tool', '[]', '2026-01-01', '2026-01-01')"
            )
        conn.close()


class TestExtractEntities:
    """Test entity extraction from text."""

    def test_extract_person_names(self, extractor):
        """Extracts capitalized proper nouns as PERSON entities."""
        text = "I talked to Russell Hamilton about the project."
        entities = extractor.extract_entities(text)
        person_names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Russell Hamilton" in person_names

    def test_extract_at_mentions(self, extractor):
        """Extracts @mentions as PERSON entities."""
        text = "Assigned to @john_doe for review."
        entities = extractor.extract_entities(text)
        person_names = [e["name"] for e in entities if e["type"] == "person"]
        assert "john_doe" in person_names

    def test_extract_tool_names(self, extractor):
        """Extracts known tool names."""
        text = "We used Python and React to build the FAISS index."
        entities = extractor.extract_entities(text)
        tool_names = [e["name"] for e in entities if e["type"] == "tool"]
        assert "Python" in tool_names
        assert "React" in tool_names
        assert "FAISS" in tool_names

    def test_extract_project_names(self, extractor):
        """Extracts known project names."""
        text = "The Connection Lab and Total Rekall projects are progressing."
        entities = extractor.extract_entities(text)
        project_names = [e["name"] for e in entities if e["type"] == "project"]
        assert "Connection Lab" in project_names
        assert "Total Rekall" in project_names

    def test_extract_entities_returns_position(self, extractor):
        """Each extracted entity has a position (character offset)."""
        text = "Python is great."
        entities = extractor.extract_entities(text)
        tool_entities = [e for e in entities if e["name"] == "Python"]
        assert len(tool_entities) == 1
        assert tool_entities[0]["position"] == 0

    def test_extract_entities_returns_mention_text(self, extractor):
        """Each extracted entity includes original mention_text."""
        text = "Used FAISS for search."
        entities = extractor.extract_entities(text)
        faiss = [e for e in entities if e["name"] == "FAISS"]
        assert len(faiss) == 1
        assert faiss[0]["mention_text"] == "FAISS"

    def test_no_entities_in_empty_text(self, extractor):
        """Empty string yields no entities."""
        entities = extractor.extract_entities("")
        assert entities == []

    def test_deduplicates_within_text(self, extractor):
        """Same entity mentioned twice should produce two entries (different positions)."""
        text = "Python is used in Python projects."
        entities = extractor.extract_entities(text)
        python_entities = [e for e in entities if e["name"] == "Python"]
        assert len(python_entities) == 2
        assert python_entities[0]["position"] != python_entities[1]["position"]


class TestLinkMemory:
    """Test linking extracted entities to memory IDs."""

    def test_link_memory_returns_count(self, extractor):
        """link_memory returns the number of entities linked."""
        count = extractor.link_memory("mem-001", "Russell Hamilton used Python and React.")
        assert count >= 3  # person + 2 tools

    def test_link_memory_creates_entities(self, extractor):
        """After linking, entities exist in the database."""
        extractor.link_memory("mem-001", "Russell Hamilton used Python.")
        entity = extractor.get_entity("Russell Hamilton")
        assert entity is not None
        assert entity["type"] == "person"

    def test_link_memory_creates_junction_records(self, extractor, db_path):
        """After linking, memory_entities records exist."""
        extractor.link_memory("mem-001", "Python and React are tools.")
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT * FROM memory_entities WHERE memory_id = ?", ("mem-001",)
        ).fetchall()
        conn.close()
        assert len(rows) >= 2

    def test_link_memory_idempotent(self, extractor):
        """Linking same memory twice does not create duplicate junction records."""
        extractor.link_memory("mem-001", "Python is great.")
        extractor.link_memory("mem-001", "Python is great.")
        memories = extractor.get_memories_by_entity("Python")
        assert memories.count("mem-001") == 1

    def test_link_memory_updates_last_seen(self, extractor):
        """Linking updates the entity's last_seen timestamp."""
        extractor.link_memory("mem-001", "Python is great.")
        e1 = extractor.get_entity("Python")
        first_seen = e1["last_seen"]

        extractor.link_memory("mem-002", "Python is used here too.")
        e2 = extractor.get_entity("Python")
        assert e2["last_seen"] >= first_seen


class TestGetMemoriesByEntity:
    """Test querying memories by entity name."""

    def test_get_memories_by_entity(self, extractor):
        """Returns memory IDs linked to an entity."""
        extractor.link_memory("mem-001", "Russell Hamilton likes Python.")
        extractor.link_memory("mem-002", "Russell Hamilton also likes React.")
        memories = extractor.get_memories_by_entity("Russell Hamilton")
        assert "mem-001" in memories
        assert "mem-002" in memories

    def test_get_memories_case_insensitive(self, extractor):
        """Entity lookup is case-insensitive."""
        extractor.link_memory("mem-001", "Used Python for the project.")
        memories = extractor.get_memories_by_entity("python")
        assert "mem-001" in memories

    def test_get_memories_by_alias(self, extractor):
        """Can find memories by entity alias."""
        extractor.link_memory("mem-001", "Russell Hamilton said hello.")
        extractor.add_alias("Russell Hamilton", "Russ")
        memories = extractor.get_memories_by_entity("Russ")
        assert "mem-001" in memories

    def test_get_memories_no_matches(self, extractor):
        """Returns empty list for unknown entity."""
        memories = extractor.get_memories_by_entity("Nonexistent Person")
        assert memories == []


class TestAliases:
    """Test alias management."""

    def test_add_alias(self, extractor):
        """Adding an alias succeeds."""
        extractor.link_memory("mem-001", "Russell Hamilton is here.")
        result = extractor.add_alias("Russell Hamilton", "Russ")
        assert result is True

    def test_add_alias_nonexistent_entity(self, extractor):
        """Adding alias to nonexistent entity returns False."""
        result = extractor.add_alias("Nobody Here", "NH")
        assert result is False

    def test_alias_stored_in_entity(self, extractor):
        """Alias appears in entity's aliases list."""
        extractor.link_memory("mem-001", "Russell Hamilton is here.")
        extractor.add_alias("Russell Hamilton", "Russ")
        entity = extractor.get_entity("Russell Hamilton")
        assert "Russ" in entity["aliases"]


class TestGetEntity:
    """Test entity retrieval."""

    def test_get_entity_exists(self, extractor):
        """Returns entity dict with expected fields."""
        extractor.link_memory("mem-001", "Python is used.")
        entity = extractor.get_entity("Python")
        assert entity is not None
        assert entity["name"] == "Python"
        assert entity["type"] == "tool"
        assert "aliases" in entity
        assert "first_seen" in entity
        assert "last_seen" in entity

    def test_get_entity_case_insensitive(self, extractor):
        """get_entity is case-insensitive."""
        extractor.link_memory("mem-001", "Python is used.")
        entity = extractor.get_entity("python")
        assert entity is not None
        assert entity["name"] == "Python"

    def test_get_entity_not_found(self, extractor):
        """Returns None for unknown entity."""
        entity = extractor.get_entity("Unknown Entity")
        assert entity is None


class TestGetAllEntities:
    """Test listing all entities."""

    def test_get_all_entities(self, extractor):
        """Returns all entities in the database."""
        extractor.link_memory("mem-001", "Russell Hamilton used Python and React.")
        entities = extractor.get_all_entities()
        names = [e["name"] for e in entities]
        assert "Russell Hamilton" in names
        assert "Python" in names
        assert "React" in names

    def test_get_all_entities_empty(self, extractor):
        """Returns empty list when no entities exist."""
        entities = extractor.get_all_entities()
        assert entities == []


class TestGetStats:
    """Test statistics."""

    def test_stats_structure(self, extractor):
        """Stats dict has expected keys."""
        extractor.link_memory("mem-001", "Russell Hamilton used Python.")
        stats = extractor.get_stats()
        assert "total_entities" in stats
        assert "total_links" in stats
        assert "by_type" in stats

    def test_stats_counts(self, extractor):
        """Stats reflect actual data."""
        extractor.link_memory("mem-001", "Russell Hamilton used Python and React.")
        stats = extractor.get_stats()
        assert stats["total_entities"] >= 3
        assert stats["total_links"] >= 3
        assert stats["by_type"].get("person", 0) >= 1
        assert stats["by_type"].get("tool", 0) >= 2


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_word_capitalized_not_person(self, extractor):
        """Common English capitalized words at sentence start should not be persons.
        Only multi-word proper nouns or @mentions should be persons."""
        text = "The project is great. Very nice work."
        entities = extractor.extract_entities(text)
        person_names = [e["name"] for e in entities if e["type"] == "person"]
        # "The" and "Very" should NOT be treated as persons
        assert "The" not in person_names
        assert "Very" not in person_names

    def test_tool_inside_sentence(self, extractor):
        """Tools are found regardless of position in sentence."""
        text = "we built it using flask and sqlite for data."
        entities = extractor.extract_entities(text)
        tool_names = [e["name"].lower() for e in entities if e["type"] == "tool"]
        assert "flask" in tool_names
        assert "sqlite" in tool_names

    def test_multiple_entity_types_in_one_text(self, extractor):
        """All entity types can coexist in one extraction."""
        text = "Russell Hamilton used Python to build Total Rekall."
        entities = extractor.extract_entities(text)
        types = {e["type"] for e in entities}
        assert "person" in types
        assert "tool" in types
        assert "project" in types
