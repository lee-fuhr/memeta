"""
Tests for pattern detector - cross-session reinforcement detection

Tests fuzzy matching, reinforcement grading, FSRS integration,
and batch detection across memories.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fsrs_scheduler import FSRSScheduler, ReviewGrade
from src.pattern_detector import (
    PatternDetector,
    ReinforcementSignal,
    normalize_text,
    word_overlap_score,
)


@pytest.fixture
def db_path(tmp_path):
    """Create temporary FSRS database"""
    return tmp_path / "test_fsrs.db"


@pytest.fixture
def memory_dir(tmp_path):
    """Create temporary memory directory with sample memories"""
    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    return mem_dir


@pytest.fixture
def scheduler(db_path):
    """Create FSRS scheduler with fresh database"""
    return FSRSScheduler(db_path=db_path)


def create_memory_file(memory_dir: Path, memory_id: str, content: str,
                       project_id: str = "LFI", importance: float = 0.7):
    """Helper: create a memory-ts markdown file"""
    file_path = memory_dir / f"{memory_id}.md"
    file_path.write_text(f"""---
id: {memory_id}
content: "{content}"
importance: {importance}
tags:
  - "#learning"
project_id: {project_id}
scope: project
created: "{datetime.now().isoformat()}"
updated: "{datetime.now().isoformat()}"
schema_version: 2
status: active
---

{content}
""")
    return file_path


class TestNormalizeText:
    """Test text normalization for comparison"""

    def test_lowercase(self):
        """Should lowercase all text"""
        result = normalize_text("HELLO WORLD")
        assert result == {"hello", "world"}

    def test_strip_punctuation(self):
        """Should remove punctuation"""
        result = normalize_text("hello, world! How's it going?")
        assert "hello" in result
        assert "world" in result
        # No word should contain punctuation characters
        for word in result:
            assert word.isalnum(), f"Word '{word}' contains non-alphanumeric chars"

    def test_empty_string(self):
        """Should handle empty string"""
        result = normalize_text("")
        assert result == set()

    def test_returns_word_set(self):
        """Should return set of unique words"""
        result = normalize_text("the cat sat on the mat")
        assert isinstance(result, set)
        assert "the" in result
        assert "cat" in result


class TestWordOverlapScore:
    """Test word overlap similarity calculation"""

    def test_identical_texts(self):
        """Identical texts should score 1.0"""
        score = word_overlap_score(
            "always validate user input at boundaries",
            "always validate user input at boundaries"
        )
        assert score == 1.0

    def test_completely_different(self):
        """Completely different texts should score 0.0"""
        score = word_overlap_score(
            "the cat sat on the mat",
            "quick brown fox jumped over lazy dog"
        )
        assert score == 0.0

    def test_partial_overlap(self):
        """Partially overlapping texts should score between 0 and 1"""
        score = word_overlap_score(
            "validate user input at system boundaries",
            "always validate user input before processing"
        )
        assert 0.0 < score < 1.0

    def test_empty_text_scores_zero(self):
        """Empty text should score 0.0"""
        assert word_overlap_score("", "something") == 0.0
        assert word_overlap_score("something", "") == 0.0
        assert word_overlap_score("", "") == 0.0

    def test_subset_text_high_score(self):
        """When one text is a subset of another, should score high"""
        score = word_overlap_score(
            "validate input",
            "always validate user input at boundaries"
        )
        assert score >= 0.5  # subset direction should be high

    def test_bidirectional_max(self):
        """Should return max of both directions"""
        # "validate input" is 100% contained in the longer text
        score = word_overlap_score(
            "validate input",
            "validate input at system boundaries"
        )
        assert score >= 0.5


class TestReinforcementSignal:
    """Test ReinforcementSignal data structure"""

    def test_create_signal(self):
        """Should create reinforcement signal with all fields"""
        signal = ReinforcementSignal(
            memory_id="mem-001",
            matched_memory_id="mem-existing-001",
            similarity_score=0.65,
            grade=ReviewGrade.GOOD,
            project_id="LFI",
            session_id="session-123",
        )
        assert signal.memory_id == "mem-001"
        assert signal.grade == ReviewGrade.GOOD
        assert signal.similarity_score == 0.65


class TestPatternDetector:
    """Test pattern detection against existing memories"""

    def test_detect_reinforcement_same_project(self, memory_dir, scheduler):
        """Should detect reinforcement when similar memory exists in same project"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        assert len(signals) >= 1
        assert signals[0].grade == ReviewGrade.GOOD  # same project

    def test_detect_reinforcement_cross_project(self, memory_dir, scheduler):
        """Should grade EASY when reinforcement is cross-project"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "ClientA",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        assert len(signals) >= 1
        assert signals[0].grade == ReviewGrade.EASY  # cross-project

    def test_no_reinforcement_for_dissimilar(self, memory_dir, scheduler):
        """Should not detect reinforcement for dissimilar memories"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "CSS grid layouts work better than flexbox for page structure",
                "project_id": "LFI",
                "importance": 0.5,
            }],
            session_id="session-001",
        )

        assert len(signals) == 0

    def test_registers_memory_in_fsrs(self, memory_dir, scheduler):
        """Should register matched memory in FSRS if not already tracked"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        # Memory should now be registered in FSRS
        state = scheduler.get_state("existing-001")
        assert state is not None

    def test_records_review_in_fsrs(self, memory_dir, scheduler):
        """Should record review event in FSRS scheduler"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        state = scheduler.get_state("existing-001")
        assert state.review_count == 1

    def test_multiple_reinforcements(self, memory_dir, scheduler):
        """Should detect multiple reinforcements in one batch"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")
        create_memory_file(memory_dir, "existing-002",
                          "Use structured logging with context fields",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[
                {
                    "content": "User input validation at boundaries is critical",
                    "project_id": "ClientA",
                    "importance": 0.7,
                },
                {
                    "content": "Structured logging with context fields helps debugging",
                    "project_id": "ClientA",
                    "importance": 0.6,
                },
            ],
            session_id="session-001",
        )

        assert len(signals) == 2

    def test_threshold_boundary(self, memory_dir, scheduler):
        """Should not match when similarity is below threshold"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries before processing external data",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
            similarity_threshold=0.5,
        )

        # Very slight overlap - below 50%
        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "Validate your assumptions about database schemas carefully",
                "project_id": "LFI",
                "importance": 0.5,
            }],
            session_id="session-001",
        )

        assert len(signals) == 0

    def test_custom_threshold(self, memory_dir, scheduler):
        """Should respect custom similarity threshold"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        # Very high threshold - shouldn't match anything but exact
        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
            similarity_threshold=0.95,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        assert len(signals) == 0

    def test_returns_best_match_per_new_memory(self, memory_dir, scheduler):
        """When a new memory matches multiple existing ones, return best match"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at boundaries",
                          project_id="LFI")
        create_memory_file(memory_dir, "existing-002",
                          "Validate user input at system boundaries before processing",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "Always validate user input at system boundaries before processing",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        # Should return only 1 signal (best match), not 2
        assert len(signals) == 1

    def test_cross_project_tracks_project(self, memory_dir, scheduler):
        """Cross-project reinforcement should track the new project"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "ClientA",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        # FSRS should track the new project
        state = scheduler.get_state("existing-001")
        projects = json.loads(state.projects_validated)
        assert "ClientA" in projects

    def test_skip_already_promoted(self, memory_dir, scheduler):
        """Should skip memories that are already promoted"""
        create_memory_file(memory_dir, "existing-001",
                          "Always validate user input at system boundaries",
                          project_id="LFI")

        # Pre-register and promote in FSRS
        scheduler.register_memory("existing-001", project_id="LFI")
        scheduler.mark_promoted("existing-001")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "User input should be validated at system boundaries",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        assert len(signals) == 0


class TestDetectFromSession:
    """Test the higher-level session detection interface"""

    def test_detect_from_session_memories(self, memory_dir, scheduler):
        """Should work with SessionMemory-like dicts from consolidator"""
        create_memory_file(memory_dir, "existing-001",
                          "Use environment variables for configuration",
                          project_id="LFI")

        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "Configuration should use environment variables not hardcoded values",
                "project_id": "ClientB",
                "importance": 0.6,
            }],
            session_id="session-002",
        )

        assert len(signals) >= 1
        assert signals[0].session_id == "session-002"

    def test_empty_new_memories(self, memory_dir, scheduler):
        """Should handle empty input gracefully"""
        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[],
            session_id="session-001",
        )

        assert signals == []

    def test_no_existing_memories(self, memory_dir, scheduler):
        """Should handle empty memory directory"""
        detector = PatternDetector(
            memory_dir=memory_dir,
            scheduler=scheduler,
        )

        signals = detector.detect_reinforcements(
            new_memories=[{
                "content": "Some new insight",
                "project_id": "LFI",
                "importance": 0.7,
            }],
            session_id="session-001",
        )

        assert signals == []
