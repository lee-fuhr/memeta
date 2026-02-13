"""
Tests for Features 45-50
- Image capture
- Code memory
- Decision journal
- A/B testing
- Cross-system learning
- Dream mode
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.multimodal.image_capture import ImageCapture, ImageMemory
from src.multimodal.code_memory import CodeMemoryLibrary, CodeMemory
from src.multimodal.decision_journal import DecisionJournal, Decision
from src.meta_learning_system import MemoryABTesting, CrossSystemLearning, DreamMode


@pytest.fixture
def temp_db():
    """Create temporary database"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(temp_file.name)
    temp_file.close()
    yield db_path
    if db_path.exists():
        db_path.unlink()


# ==================== Feature 45: Image Capture ====================

class TestImageCapture:
    """Test image memory capture"""

    @pytest.fixture
    def image_capture(self, temp_db):
        return ImageCapture(db_path=temp_db)

    @pytest.fixture
    def temp_image(self):
        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image_path = Path(temp_file.name)
        temp_file.write(b"fake image data")
        temp_file.close()
        yield image_path
        if image_path.exists():
            image_path.unlink()

    @patch('subprocess.run')
    def test_ocr_image(self, mock_run, image_capture, temp_image):
        """OCR extracts text from image"""
        mock_run.return_value = MagicMock(returncode=0, stdout="Extracted text")

        result = image_capture.ocr_image(temp_image)

        assert result == "Extracted text"

    def test_ocr_nonexistent_image(self, image_capture):
        """Raises error for missing image"""
        with pytest.raises(FileNotFoundError):
            image_capture.ocr_image(Path("/nonexistent.png"))

    @patch('subprocess.run')
    def test_analyze_with_vision(self, mock_run, image_capture, temp_image):
        """Vision API analyzes image"""
        mock_run.return_value = MagicMock(returncode=0, stdout="Vision insights about the image")

        result = image_capture.analyze_with_vision(temp_image, "OCR text")

        assert "Vision insights" in result or "OCR text" in result

    @patch.object(ImageCapture, 'ocr_image')
    @patch.object(ImageCapture, 'analyze_with_vision')
    def test_process_image(self, mock_vision, mock_ocr, image_capture, temp_image):
        """Complete image processing pipeline"""
        mock_ocr.return_value = "OCR extracted"
        mock_vision.return_value = "Key insight about the image"

        result = image_capture.process_image(temp_image, save_to_memory_ts=False)

        assert isinstance(result, ImageMemory)
        assert result.ocr_text == "OCR extracted"
        assert result.vision_insights == "Key insight about the image"

    def test_search_image_memories(self, image_capture):
        """Search image memories by text"""
        cursor = image_capture.db.conn.cursor()
        cursor.execute("""
            INSERT INTO image_memories
            (image_path, ocr_text, vision_analysis, created_at, project_id, importance)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("/test.png", "Test OCR content", "Vision analysis", datetime.now().isoformat(), "LFI", 0.7))
        image_capture.db.conn.commit()

        results = image_capture.search_image_memories("Test OCR")

        assert len(results) >= 1


# ==================== Feature 46: Code Memory ====================

class TestCodeMemory:
    """Test code snippet library"""

    @pytest.fixture
    def code_library(self, temp_db):
        return CodeMemoryLibrary(db_path=temp_db)

    def test_save_code_snippet(self, code_library):
        """Save code snippet to library"""
        result = code_library.save_code_snippet(
            snippet="def test(): pass",
            language="python",
            description="Test function",
            context="Testing code memory",
            save_to_memory_ts=False
        )

        assert isinstance(result, CodeMemory)
        assert result.snippet == "def test(): pass"
        assert result.language == "python"

    def test_save_empty_snippet_raises_error(self, code_library):
        """Empty snippet raises error"""
        with pytest.raises(ValueError):
            code_library.save_code_snippet("", "python", "", "", save_to_memory_ts=False)

    def test_search_code_keyword(self, code_library):
        """Search code snippets by keyword"""
        code_library.save_code_snippet(
            snippet="async def rate_limit(): pass",
            language="python",
            description="Rate limiting implementation",
            context="Async rate limiting",
            save_to_memory_ts=False
        )

        results = code_library.search_code("rate limiting", use_semantic=False)

        assert len(results) >= 1
        assert "rate_limit" in results[0]['snippet'] or "rate limiting" in results[0]['description'].lower()

    def test_get_by_language(self, code_library):
        """Filter code by language"""
        code_library.save_code_snippet("const x = 1", "javascript", "Const", "JS test", save_to_memory_ts=False)
        code_library.save_code_snippet("x = 1", "python", "Var", "Py test", save_to_memory_ts=False)

        results = code_library.get_by_language("python")

        assert all(r['language'] == "python" for r in results)

    def test_deduplicate_snippet(self, code_library):
        """Detect duplicate snippets"""
        snippet = "def unique(): return True"
        code_library.save_code_snippet(snippet, "python", "Unique", "Test", save_to_memory_ts=False)

        duplicate = code_library.deduplicate_snippet(snippet)

        assert duplicate is not None
        assert duplicate['snippet'] == snippet


# ==================== Feature 47: Decision Journal ====================

class TestDecisionJournal:
    """Test decision tracking"""

    @pytest.fixture
    def journal(self, temp_db):
        return DecisionJournal(db_path=temp_db)

    def test_record_decision(self, journal):
        """Record a decision"""
        result = journal.record_decision(
            decision="Which framework to use?",
            options_considered=["React", "Vue", "Svelte"],
            chosen_option="React",
            rationale="Team experience",
            save_to_memory_ts=False,
            link_to_commitment=False
        )

        assert isinstance(result, Decision)
        assert result.decision == "Which framework to use?"
        assert result.chosen_option == "React"

    def test_track_outcome(self, journal):
        """Track decision outcome"""
        # Record decision
        decision = journal.record_decision(
            "Test decision",
            ["A", "B"],
            "A",
            "Test rationale",
            save_to_memory_ts=False,
            link_to_commitment=False
        )

        # Get decision ID from DB
        cursor = journal.db.conn.cursor()
        cursor.execute("SELECT id FROM decision_journal ORDER BY id DESC LIMIT 1")
        decision_id = cursor.fetchone()[0]

        # Track outcome
        result = journal.track_outcome(
            decision_id,
            outcome="Worked well",
            success=True,
            update_memory_ts=False
        )

        assert result['outcome'] == "Worked well"
        assert result['outcome_success'] == 1  # SQLite bool

    def test_learn_from_decisions(self, journal):
        """Analyze decision patterns"""
        # Record multiple decisions
        for i in range(5):
            decision = journal.record_decision(
                f"Decision {i}",
                ["Option A", "Option B"],
                "Option A" if i % 2 == 0 else "Option B",
                "Test",
                save_to_memory_ts=False,
                link_to_commitment=False
            )

        # Track outcomes
        cursor = journal.db.conn.cursor()
        cursor.execute("SELECT id FROM decision_journal")
        ids = [row[0] for row in cursor.fetchall()]

        for i, did in enumerate(ids):
            journal.track_outcome(did, "Outcome", i % 2 == 0, update_memory_ts=False)

        # Analyze
        analysis = journal.learn_from_decisions()

        assert analysis['total_decisions'] >= 5
        assert 'success_rate' in analysis

    def test_get_pending_outcomes(self, journal):
        """Get decisions without outcomes"""
        journal.record_decision("Pending", ["A"], "A", "Test", save_to_memory_ts=False, link_to_commitment=False)

        pending = journal.get_pending_outcomes()

        assert len(pending) >= 1


# ==================== Feature 48: A/B Testing ====================

class TestMemoryABTesting:
    """Test A/B testing system"""

    @pytest.fixture
    def ab_testing(self, temp_db):
        return MemoryABTesting(db_path=temp_db)

    def test_start_test(self, ab_testing):
        """Start A/B test"""
        test_id = ab_testing.start_test(
            "Semantic vs Hybrid",
            "Semantic Only",
            "Hybrid Search",
            sample_size=100
        )

        assert test_id > 0

    def test_record_performance(self, ab_testing):
        """Record test performance"""
        test_id = ab_testing.start_test("Test", "A", "B", 50)

        ab_testing.record_performance(test_id, 0.85, 0.75)

        result = ab_testing.get_test_results(test_id)
        assert result['winner'] == 'a'  # A performed better

    def test_adopt_winner(self, ab_testing):
        """Mark winner as adopted"""
        test_id = ab_testing.start_test("Test", "A", "B", 50)
        ab_testing.record_performance(test_id, 0.9, 0.8)

        ab_testing.adopt_winner(test_id)

        result = ab_testing.get_test_results(test_id)
        assert result['adopted'] == 1

    def test_get_active_tests(self, ab_testing):
        """Get running tests"""
        ab_testing.start_test("Active Test", "A", "B", 50)

        active = ab_testing.get_active_tests()

        assert len(active) >= 1
        assert active[0]['ended_at'] is None


# ==================== Feature 49: Cross-System Learning ====================

class TestCrossSystemLearning:
    """Test cross-system learning"""

    @pytest.fixture
    def cross_learning(self, temp_db):
        return CrossSystemLearning(db_path=temp_db)

    def test_import_pattern(self, cross_learning):
        """Import pattern from another system"""
        import_id = cross_learning.import_pattern(
            "Ben's Kit",
            "extraction",
            "Use trigger phrases",
            save_to_memory_ts=False
        )

        assert import_id > 0

    def test_mark_adapted(self, cross_learning):
        """Mark pattern as adapted"""
        import_id = cross_learning.import_pattern("Kit", "pattern", "Test", save_to_memory_ts=False)

        cross_learning.mark_adapted(import_id, "Applied successfully")

        cursor = cross_learning.db.conn.cursor()
        cursor.execute("SELECT adapted FROM cross_system_imports WHERE id = ?", (import_id,))
        assert cursor.fetchone()[0] == 1

    def test_rate_effectiveness(self, cross_learning):
        """Rate pattern effectiveness"""
        import_id = cross_learning.import_pattern("Kit", "pattern", "Test", save_to_memory_ts=False)

        cross_learning.rate_effectiveness(import_id, 0.85)

        cursor = cross_learning.db.conn.cursor()
        cursor.execute("SELECT effectiveness_score FROM cross_system_imports WHERE id = ?", (import_id,))
        assert cursor.fetchone()[0] == 0.85

    def test_get_effective_patterns(self, cross_learning):
        """Get high-performing patterns"""
        import_id = cross_learning.import_pattern("Kit", "pattern", "Good", save_to_memory_ts=False)
        cross_learning.rate_effectiveness(import_id, 0.9)

        effective = cross_learning.get_effective_patterns(min_score=0.8)

        assert len(effective) >= 1


# ==================== Feature 50: Dream Mode ====================

class TestDreamMode:
    """Test overnight consolidation"""

    @pytest.fixture
    def dream_mode(self, temp_db):
        return DreamMode(db_path=temp_db)

    def test_consolidate_overnight(self, dream_mode):
        """Overnight consolidation runs"""
        # Mock memory_client.search
        with patch.object(dream_mode.memory_client, 'search') as mock_search:
            mock_search.return_value = [
                {'content': 'Test memory 1', 'project_id': 'LFI'},
                {'content': 'Test memory 2', 'project_id': 'LFI'}
            ]

            result = dream_mode.consolidate_overnight(lookback_days=1, save_insights=False)

            assert 'memories_analyzed' in result
            assert 'patterns_found' in result
            assert 'deep_insights' in result

    def test_get_morning_report_no_data(self, dream_mode):
        """Morning report with no data"""
        report = dream_mode.get_morning_report()

        assert "No overnight consolidation" in report

    def test_consolidate_saves_to_db(self, dream_mode):
        """Consolidation saves to intelligence DB"""
        with patch.object(dream_mode.memory_client, 'search') as mock_search:
            # Provide some memories so save_insights logic runs
            mock_search.return_value = [
                {'content': 'Test memory for saving', 'project_id': 'LFI'}
            ]

            dream_mode.consolidate_overnight(lookback_days=1, save_insights=True)

            cursor = dream_mode.db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM dream_insights")
            count = cursor.fetchone()[0]

            assert count >= 1
