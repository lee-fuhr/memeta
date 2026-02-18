"""
Tests for cluster-based morning briefing — generate session-start briefings
from memory clusters.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory_system.cluster_briefing import (
    ClusterBriefing,
    BriefingItem,
    MorningBriefing,
    generate_briefing,
    detect_cluster_divergence,
    format_briefing_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create a temp intelligence.db with cluster tables."""
    import sqlite3
    db = tmp_path / "intelligence.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE memory_clusters (
            cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_label TEXT NOT NULL,
            keywords TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            last_updated INTEGER NOT NULL,
            member_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE cluster_memberships (
            memory_id TEXT NOT NULL,
            cluster_id INTEGER NOT NULL,
            similarity_score REAL NOT NULL,
            added_at INTEGER NOT NULL,
            PRIMARY KEY (memory_id, cluster_id),
            FOREIGN KEY (cluster_id) REFERENCES memory_clusters(cluster_id)
        )
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def memory_dir(tmp_path):
    """Create a temp memory directory with test memories."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


def _seed_clusters(db_path, clusters_data):
    """Seed cluster tables with test data.

    clusters_data: list of (topic_label, keywords, member_count, member_ids)
    """
    import sqlite3
    now = int(datetime.now(tz=timezone.utc).timestamp())
    conn = sqlite3.connect(str(db_path))
    for topic, keywords, count, member_ids in clusters_data:
        cursor = conn.execute(
            "INSERT INTO memory_clusters (topic_label, keywords, created_at, last_updated, member_count) VALUES (?,?,?,?,?)",
            (topic, json.dumps(keywords), now, now, count),
        )
        cluster_id = cursor.lastrowid
        for mid in member_ids:
            conn.execute(
                "INSERT INTO cluster_memberships (memory_id, cluster_id, similarity_score, added_at) VALUES (?,?,?,?)",
                (mid, cluster_id, 0.85, now),
            )
    conn.commit()
    conn.close()


def _write_memory_file(mem_dir, memory_id, content, importance=0.7,
                       domain="testing", tags=None):
    """Write a memory .md file."""
    now = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tags_str = json.dumps(tags or ["testing"])
    fm = f"""---
id: {memory_id}
created: {now}
updated: {now}
reasoning: test
importance_weight: {importance}
confidence_score: 0.9
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: {domain}
status: active
scope: project
project_id: LFI
session_id: test-session
semantic_tags: {tags_str}
schema_version: 2
---
{content}"""
    (mem_dir / f"{memory_id}.md").write_text(fm)


# ---------------------------------------------------------------------------
# BriefingItem
# ---------------------------------------------------------------------------

class TestBriefingItem:
    def test_creation(self):
        item = BriefingItem(
            cluster_id=1,
            topic="Client strategy",
            keywords=["strategy", "clients"],
            member_count=12,
            top_memories=["mem1", "mem2"],
            summary="Key insights about client strategy.",
        )
        assert item.topic == "Client strategy"
        assert item.member_count == 12

    def test_to_dict(self):
        item = BriefingItem(
            cluster_id=1,
            topic="Client strategy",
            keywords=["strategy"],
            member_count=5,
            top_memories=["m1"],
            summary="Summary here.",
        )
        d = item.to_dict()
        assert d["topic"] == "Client strategy"
        assert d["member_count"] == 5
        assert "summary" in d


# ---------------------------------------------------------------------------
# MorningBriefing
# ---------------------------------------------------------------------------

class TestMorningBriefing:
    def test_empty_briefing(self):
        briefing = MorningBriefing(items=[], divergences=[], generated_at=datetime.now(tz=timezone.utc))
        assert len(briefing.items) == 0
        assert briefing.is_empty

    def test_non_empty(self):
        item = BriefingItem(1, "Topic", ["kw"], 5, [], "Summary")
        briefing = MorningBriefing(items=[item], divergences=[], generated_at=datetime.now(tz=timezone.utc))
        assert not briefing.is_empty
        assert len(briefing.items) == 1


# ---------------------------------------------------------------------------
# generate_briefing
# ---------------------------------------------------------------------------

class TestGenerateBriefing:
    def test_no_clusters_returns_empty(self, db_path, memory_dir):
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir)
        assert briefing.is_empty

    def test_with_clusters(self, db_path, memory_dir):
        _write_memory_file(memory_dir, "m1", "Client onboarding process needs improvement")
        _write_memory_file(memory_dir, "m2", "Weekly review cadence works well")
        _seed_clusters(db_path, [
            ("Client strategy", ["strategy", "clients"], 2, ["m1", "m2"]),
        ])
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir)
        assert len(briefing.items) == 1
        assert briefing.items[0].topic == "Client strategy"
        assert briefing.items[0].member_count == 2

    def test_multiple_clusters_sorted_by_size(self, db_path, memory_dir):
        for i in range(5):
            _write_memory_file(memory_dir, f"big-{i}", f"Big cluster content {i}")
        for i in range(2):
            _write_memory_file(memory_dir, f"small-{i}", f"Small cluster content {i}")

        _seed_clusters(db_path, [
            ("Small topic", ["small"], 2, ["small-0", "small-1"]),
            ("Big topic", ["big"], 5, ["big-0", "big-1", "big-2", "big-3", "big-4"]),
        ])
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir)
        assert len(briefing.items) == 2
        assert briefing.items[0].topic == "Big topic"
        assert briefing.items[0].member_count == 5

    def test_top_memories_limited(self, db_path, memory_dir):
        ids = []
        for i in range(10):
            mid = f"m-{i}"
            _write_memory_file(memory_dir, mid, f"Content {i}")
            ids.append(mid)

        _seed_clusters(db_path, [
            ("Large cluster", ["large"], 10, ids),
        ])
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir, top_n_memories=3)
        assert len(briefing.items[0].top_memories) <= 3

    def test_max_clusters_param(self, db_path, memory_dir):
        for i in range(15):
            _write_memory_file(memory_dir, f"m-{i}", f"Content {i}")

        clusters_data = []
        for i in range(5):
            clusters_data.append(
                (f"Topic {i}", [f"kw{i}"], 3, [f"m-{i*3}", f"m-{i*3+1}", f"m-{i*3+2}"])
            )
        _seed_clusters(db_path, clusters_data)
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir, max_clusters=3)
        assert len(briefing.items) == 3

    def test_summary_includes_content_preview(self, db_path, memory_dir):
        _write_memory_file(memory_dir, "m1", "Pipeline review shows strong Q2 momentum")
        _seed_clusters(db_path, [
            ("Pipeline review", ["pipeline", "Q2"], 1, ["m1"]),
        ])
        briefing = generate_briefing(db_path=db_path, memory_dir=memory_dir)
        assert "Pipeline" in briefing.items[0].summary or "pipeline" in briefing.items[0].summary.lower()


# ---------------------------------------------------------------------------
# detect_cluster_divergence
# ---------------------------------------------------------------------------

class TestDetectClusterDivergence:
    def test_no_previous_clusters(self, db_path):
        divergences = detect_cluster_divergence(db_path=db_path)
        assert divergences == []

    def test_detects_large_cluster(self, db_path, memory_dir):
        ids = [f"m-{i}" for i in range(20)]
        for mid in ids:
            _write_memory_file(memory_dir, mid, f"Content for {mid}")
        _seed_clusters(db_path, [
            ("Massive topic", ["big"], 20, ids),
        ])
        divergences = detect_cluster_divergence(db_path=db_path, split_threshold=15)
        assert len(divergences) >= 1
        assert "Massive topic" in divergences[0]

    def test_no_divergence_for_small_clusters(self, db_path, memory_dir):
        _write_memory_file(memory_dir, "m1", "Content 1")
        _write_memory_file(memory_dir, "m2", "Content 2")
        _seed_clusters(db_path, [
            ("Small topic", ["small"], 2, ["m1", "m2"]),
        ])
        divergences = detect_cluster_divergence(db_path=db_path, split_threshold=15)
        assert divergences == []


# ---------------------------------------------------------------------------
# format_briefing_text
# ---------------------------------------------------------------------------

class TestFormatBriefingText:
    def test_empty_briefing(self):
        briefing = MorningBriefing(items=[], divergences=[], generated_at=datetime.now(tz=timezone.utc))
        text = format_briefing_text(briefing)
        assert "No clusters" in text or "nothing" in text.lower() or "empty" in text.lower()

    def test_single_item(self):
        item = BriefingItem(1, "Client strategy", ["strategy"], 8, ["m1"], "Active thinking about strategy.")
        briefing = MorningBriefing(items=[item], divergences=[], generated_at=datetime.now(tz=timezone.utc))
        text = format_briefing_text(briefing)
        assert "Client strategy" in text
        assert "8" in text

    def test_includes_divergences(self):
        item = BriefingItem(1, "Topic A", ["a"], 5, [], "Summary")
        divergence = "Your thinking about 'Big topic' may have split — 20 memories, consider re-clustering."
        briefing = MorningBriefing(items=[item], divergences=[divergence], generated_at=datetime.now(tz=timezone.utc))
        text = format_briefing_text(briefing)
        assert "divergen" in text.lower() or "split" in text.lower()

    def test_multiple_items_formatted(self):
        items = [
            BriefingItem(1, "Topic A", ["a"], 10, [], "Summary A"),
            BriefingItem(2, "Topic B", ["b"], 5, [], "Summary B"),
        ]
        briefing = MorningBriefing(items=items, divergences=[], generated_at=datetime.now(tz=timezone.utc))
        text = format_briefing_text(briefing)
        assert "Topic A" in text
        assert "Topic B" in text


# ---------------------------------------------------------------------------
# ClusterBriefing (main interface)
# ---------------------------------------------------------------------------

class TestClusterBriefing:
    def test_init(self, db_path, memory_dir):
        cb = ClusterBriefing(db_path=db_path, memory_dir=memory_dir)
        assert cb is not None

    def test_get_briefing(self, db_path, memory_dir):
        _write_memory_file(memory_dir, "m1", "Content 1")
        _seed_clusters(db_path, [
            ("Test topic", ["test"], 1, ["m1"]),
        ])
        cb = ClusterBriefing(db_path=db_path, memory_dir=memory_dir)
        briefing = cb.get_briefing()
        assert not briefing.is_empty

    def test_get_formatted_briefing(self, db_path, memory_dir):
        _write_memory_file(memory_dir, "m1", "Content 1")
        _seed_clusters(db_path, [
            ("Test topic", ["test"], 1, ["m1"]),
        ])
        cb = ClusterBriefing(db_path=db_path, memory_dir=memory_dir)
        text = cb.get_formatted_briefing()
        assert isinstance(text, str)
        assert "Test topic" in text
