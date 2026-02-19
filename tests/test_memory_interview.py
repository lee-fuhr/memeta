"""
Tests for memory interview — stale review, contradiction review, decision rating.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory_system.memory_interview import InterviewQuestion, MemoryInterviewer
from memory_system.memory_ts_client import MemoryTSClient, Memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_memory_file(
    mem_dir: Path,
    memory_id: str,
    content: str = "test content",
    importance: float = 0.7,
    confidence_score: float = 0.9,
    days_old: int = 100,
    status: str = "active",
):
    """Write a memory .md file with controlled age and attributes."""
    now = datetime.now()
    created = now - timedelta(days=days_old)

    tags_str = '["#test"]'
    fm = f"""---
id: {memory_id}
created: {created.isoformat()}
updated: {created.isoformat()}
reasoning: test
importance_weight: {importance}
confidence_score: {confidence_score}
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: testing
status: {status}
scope: project
project_id: LFI
session_id: test-session
semantic_tags: {tags_str}
retrieval_weight: {importance}
schema_version: 2
---

{content}"""
    (mem_dir / f"{memory_id}.md").write_text(fm)


def _setup_decision_db(db_path: Path, decisions: list[dict]) -> None:
    """Insert test decisions into a decision_journal table."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision TEXT NOT NULL,
            options_considered TEXT NOT NULL,
            chosen_option TEXT NOT NULL,
            rationale TEXT NOT NULL,
            context TEXT,
            project_id TEXT,
            session_id TEXT,
            decided_at TEXT NOT NULL,
            outcome TEXT,
            outcome_success BOOLEAN,
            outcome_recorded_at TEXT,
            commitment_id TEXT,
            tags TEXT
        )
    """)
    for d in decisions:
        conn.execute(
            "INSERT INTO decision_journal "
            "(decision, options_considered, chosen_option, rationale, context, "
            "project_id, session_id, decided_at, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                d.get('decision', 'test decision'),
                d.get('options_considered', '["A", "B"]'),
                d.get('chosen_option', 'A'),
                d.get('rationale', 'seemed right'),
                d.get('context', 'test context'),
                d.get('project_id', 'LFI'),
                d.get('session_id', 'test-session'),
                d.get('decided_at', '2025-01-01'),
                d.get('outcome', None),
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path):
    """Create temp memory directory."""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def db_path(tmp_path):
    """Create temp intelligence DB path."""
    return tmp_path / "intelligence.db"


@pytest.fixture
def interviewer(memory_dir, db_path):
    """Create a MemoryInterviewer with temp storage."""
    return MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)


# ---------------------------------------------------------------------------
# generate_interview() — stale memories
# ---------------------------------------------------------------------------

class TestGenerateStaleReview:
    def test_stale_memories_produce_stale_review_questions(self, memory_dir, db_path):
        """Stale high-importance memories generate stale_review questions."""
        _write_memory_file(memory_dir, "old-important", importance=0.8, days_old=120)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_qs = [q for q in questions if q.category == 'stale_review']
        assert len(stale_qs) >= 1
        assert "still true" in stale_qs[0].question_text

    def test_fresh_memories_excluded(self, memory_dir, db_path):
        """Memories updated recently are NOT flagged as stale."""
        _write_memory_file(memory_dir, "fresh", importance=0.8, days_old=10)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_qs = [q for q in questions if q.category == 'stale_review']
        assert len(stale_qs) == 0

    def test_low_importance_excluded(self, memory_dir, db_path):
        """Memories below MIN_IMPORTANCE are excluded from stale review."""
        _write_memory_file(memory_dir, "old-low", importance=0.3, days_old=120)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_qs = [q for q in questions if q.category == 'stale_review']
        assert len(stale_qs) == 0


# ---------------------------------------------------------------------------
# generate_interview() — contradictions
# ---------------------------------------------------------------------------

class TestGenerateContradiction:
    def test_low_confidence_produces_contradiction_questions(self, memory_dir, db_path):
        """Low-confidence memories generate contradiction questions."""
        _write_memory_file(
            memory_dir, "contradicted", confidence_score=0.3,
            importance=0.6, days_old=10,
        )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        contra_qs = [q for q in questions if q.category == 'contradiction']
        assert len(contra_qs) >= 1
        assert "contradicted" in contra_qs[0].question_text

    def test_high_confidence_excluded(self, memory_dir, db_path):
        """Memories with confidence >= 0.5 are NOT contradiction candidates."""
        _write_memory_file(
            memory_dir, "confident", confidence_score=0.8,
            importance=0.6, days_old=10,
        )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        contra_qs = [q for q in questions if q.category == 'contradiction']
        assert len(contra_qs) == 0


# ---------------------------------------------------------------------------
# generate_interview() — decision rating
# ---------------------------------------------------------------------------

class TestGenerateDecisionRating:
    def test_unrated_decisions_produce_decision_rating_questions(self, memory_dir, db_path):
        """Decisions with NULL outcome generate decision_rating questions."""
        _setup_decision_db(db_path, [
            {'decision': 'Use FAISS over Annoy', 'outcome': None},
        ])
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        dec_qs = [q for q in questions if q.category == 'decision_rating']
        assert len(dec_qs) >= 1
        assert "outcome" in dec_qs[0].question_text

    def test_rated_decisions_excluded(self, memory_dir, db_path):
        """Decisions that already have outcomes are excluded."""
        _setup_decision_db(db_path, [
            {'decision': 'Already rated', 'outcome': 'It worked great'},
        ])
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        dec_qs = [q for q in questions if q.category == 'decision_rating']
        assert len(dec_qs) == 0


# ---------------------------------------------------------------------------
# generate_interview() — mixed + limits
# ---------------------------------------------------------------------------

class TestGenerateMixed:
    def test_mixed_sources_produce_mixed_questions(self, memory_dir, db_path):
        """All 3 sources together produce questions from each category."""
        _write_memory_file(memory_dir, "stale1", importance=0.8, days_old=120)
        _write_memory_file(memory_dir, "contra1", confidence_score=0.2, importance=0.6, days_old=5)
        _setup_decision_db(db_path, [
            {'decision': 'Pick Postgres', 'outcome': None},
        ])
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        categories = {q.category for q in questions}
        assert 'stale_review' in categories
        assert 'contradiction' in categories
        assert 'decision_rating' in categories

    def test_max_questions_limit(self, memory_dir, db_path):
        """Never returns more than MAX_QUESTIONS."""
        for i in range(10):
            _write_memory_file(
                memory_dir, f"stale{i}", importance=0.8, days_old=120 + i,
            )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        assert len(questions) <= MemoryInterviewer.MAX_QUESTIONS

    def test_no_candidates_returns_empty(self, memory_dir, db_path):
        """No stale, no contradictions, no unrated decisions -> empty list."""
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)
        questions = interviewer.generate_interview()
        assert questions == []

    def test_redistributes_slots_when_category_empty(self, memory_dir, db_path):
        """If contradictions have 0 candidates, their slots go to stale."""
        for i in range(5):
            _write_memory_file(
                memory_dir, f"stale{i}", importance=0.8, days_old=120 + i,
            )
        # No contradicted memories, no unrated decisions
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        assert len(questions) == 5  # All 5 slots filled by stale
        assert all(q.category == 'stale_review' for q in questions)


# ---------------------------------------------------------------------------
# process_response() — stale review
# ---------------------------------------------------------------------------

class TestProcessStaleResponse:
    def test_yes_confirms_memory(self, memory_dir, db_path):
        """Responding 'yes' to stale review confirms the memory."""
        _write_memory_file(memory_dir, "stale-confirm", importance=0.8, days_old=120)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_q = next(q for q in questions if q.category == 'stale_review')

        result = interviewer.process_response(stale_q.id, "yes")
        assert result['action'] == 'confirmed'
        assert result['memory_id'] == 'stale-confirm'

    def test_no_archives_memory(self, memory_dir, db_path):
        """Responding 'no' to stale review archives the memory."""
        _write_memory_file(memory_dir, "stale-archive", importance=0.8, days_old=120)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_q = next(q for q in questions if q.category == 'stale_review')

        result = interviewer.process_response(stale_q.id, "no")
        assert result['action'] == 'archived'
        # Verify file moved to archived/
        assert not (memory_dir / "stale-archive.md").exists()
        assert (memory_dir / "archived" / "stale-archive.md").exists()

    def test_freetext_updates_memory(self, memory_dir, db_path):
        """Free-text response updates the memory content."""
        _write_memory_file(
            memory_dir, "stale-update", importance=0.8, days_old=120,
            content="Old content",
        )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        stale_q = next(q for q in questions if q.category == 'stale_review')

        result = interviewer.process_response(stale_q.id, "Actually it changed to X")
        assert result['action'] == 'updated'
        # Verify content changed
        updated = interviewer.client.get("stale-update")
        assert "Actually it changed to X" in updated.content


# ---------------------------------------------------------------------------
# process_response() — contradiction
# ---------------------------------------------------------------------------

class TestProcessContradictionResponse:
    def test_keep_confirms_memory(self, memory_dir, db_path):
        """Responding 'keep' confirms the contradicted memory."""
        _write_memory_file(
            memory_dir, "contra-keep", confidence_score=0.3,
            importance=0.6, days_old=10,
        )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        contra_q = next(q for q in questions if q.category == 'contradiction')

        result = interviewer.process_response(contra_q.id, "keep")
        assert result['action'] == 'confirmed'

    def test_archive_archives_memory(self, memory_dir, db_path):
        """Responding 'archive' removes the contradicted memory."""
        _write_memory_file(
            memory_dir, "contra-archive", confidence_score=0.2,
            importance=0.6, days_old=10,
        )
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        contra_q = next(q for q in questions if q.category == 'contradiction')

        result = interviewer.process_response(contra_q.id, "archive")
        assert result['action'] == 'archived'


# ---------------------------------------------------------------------------
# process_response() — decision rating
# ---------------------------------------------------------------------------

class TestProcessDecisionResponse:
    def test_records_outcome(self, memory_dir, db_path):
        """Decision rating records the outcome in decision_journal."""
        _setup_decision_db(db_path, [
            {'decision': 'Use SQLite', 'outcome': None},
        ])
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        dec_q = next(q for q in questions if q.category == 'decision_rating')

        result = interviewer.process_response(dec_q.id, "It worked great, good decision")
        assert result['action'] == 'rated'

        # Verify DB was updated
        row = interviewer.db.conn.execute(
            "SELECT outcome, outcome_success FROM decision_journal WHERE id = ?",
            (int(dec_q.memory_ids[0]),)
        ).fetchone()
        assert row is not None
        assert "worked great" in row['outcome']
        assert row['outcome_success'] == 1  # True -> 1 in SQLite


# ---------------------------------------------------------------------------
# save_interview()
# ---------------------------------------------------------------------------

class TestSaveInterview:
    def test_creates_file_in_interviews_dir(self, memory_dir, db_path):
        """save_interview() creates a dated file in interviews/ directory."""
        _write_memory_file(memory_dir, "stale1", importance=0.8, days_old=120)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        path = interviewer.save_interview(questions)

        assert path.exists()
        assert path.parent.name == "interviews"
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in path.name

    def test_file_contains_all_questions(self, memory_dir, db_path):
        """Saved interview file contains text of all questions."""
        _write_memory_file(memory_dir, "s1", importance=0.8, days_old=120)
        _write_memory_file(memory_dir, "s2", importance=0.7, days_old=150)
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)

        questions = interviewer.generate_interview()
        path = interviewer.save_interview(questions)
        content = path.read_text()

        for q in questions:
            assert q.question_text in content

    def test_empty_questions_still_saves(self, memory_dir, db_path):
        """Saving an empty question list still creates a valid file."""
        interviewer = MemoryInterviewer(memory_dir=memory_dir, db_path=db_path)
        path = interviewer.save_interview([])
        assert path.exists()
        content = path.read_text()
        assert "Questions: 0" in content


# ---------------------------------------------------------------------------
# InterviewQuestion dataclass
# ---------------------------------------------------------------------------

class TestInterviewQuestion:
    def test_has_all_required_fields(self):
        """InterviewQuestion has all required fields."""
        q = InterviewQuestion(
            id="q-1",
            category="stale_review",
            question_text="Is this still true?",
            context="Some memory content",
            memory_ids=["mem-123"],
            created_at="2026-01-01T00:00:00",
        )
        assert q.id == "q-1"
        assert q.category == "stale_review"
        assert q.question_text == "Is this still true?"
        assert q.context == "Some memory content"
        assert q.memory_ids == ["mem-123"]
        assert q.created_at == "2026-01-01T00:00:00"
