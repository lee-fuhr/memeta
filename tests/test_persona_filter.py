"""
Tests for persona-aware memory filtering (Spec 20).

Covers:
- Persona detection from project IDs
- Memory filtering by persona
- Memory tagging
- Relevant project lookup
- Custom persona management
- Edge cases (empty input, case-insensitivity, unknown projects)
"""

import pytest
from memory_system.persona_filter import PersonaFilter, DEFAULT_PERSONAS


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def pf():
    """Fresh PersonaFilter with default personas."""
    return PersonaFilter()


@pytest.fixture
def sample_memories():
    """Mix of tagged, untagged, and cross-persona memories."""
    return [
        {"content": "LFI client onboarding process", "project_id": "LFI", "persona": "business"},
        {"content": "FAISS indexing strategy", "project_id": "memory-system", "persona": "technical"},
        {"content": "Morning routine notes", "project_id": "health", "persona": "personal"},
        {"content": "Python best practices (untagged)", "project_id": "misc"},
        {"content": "Universal config note", "project_id": "LFI", "persona": "universal"},
    ]


# ── detect_persona ───────────────────────────────────────────────────────────


class TestDetectPersona:
    """Tests for PersonaFilter.detect_persona."""

    def test_detect_business_project(self, pf):
        """Known business project returns 'business'."""
        assert pf.detect_persona("LFI") == "business"

    def test_detect_technical_project(self, pf):
        """Known technical project returns 'technical'."""
        assert pf.detect_persona("memory-system") == "technical"

    def test_detect_personal_project(self, pf):
        """Known personal project returns 'personal'."""
        assert pf.detect_persona("health") == "personal"

    def test_detect_unknown_project(self, pf):
        """Unknown project returns 'universal'."""
        assert pf.detect_persona("random-thing") == "universal"

    def test_detect_case_insensitive(self, pf):
        """Detection is case-insensitive."""
        assert pf.detect_persona("lfi") == "business"
        assert pf.detect_persona("MEMORY-SYSTEM") == "technical"
        assert pf.detect_persona("Health") == "personal"

    def test_detect_empty_string(self, pf):
        """Empty project_id returns 'universal'."""
        assert pf.detect_persona("") == "universal"


# ── filter_memories ──────────────────────────────────────────────────────────


class TestFilterMemories:
    """Tests for PersonaFilter.filter_memories."""

    def test_filter_business_includes_matching_and_untagged(self, pf, sample_memories):
        """Filtering for 'business' returns business + untagged + universal memories."""
        result = pf.filter_memories(sample_memories, "business")
        contents = [m["content"] for m in result]
        assert "LFI client onboarding process" in contents
        assert "Python best practices (untagged)" in contents
        assert "Universal config note" in contents
        assert "FAISS indexing strategy" not in contents
        assert "Morning routine notes" not in contents

    def test_filter_technical(self, pf, sample_memories):
        """Filtering for 'technical' returns technical + untagged + universal."""
        result = pf.filter_memories(sample_memories, "technical")
        contents = [m["content"] for m in result]
        assert "FAISS indexing strategy" in contents
        assert "Python best practices (untagged)" in contents
        assert "Universal config note" in contents
        assert len(result) == 3

    def test_filter_empty_list(self, pf):
        """Filtering an empty list returns an empty list."""
        assert pf.filter_memories([], "business") == []

    def test_filter_all_untagged(self, pf):
        """All untagged memories pass through any persona filter."""
        memories = [
            {"content": "note one"},
            {"content": "note two"},
        ]
        result = pf.filter_memories(memories, "technical")
        assert len(result) == 2

    def test_filter_case_insensitive_persona(self, pf, sample_memories):
        """Persona matching on memories is case-insensitive."""
        mixed = [{"content": "biz note", "persona": "Business"}]
        result = pf.filter_memories(mixed, "business")
        assert len(result) == 1

    def test_filter_preserves_order(self, pf):
        """Filtered results preserve original order."""
        memories = [
            {"content": "a", "persona": "business"},
            {"content": "b"},
            {"content": "c", "persona": "business"},
        ]
        result = pf.filter_memories(memories, "business")
        assert [m["content"] for m in result] == ["a", "b", "c"]


# ── tag_memory ───────────────────────────────────────────────────────────────


class TestTagMemory:
    """Tests for PersonaFilter.tag_memory."""

    def test_tag_adds_persona_field(self, pf):
        """Tagging adds the persona key."""
        mem = {"content": "test memory", "project_id": "LFI"}
        tagged = pf.tag_memory(mem, "business")
        assert tagged["persona"] == "business"

    def test_tag_does_not_mutate_original(self, pf):
        """Tagging returns a new dict; original is untouched."""
        mem = {"content": "test memory"}
        tagged = pf.tag_memory(mem, "technical")
        assert "persona" not in mem
        assert tagged["persona"] == "technical"

    def test_tag_overwrites_existing(self, pf):
        """Tagging overwrites an existing persona value."""
        mem = {"content": "test", "persona": "personal"}
        tagged = pf.tag_memory(mem, "business")
        assert tagged["persona"] == "business"
        assert mem["persona"] == "personal"  # original unchanged


# ── get_relevant_projects ────────────────────────────────────────────────────


class TestGetRelevantProjects:
    """Tests for PersonaFilter.get_relevant_projects."""

    def test_get_business_projects(self, pf):
        """Returns business project list."""
        projects = pf.get_relevant_projects("business")
        assert "LFI" in projects
        assert "CogentAnalytics" in projects
        assert len(projects) == 6

    def test_get_unknown_persona(self, pf):
        """Unknown persona returns empty list."""
        assert pf.get_relevant_projects("nonexistent") == []

    def test_get_case_insensitive(self, pf):
        """Lookup is case-insensitive."""
        assert pf.get_relevant_projects("TECHNICAL") == pf.get_relevant_projects("technical")


# ── add_persona + get_all_personas ───────────────────────────────────────────


class TestPersonaManagement:
    """Tests for add_persona and get_all_personas."""

    def test_add_new_persona(self, pf):
        """Adding a new persona makes it detectable."""
        pf.add_persona("research", ["AcademicProject", "LabWork"])
        assert pf.detect_persona("AcademicProject") == "research"
        assert "research" in pf.get_all_personas()

    def test_add_updates_existing(self, pf):
        """Adding with an existing name replaces the project list."""
        pf.add_persona("business", ["NewCo"])
        projects = pf.get_relevant_projects("business")
        assert projects == ["NewCo"]
        assert pf.detect_persona("LFI") == "universal"  # no longer in business

    def test_get_all_returns_copy(self, pf):
        """get_all_personas returns a copy, not a reference."""
        all_personas = pf.get_all_personas()
        all_personas["business"].append("INJECTED")
        assert "INJECTED" not in pf.get_relevant_projects("business")

    def test_instances_are_isolated(self):
        """Mutations on one instance don't affect another."""
        pf1 = PersonaFilter()
        pf2 = PersonaFilter()
        pf1.add_persona("custom", ["Proj1"])
        assert "custom" not in pf2.get_all_personas()

    def test_default_personas_match_module_constant(self, pf):
        """Instance starts with exactly the default personas."""
        all_p = pf.get_all_personas()
        assert set(all_p.keys()) == set(DEFAULT_PERSONAS.keys())
        for name in DEFAULT_PERSONAS:
            assert all_p[name] == DEFAULT_PERSONAS[name]
