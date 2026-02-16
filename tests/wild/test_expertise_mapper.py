"""Tests for F59: Expertise Mapping"""

import pytest
import tempfile
import os

from memory_system.wild.expertise_mapper import ExpertiseMapper


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def mapper(temp_db):
    return ExpertiseMapper(temp_db)


def test_mapper_initialization(mapper):
    assert mapper is not None


def test_record_expertise(mapper):
    mapper.record_expertise("Agent1", "python", memory_count=5, quality=4.0)


def test_record_expertise_updates(mapper):
    mapper.record_expertise("Agent1", "python", memory_count=5, quality=4.0)
    mapper.record_expertise("Agent1", "python", memory_count=3, quality=3.0)
    
    expertise = mapper.get_agent_expertise("Agent1")
    assert len(expertise) == 1
    assert expertise[0]["memory_count"] == 8


def test_get_expert_for_domain_none(mapper):
    expert = mapper.get_expert_for_domain("rust")
    assert expert is None


def test_get_expert_for_domain_exists(mapper):
    mapper.record_expertise("Agent1", "python", memory_count=5, quality=4.0)
    mapper.record_expertise("Agent2", "python", memory_count=3, quality=3.0)
    
    expert = mapper.get_expert_for_domain("python")
    assert expert == "Agent1"  # Higher score


def test_map_expertise_empty(mapper):
    expertise_map = mapper.map_expertise()
    assert expertise_map == {}


def test_map_expertise_with_data(mapper):
    mapper.record_expertise("Agent1", "python")
    mapper.record_expertise("Agent1", "javascript")
    mapper.record_expertise("Agent2", "rust")
    
    expertise_map = mapper.map_expertise()
    assert len(expertise_map) == 2
    assert len(expertise_map["Agent1"]) == 2


def test_get_agent_expertise_empty(mapper):
    expertise = mapper.get_agent_expertise("NonExistent")
    assert expertise == []


def test_get_agent_expertise_with_data(mapper):
    mapper.record_expertise("Agent1", "python", memory_count=5, quality=4.0)
    mapper.record_expertise("Agent1", "javascript", memory_count=2, quality=3.0)
    
    expertise = mapper.get_agent_expertise("Agent1")
    assert len(expertise) == 2
    assert expertise[0]["domain"] == "python"  # Higher score first


def test_get_statistics(mapper):
    mapper.record_expertise("Agent1", "python")
    mapper.record_expertise("Agent2", "javascript")
    
    stats = mapper.get_statistics()
    assert stats["total_agents"] == 2
    assert stats["total_domains"] == 2
    assert stats["total_expertise_records"] == 2
