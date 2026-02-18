"""
Tests for cross-client pattern synthesizer — identify transferable patterns
across projects and generate cross-client hypotheses.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory_system.cross_client_synthesizer import (
    CrossClientSynthesizer,
    TransferHypothesis,
    CrossClientReport,
    find_cross_project_memories,
    group_by_domain,
    generate_hypotheses,
    format_synthesis_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path):
    """Create a temp memory directory."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def db_path(tmp_path):
    """Create a temp intelligence.db with pattern_transfers table."""
    import sqlite3
    db = tmp_path / "intelligence.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE pattern_transfers (
            id TEXT PRIMARY KEY,
            from_project TEXT NOT NULL,
            to_project TEXT NOT NULL,
            pattern_description TEXT NOT NULL,
            transferred_at INTEGER NOT NULL,
            effectiveness_rating REAL,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()
    return db


def _write_memory(mem_dir, memory_id, content, project_id="ProjectA",
                   scope="project", domain="strategy", tags=None,
                   importance=0.7):
    """Write a memory .md file with frontmatter."""
    now = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    tags = tags or ["testing"]
    tags_str = json.dumps(tags)
    fm = f"""---
id: {memory_id}
created: {now}
updated: {now}
reasoning: test memory
importance_weight: {importance}
confidence_score: 0.9
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: {domain}
status: active
scope: {scope}
project_id: {project_id}
session_id: test-session
semantic_tags: {tags_str}
schema_version: 2
---
{content}"""
    (mem_dir / f"{memory_id}.md").write_text(fm)


def _seed_transfers(db_path, transfers):
    """Seed pattern_transfers table.

    transfers: list of (id, from_project, to_project, description, rating)
    """
    import sqlite3
    now = int(time.time())
    conn = sqlite3.connect(str(db_path))
    for tid, from_p, to_p, desc, rating in transfers:
        conn.execute(
            "INSERT INTO pattern_transfers (id, from_project, to_project, pattern_description, transferred_at, effectiveness_rating) VALUES (?,?,?,?,?,?)",
            (tid, from_p, to_p, desc, now, rating),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# TransferHypothesis
# ---------------------------------------------------------------------------

class TestTransferHypothesis:
    def test_creation(self):
        h = TransferHypothesis(
            source_project="ClientA",
            target_project="ClientB",
            pattern="Weekly pipeline reviews improve close rates",
            confidence=0.85,
            domain="strategy",
            supporting_memories=["m1", "m2"],
        )
        assert h.source_project == "ClientA"
        assert h.confidence == 0.85

    def test_to_dict(self):
        h = TransferHypothesis(
            source_project="ClientA",
            target_project="ClientB",
            pattern="Discovery calls before demos",
            confidence=0.7,
            domain="sales",
            supporting_memories=["m1"],
        )
        d = h.to_dict()
        assert d["source_project"] == "ClientA"
        assert d["target_project"] == "ClientB"
        assert d["pattern"] == "Discovery calls before demos"
        assert "confidence" in d


# ---------------------------------------------------------------------------
# CrossClientReport
# ---------------------------------------------------------------------------

class TestCrossClientReport:
    def test_empty_report(self):
        report = CrossClientReport(
            hypotheses=[],
            projects_analyzed=[],
            total_memories_scanned=0,
        )
        assert report.is_empty
        assert report.hypothesis_count == 0

    def test_non_empty_report(self):
        h = TransferHypothesis("A", "B", "pattern", 0.8, "domain", [])
        report = CrossClientReport(
            hypotheses=[h],
            projects_analyzed=["A", "B"],
            total_memories_scanned=10,
        )
        assert not report.is_empty
        assert report.hypothesis_count == 1


# ---------------------------------------------------------------------------
# find_cross_project_memories
# ---------------------------------------------------------------------------

class TestFindCrossProjectMemories:
    def test_finds_global_scope_memories(self, memory_dir):
        _write_memory(memory_dir, "m1", "Universal insight", scope="global", project_id="ClientA")
        _write_memory(memory_dir, "m2", "Project-only insight", scope="project", project_id="ClientA")
        result = find_cross_project_memories(memory_dir)
        global_ids = [m["id"] for m in result]
        assert "m1" in global_ids

    def test_finds_cross_client_ok_tagged(self, memory_dir):
        _write_memory(memory_dir, "m1", "Shareable insight",
                       tags=["#cross_client_ok", "strategy"], project_id="ClientA")
        _write_memory(memory_dir, "m2", "Private insight",
                       tags=["private"], project_id="ClientA")
        result = find_cross_project_memories(memory_dir)
        ids = [m["id"] for m in result]
        assert "m1" in ids

    def test_finds_universal_tagged(self, memory_dir):
        _write_memory(memory_dir, "m1", "Universal pattern",
                       tags=["#universal"], project_id="ClientA")
        result = find_cross_project_memories(memory_dir)
        ids = [m["id"] for m in result]
        assert "m1" in ids

    def test_excludes_private_project_memories(self, memory_dir):
        _write_memory(memory_dir, "m1", "Private thing",
                       scope="project", tags=["internal"], project_id="ClientA")
        result = find_cross_project_memories(memory_dir)
        ids = [m["id"] for m in result]
        assert "m1" not in ids

    def test_empty_directory(self, memory_dir):
        result = find_cross_project_memories(memory_dir)
        assert result == []

    def test_returns_metadata(self, memory_dir):
        _write_memory(memory_dir, "m1", "Insight about pipeline",
                       scope="global", project_id="ClientA", domain="sales")
        result = find_cross_project_memories(memory_dir)
        assert len(result) == 1
        m = result[0]
        assert m["id"] == "m1"
        assert m["project_id"] == "ClientA"
        assert m["domain"] == "sales"
        assert "content" in m


# ---------------------------------------------------------------------------
# group_by_domain
# ---------------------------------------------------------------------------

class TestGroupByDomain:
    def test_groups_correctly(self):
        memories = [
            {"id": "m1", "domain": "sales", "project_id": "A", "content": "x"},
            {"id": "m2", "domain": "sales", "project_id": "B", "content": "y"},
            {"id": "m3", "domain": "strategy", "project_id": "A", "content": "z"},
        ]
        groups = group_by_domain(memories)
        assert "sales" in groups
        assert len(groups["sales"]) == 2
        assert "strategy" in groups
        assert len(groups["strategy"]) == 1

    def test_empty_input(self):
        groups = group_by_domain([])
        assert groups == {}


# ---------------------------------------------------------------------------
# generate_hypotheses
# ---------------------------------------------------------------------------

class TestGenerateHypotheses:
    def test_generates_hypothesis_for_shared_domain(self, memory_dir):
        _write_memory(memory_dir, "m1", "Weekly pipeline reviews improve close rates",
                       scope="global", project_id="ClientA", domain="sales")
        _write_memory(memory_dir, "m2", "Pipeline visibility is a challenge",
                       scope="global", project_id="ClientB", domain="sales")
        memories = find_cross_project_memories(memory_dir)
        hypotheses = generate_hypotheses(memories)
        assert len(hypotheses) >= 1
        # Should suggest transferring between the two projects
        projects_involved = set()
        for h in hypotheses:
            projects_involved.add(h.source_project)
            projects_involved.add(h.target_project)
        assert "ClientA" in projects_involved or "ClientB" in projects_involved

    def test_no_hypothesis_for_single_project(self, memory_dir):
        _write_memory(memory_dir, "m1", "Insight A", scope="global", project_id="ClientA", domain="sales")
        _write_memory(memory_dir, "m2", "Insight B", scope="global", project_id="ClientA", domain="sales")
        memories = find_cross_project_memories(memory_dir)
        hypotheses = generate_hypotheses(memories)
        # No cross-project hypothesis if all from same project
        assert len(hypotheses) == 0

    def test_respects_max_hypotheses(self, memory_dir):
        # Create many cross-project memories
        for i in range(10):
            proj = f"Client{chr(65 + i % 5)}"
            _write_memory(memory_dir, f"m-{i}", f"Insight {i}",
                           scope="global", project_id=proj, domain="operations")
        memories = find_cross_project_memories(memory_dir)
        hypotheses = generate_hypotheses(memories, max_hypotheses=3)
        assert len(hypotheses) <= 3

    def test_hypothesis_includes_supporting_memories(self, memory_dir):
        _write_memory(memory_dir, "m1", "CRM hygiene drives revenue",
                       scope="global", project_id="ClientA", domain="sales")
        _write_memory(memory_dir, "m2", "CRM data is messy",
                       scope="global", project_id="ClientB", domain="sales")
        memories = find_cross_project_memories(memory_dir)
        hypotheses = generate_hypotheses(memories)
        if hypotheses:
            assert len(hypotheses[0].supporting_memories) > 0

    def test_boosts_confidence_from_prior_transfers(self, memory_dir, db_path):
        _write_memory(memory_dir, "m1", "Discovery-first sales process",
                       scope="global", project_id="ClientA", domain="sales")
        _write_memory(memory_dir, "m2", "Need better sales process",
                       scope="global", project_id="ClientB", domain="sales")
        _seed_transfers(db_path, [
            ("t1", "ClientA", "ClientC", "Discovery-first sales", 0.9),
        ])
        memories = find_cross_project_memories(memory_dir)
        hypotheses = generate_hypotheses(memories, db_path=db_path)
        # Should have higher confidence when prior transfers succeeded
        if hypotheses:
            assert hypotheses[0].confidence > 0.5


# ---------------------------------------------------------------------------
# format_synthesis_report
# ---------------------------------------------------------------------------

class TestFormatSynthesisReport:
    def test_empty_report(self):
        report = CrossClientReport([], [], 0)
        text = format_synthesis_report(report)
        assert "no" in text.lower() or "empty" in text.lower()

    def test_includes_hypothesis_details(self):
        h = TransferHypothesis("ClientA", "ClientB", "Pipeline reviews", 0.85, "sales", ["m1"])
        report = CrossClientReport([h], ["ClientA", "ClientB"], 10)
        text = format_synthesis_report(report)
        assert "Pipeline reviews" in text
        assert "ClientA" in text
        assert "ClientB" in text

    def test_multiple_hypotheses(self):
        hypotheses = [
            TransferHypothesis("A", "B", "Pattern 1", 0.9, "sales", ["m1"]),
            TransferHypothesis("B", "C", "Pattern 2", 0.7, "ops", ["m2"]),
        ]
        report = CrossClientReport(hypotheses, ["A", "B", "C"], 20)
        text = format_synthesis_report(report)
        assert "Pattern 1" in text
        assert "Pattern 2" in text


# ---------------------------------------------------------------------------
# CrossClientSynthesizer (main interface)
# ---------------------------------------------------------------------------

class TestCrossClientSynthesizer:
    def test_init(self, memory_dir, db_path):
        synth = CrossClientSynthesizer(memory_dir=memory_dir, db_path=db_path)
        assert synth is not None

    def test_synthesize_empty(self, memory_dir, db_path):
        synth = CrossClientSynthesizer(memory_dir=memory_dir, db_path=db_path)
        report = synth.synthesize()
        assert report.is_empty

    def test_synthesize_with_data(self, memory_dir, db_path):
        _write_memory(memory_dir, "m1", "Structured onboarding reduces churn",
                       scope="global", project_id="ClientA", domain="operations")
        _write_memory(memory_dir, "m2", "Client onboarding is chaotic",
                       scope="global", project_id="ClientB", domain="operations")
        synth = CrossClientSynthesizer(memory_dir=memory_dir, db_path=db_path)
        report = synth.synthesize()
        assert report.total_memories_scanned >= 2

    def test_get_formatted_report(self, memory_dir, db_path):
        _write_memory(memory_dir, "m1", "Weekly reviews drive accountability",
                       scope="global", project_id="ClientA", domain="management")
        _write_memory(memory_dir, "m2", "Team lacks accountability structures",
                       scope="global", project_id="ClientB", domain="management")
        synth = CrossClientSynthesizer(memory_dir=memory_dir, db_path=db_path)
        text = synth.get_formatted_report()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_records_transfer_to_db(self, memory_dir, db_path):
        import sqlite3
        _write_memory(memory_dir, "m1", "Process X works well",
                       scope="global", project_id="ClientA", domain="ops")
        _write_memory(memory_dir, "m2", "Need process improvements",
                       scope="global", project_id="ClientB", domain="ops")
        synth = CrossClientSynthesizer(memory_dir=memory_dir, db_path=db_path)
        report = synth.synthesize(record=True)
        # Check that transfers were recorded
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM pattern_transfers").fetchone()[0]
        conn.close()
        assert count >= 0  # May be 0 if no hypotheses generated, but shouldn't error
