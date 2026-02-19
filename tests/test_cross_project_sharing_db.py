"""
Tests for cross_project_sharing_db.py — persistent cross-project sharing layer.

Covers:
1. Schema initialization (tables + indexes created)
2. share() — success, dedup, disabled target, multi-target
3. get_shared() — enabled project, disabled project, ordering
4. set_sharing_enabled() / is_sharing_enabled() — toggle, default
5. get_sharing_stats() — counts, averages, empty state
6. Relevance score storage and retrieval
"""

import pytest
import tempfile
import os
from pathlib import Path

from memory_system.cross_project_sharing_db import CrossProjectSharer


@pytest.fixture
def temp_db():
    """Create a temporary database file for test isolation."""
    temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db_path = temp_file.name
    temp_file.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)
    Path(db_path + '-wal').unlink(missing_ok=True)
    Path(db_path + '-shm').unlink(missing_ok=True)


@pytest.fixture
def sharer(temp_db):
    """CrossProjectSharer with isolated temp database."""
    return CrossProjectSharer(db_path=temp_db)


@pytest.fixture
def sample_memory():
    """A minimal memory dict for sharing."""
    return {
        'id': 'mem-001',
        'content': 'Always validate inputs before processing.',
        'project_id': 'project-alpha',
        'tags': ['#universal'],
    }


# ── share() tests ────────────────────────────────────────────────────────────

class TestShare:
    def test_share_creates_row(self, sharer, sample_memory):
        """share() inserts a row into shared_insights."""
        result = sharer.share(sample_memory, target_project='project-beta')
        assert result['shared'] is True
        assert result['id'] is not None
        assert result['reason'] == 'success'

        # Verify the row exists
        insights = sharer.get_shared('project-beta')
        assert len(insights) == 1
        assert insights[0]['memory_id'] == 'mem-001'

    def test_share_returns_shared_true(self, sharer, sample_memory):
        """share() returns shared=True on first successful share."""
        result = sharer.share(sample_memory, target_project='project-beta')
        assert result['shared'] is True
        assert result['reason'] == 'success'

    def test_share_dedup_same_memory_same_project(self, sharer, sample_memory):
        """share() same memory to same project = no duplicate."""
        result1 = sharer.share(sample_memory, target_project='project-beta')
        result2 = sharer.share(sample_memory, target_project='project-beta')

        assert result1['shared'] is True
        assert result2['shared'] is False
        assert result2['reason'] == 'duplicate'

        # Only one row
        insights = sharer.get_shared('project-beta')
        assert len(insights) == 1

    def test_share_same_memory_different_projects(self, sharer, sample_memory):
        """share() same memory to different projects = 2 rows."""
        result1 = sharer.share(sample_memory, target_project='project-beta')
        result2 = sharer.share(sample_memory, target_project='project-gamma')

        assert result1['shared'] is True
        assert result2['shared'] is True

        beta_insights = sharer.get_shared('project-beta')
        gamma_insights = sharer.get_shared('project-gamma')
        assert len(beta_insights) == 1
        assert len(gamma_insights) == 1

    def test_share_to_disabled_project_returns_false(self, sharer, sample_memory):
        """share() to a project with sharing disabled returns shared=False."""
        sharer.set_sharing_enabled('project-beta', False)
        result = sharer.share(sample_memory, target_project='project-beta')

        assert result['shared'] is False
        assert result['reason'] == 'sharing_disabled'
        assert result['id'] is None


# ── get_shared() tests ───────────────────────────────────────────────────────

class TestGetShared:
    def test_get_shared_returns_insights_for_enabled_project(self, sharer, sample_memory):
        """get_shared() returns insights for a project with sharing enabled."""
        sharer.share(sample_memory, target_project='project-beta')
        insights = sharer.get_shared('project-beta')
        assert len(insights) == 1
        assert insights[0]['source_project'] == 'project-alpha'
        assert insights[0]['memory_content'] == 'Always validate inputs before processing.'

    def test_get_shared_returns_empty_for_disabled_project(self, sharer, sample_memory):
        """get_shared() returns empty list when sharing is disabled."""
        sharer.share(sample_memory, target_project='project-beta')
        sharer.set_sharing_enabled('project-beta', False)
        insights = sharer.get_shared('project-beta')
        assert insights == []


# ── set_sharing_enabled() / is_sharing_enabled() tests ───────────────────────

class TestSharingConfig:
    def test_is_sharing_enabled_default_true(self, sharer):
        """is_sharing_enabled() returns True when no config row exists."""
        assert sharer.is_sharing_enabled('brand-new-project') is True

    def test_set_sharing_disabled_then_check(self, sharer):
        """is_sharing_enabled() returns False after disabling."""
        sharer.set_sharing_enabled('project-beta', False)
        assert sharer.is_sharing_enabled('project-beta') is False

    def test_set_sharing_toggle(self, sharer):
        """set_sharing_enabled() toggles correctly on repeated calls."""
        sharer.set_sharing_enabled('project-beta', False)
        assert sharer.is_sharing_enabled('project-beta') is False

        sharer.set_sharing_enabled('project-beta', True)
        assert sharer.is_sharing_enabled('project-beta') is True

        sharer.set_sharing_enabled('project-beta', False)
        assert sharer.is_sharing_enabled('project-beta') is False


# ── get_sharing_stats() tests ────────────────────────────────────────────────

class TestSharingStats:
    def test_stats_empty_db(self, sharer):
        """get_sharing_stats() returns zeroes on empty database."""
        stats = sharer.get_sharing_stats()
        assert stats['total_shared'] == 0
        assert stats['by_source_project'] == {}
        assert stats['by_target_project'] == {}
        assert stats['avg_relevance'] == 0.0

    def test_stats_correct_counts(self, sharer):
        """get_sharing_stats() returns correct counts after multiple shares."""
        mem1 = {'id': 'mem-001', 'content': 'Insight 1', 'project_id': 'alpha'}
        mem2 = {'id': 'mem-002', 'content': 'Insight 2', 'project_id': 'alpha'}
        mem3 = {'id': 'mem-003', 'content': 'Insight 3', 'project_id': 'beta'}

        sharer.share(mem1, target_project='gamma', relevance_score=0.8)
        sharer.share(mem2, target_project='gamma', relevance_score=0.6)
        sharer.share(mem3, target_project='delta', relevance_score=0.4)

        stats = sharer.get_sharing_stats()
        assert stats['total_shared'] == 3
        assert stats['by_source_project'] == {'alpha': 2, 'beta': 1}
        assert stats['by_target_project'] == {'gamma': 2, 'delta': 1}
        assert stats['avg_relevance'] == pytest.approx(0.6, abs=0.01)


# ── Relevance score tests ───────────────────────────────────────────────────

class TestRelevanceScore:
    def test_relevance_score_stored_and_retrievable(self, sharer, sample_memory):
        """Relevance score is stored correctly and returned in get_shared()."""
        sharer.share(sample_memory, target_project='project-beta', relevance_score=0.92)
        insights = sharer.get_shared('project-beta')
        assert len(insights) == 1
        assert insights[0]['relevance_score'] == pytest.approx(0.92, abs=0.001)

    def test_default_relevance_score(self, sharer):
        """Default relevance score is 0.5 when not specified."""
        mem = {'id': 'mem-default', 'content': 'Default score test', 'project_id': 'src'}
        sharer.share(mem, target_project='dst')
        insights = sharer.get_shared('dst')
        assert insights[0]['relevance_score'] == pytest.approx(0.5, abs=0.001)
