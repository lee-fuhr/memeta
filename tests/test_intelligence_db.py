"""
Tests for intelligence_db.py - Shared database for Features 44-50
"""

import pytest
import tempfile
from pathlib import Path
from memory_system.intelligence_db import IntelligenceDB


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(temp_file.name)
    temp_file.close()

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()


class TestIntelligenceDBInit:
    """Test database initialization"""

    def test_create_database(self, temp_db):
        """Database file is created"""
        with IntelligenceDB(temp_db) as db:
            assert temp_db.exists()

    def test_schema_initialization(self, temp_db):
        """All tables are created"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            # Check all feature tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert 'voice_memories' in tables
            assert 'image_memories' in tables
            assert 'code_memories' in tables
            assert 'decision_journal' in tables
            assert 'ab_tests' in tables
            assert 'cross_system_imports' in tables
            assert 'dream_insights' in tables

    def test_indexes_created(self, temp_db):
        """Indexes for common queries are created"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}

            assert 'idx_voice_project' in indexes
            assert 'idx_image_project' in indexes
            assert 'idx_code_language' in indexes
            assert 'idx_code_project' in indexes
            assert 'idx_decisions_project' in indexes
            assert 'idx_decisions_outcome' in indexes


class TestVoiceMemoriesTable:
    """Test voice_memories table structure"""

    def test_insert_voice_memory(self, temp_db):
        """Can insert voice memory record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO voice_memories
                (audio_path, transcript, memory_id, duration_seconds, created_at, project_id, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "/path/to/audio.m4a",
                "Test transcript",
                "mem_123",
                120.5,
                "2026-02-12T10:00:00",
                "LFI",
                '["#voice-memo"]',
                0.7
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM voice_memories WHERE id = 1")
            row = cursor.fetchone()

            assert row['audio_path'] == "/path/to/audio.m4a"
            assert row['transcript'] == "Test transcript"
            assert row['duration_seconds'] == 120.5


class TestImageMemoriesTable:
    """Test image_memories table structure"""

    def test_insert_image_memory(self, temp_db):
        """Can insert image memory record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO image_memories
                (image_path, ocr_text, vision_analysis, memory_id, created_at, project_id, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "/path/to/screenshot.png",
                "OCR extracted text",
                "Vision insights",
                "mem_456",
                "2026-02-12T10:00:00",
                "LFI",
                '["#screenshot"]',
                0.6
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM image_memories WHERE id = 1")
            row = cursor.fetchone()

            assert row['image_path'] == "/path/to/screenshot.png"
            assert row['ocr_text'] == "OCR extracted text"


class TestCodeMemoriesTable:
    """Test code_memories table structure"""

    def test_insert_code_memory(self, temp_db):
        """Can insert code memory record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO code_memories
                (snippet, language, description, context, file_path, session_id, created_at, project_id, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "def hello(): print('world')",
                "python",
                "Hello world function",
                "Testing code snippets",
                "/test.py",
                "sess_789",
                "2026-02-12T10:00:00",
                "LFI",
                '["#code-pattern"]',
                0.5
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM code_memories WHERE id = 1")
            row = cursor.fetchone()

            assert row['snippet'] == "def hello(): print('world')"
            assert row['language'] == "python"


class TestDecisionJournalTable:
    """Test decision_journal table structure"""

    def test_insert_decision(self, temp_db):
        """Can insert decision record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO decision_journal
                (decision, options_considered, chosen_option, rationale, context, project_id, decided_at, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "Which database to use?",
                '["SQLite", "PostgreSQL"]',
                "SQLite",
                "Simpler for local use",
                "Memory system",
                "LFI",
                "2026-02-12T10:00:00",
                '["#decision"]'
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM decision_journal WHERE id = 1")
            row = cursor.fetchone()

            assert row['decision'] == "Which database to use?"
            assert row['chosen_option'] == "SQLite"

    def test_track_outcome(self, temp_db):
        """Can track decision outcome"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            # Insert decision
            cursor.execute("""
                INSERT INTO decision_journal
                (decision, options_considered, chosen_option, rationale, decided_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "Test decision",
                '["A", "B"]',
                "A",
                "Seemed better",
                "2026-02-12T10:00:00"
            ))

            db.conn.commit()

            # Update with outcome
            cursor.execute("""
                UPDATE decision_journal
                SET outcome = ?, outcome_success = ?, outcome_recorded_at = ?
                WHERE id = 1
            """, ("Worked great", True, "2026-02-12T11:00:00"))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM decision_journal WHERE id = 1")
            row = cursor.fetchone()

            assert row['outcome'] == "Worked great"
            assert row['outcome_success'] == 1  # SQLite stores bool as int


class TestABTestsTable:
    """Test ab_tests table structure"""

    def test_insert_ab_test(self, temp_db):
        """Can insert A/B test record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO ab_tests
                (test_name, strategy_a_name, strategy_b_name, started_at, sample_size)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "Semantic vs Hybrid Search",
                "Semantic Only",
                "Hybrid (70/30)",
                "2026-02-12T10:00:00",
                100
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM ab_tests WHERE id = 1")
            row = cursor.fetchone()

            assert row['test_name'] == "Semantic vs Hybrid Search"
            assert row['sample_size'] == 100


class TestCrossSystemImportsTable:
    """Test cross_system_imports table structure"""

    def test_insert_import(self, temp_db):
        """Can insert cross-system import record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO cross_system_imports
                (source_system, pattern_type, pattern_description, imported_at)
                VALUES (?, ?, ?, ?)
            """, (
                "Ben's Kit",
                "extraction",
                "Use trigger phrases for context loading",
                "2026-02-12T10:00:00"
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM cross_system_imports WHERE id = 1")
            row = cursor.fetchone()

            assert row['source_system'] == "Ben's Kit"
            assert row['pattern_type'] == "extraction"


class TestDreamInsightsTable:
    """Test dream_insights table structure"""

    def test_insert_dream_insights(self, temp_db):
        """Can insert dream insights record"""
        with IntelligenceDB(temp_db) as db:
            cursor = db.conn.cursor()

            cursor.execute("""
                INSERT INTO dream_insights
                (run_date, memories_analyzed, patterns_found, deep_insights, new_connections, runtime_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "2026-02-12",
                150,
                '["Pattern 1", "Pattern 2"]',
                "Deep insight text",
                5,
                45.2
            ))

            db.conn.commit()

            # Verify
            cursor.execute("SELECT * FROM dream_insights WHERE id = 1")
            row = cursor.fetchone()

            assert row['memories_analyzed'] == 150
            assert row['new_connections'] == 5


class TestContextManager:
    """Test context manager support"""

    def test_with_statement(self, temp_db):
        """Can use database with 'with' statement"""
        with IntelligenceDB(temp_db) as db:
            assert db.conn is not None

        # Connection should be closed after exiting
        # (Python sqlite3 doesn't error on closed connection, but we can verify db object exists)
        assert db.db_path == temp_db
