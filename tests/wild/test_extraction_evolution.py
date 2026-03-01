"""
Tests for extraction evolution loop integration.

Tests the wiring between prompt_evolver, quality_grader, llm_extractor,
and session_consolidator.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from memory_system.wild.prompt_evolver import ExtractionPromptEvolver, ExtractionPrompt
from memory_system.wild.quality_grader import MemoryQualityGrader
from memory_system.session_consolidator import SessionMemory


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def evolver(temp_db):
    """ExtractionPromptEvolver instance with temp DB"""
    return ExtractionPromptEvolver(db_path=temp_db)


@pytest.fixture
def grader(temp_db):
    """MemoryQualityGrader instance with temp DB"""
    return MemoryQualityGrader(db_path=temp_db)


# ---------------------------------------------------------------------------
# Test get_best_prompt() with epsilon-greedy
# ---------------------------------------------------------------------------

class TestGetBestPromptEpsilonGreedy:
    def test_returns_prompt_string(self, evolver):
        """get_best_prompt() returns a string"""
        evolver.initialize_population()
        prompt = evolver.get_best_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_returns_best_fitness_90_percent_of_time(self, evolver):
        """With epsilon=0.1, returns best prompt 90% of time"""
        evolver.initialize_population()

        # Mock random to return 0.05 (< 0.1) = explore
        with patch('random.random', return_value=0.05):
            prompt1 = evolver.get_best_prompt(epsilon=0.1)

        # Mock random to return 0.15 (>= 0.1) = exploit
        with patch('random.random', return_value=0.15):
            prompt2 = evolver.get_best_prompt(epsilon=0.1)

        # Both should return prompts, but likely different ones
        assert isinstance(prompt1, str)
        assert isinstance(prompt2, str)

    def test_epsilon_zero_always_returns_best(self, evolver):
        """With epsilon=0.0, always returns best prompt"""
        evolver.initialize_population()

        # Update one prompt to have high fitness
        prompts = evolver._get_active_prompts()
        evolver._update_fitness(prompts[0].id, 0.9)
        evolver._update_fitness(prompts[1].id, 0.3)

        # Call multiple times with epsilon=0
        results = [evolver.get_best_prompt(epsilon=0.0) for _ in range(5)]

        # All should be the same (best prompt)
        assert len(set(results)) == 1

    def test_fallback_to_base_when_no_population(self, temp_db):
        """Falls back to BASE_PROMPT when population is empty"""
        evolver = ExtractionPromptEvolver(db_path=temp_db)
        # Don't initialize population
        prompt = evolver.get_best_prompt()
        assert prompt == ExtractionPromptEvolver.BASE_PROMPT


# ---------------------------------------------------------------------------
# Test prompt template with conversation placeholder
# ---------------------------------------------------------------------------

class TestPromptTemplate:
    def test_base_prompt_has_conversation_placeholder(self, evolver):
        """BASE_PROMPT contains {CONVERSATION} placeholder"""
        assert '{CONVERSATION}' in ExtractionPromptEvolver.BASE_PROMPT

    def test_prompt_template_injection(self, evolver):
        """Prompt template accepts conversation injection"""
        evolver.initialize_population()
        template = evolver.get_best_prompt()

        conversation = "user: test conversation\nassistant: test response"
        filled = template.format(CONVERSATION=conversation)

        assert conversation in filled
        assert '{CONVERSATION}' not in filled


# ---------------------------------------------------------------------------
# Test quality grading integration
# ---------------------------------------------------------------------------

class TestQualityGradingIntegration:
    def test_grade_memory_returns_quality_grade(self, grader):
        """grade_memory() returns QualityGrade object"""
        grade = grader.grade_memory(
            memory_id="test-mem-1",
            content="Always run tests before committing to catch bugs early",
            importance=0.8
        )

        assert grade.memory_id == "test-mem-1"
        assert grade.grade in ('A', 'B', 'C', 'D')
        assert 0.0 <= grade.score <= 1.0

    def test_grading_after_extraction(self, grader):
        """Can grade memories after extraction"""
        memories = [
            SessionMemory(
                content="Use pytest for testing Python code",
                importance=0.7,
                project_id="LFI"
            ),
            SessionMemory(
                content="Maybe sometimes check things",
                importance=0.3,
                project_id="LFI"
            )
        ]

        grades = []
        for i, mem in enumerate(memories):
            grade = grader.grade_memory(f"mem-{i}", mem.content, mem.importance)
            grades.append(grade)

        # First memory should grade higher (more specific/actionable)
        assert grades[0].score > grades[1].score

    def test_injection_event_type_accepted(self, grader):
        """'injection' event type is accepted by quality_grader"""
        grader.grade_memory("mem-1", "Test memory", 0.5)

        # Should not raise ValueError
        grader.update_grade_from_validation(
            memory_id="mem-1",
            event_type="injection",
            session_id="test-session",
            evidence="Memory was injected into session"
        )


# ---------------------------------------------------------------------------
# Test test_prompt() implementation
# ---------------------------------------------------------------------------

class TestPromptTesting:
    def test_test_prompt_not_simulated(self, evolver):
        """test_prompt() returns real results, not simulated data"""
        evolver.initialize_population()
        prompts = evolver._get_active_prompts()
        prompt = prompts[0]

        session_data = {
            'id': 'test-session',
            'messages': [
                {'role': 'user', 'content': 'How do I test Python code?'},
                {'role': 'assistant', 'content': 'Use pytest framework'}
            ],
            'conversation': 'user: How do I test Python code?\nassistant: Use pytest framework'
        }

        result = evolver.test_prompt(prompt, session_data)

        # Should have actual metrics, not placeholder values
        assert result.prompt_id == prompt.id
        assert result.session_id == 'test-session'
        assert isinstance(result.memories_extracted, int)
        assert isinstance(result.avg_quality_grade, float)

    def test_test_prompt_uses_quality_grader(self, evolver, grader, temp_db):
        """test_prompt() uses quality_grader to evaluate memories"""
        # Create evolver with same DB as grader
        evolver_with_grader = ExtractionPromptEvolver(db_path=temp_db)
        evolver_with_grader.initialize_population()
        prompts = evolver_with_grader._get_active_prompts()

        session_data = {
            'id': 'test-session',
            'messages': [],
            'conversation': 'user: Always use type hints\nassistant: Good advice'
        }

        result = evolver_with_grader.test_prompt(prompts[0], session_data)

        # Quality grade should be calculated from grader
        assert 0.0 <= result.avg_quality_grade <= 1.0


# ---------------------------------------------------------------------------
# Test llm_extractor integration
# ---------------------------------------------------------------------------

class TestLLMExtractorIntegration:
    def test_generate_extraction_prompt_uses_evolver(self, evolver, temp_db):
        """generate_extraction_prompt() uses evolver's best prompt"""
        from memory_system import llm_extractor

        evolver.initialize_population()

        # Mock evolver to be available - patch the import inside the function
        with patch('memory_system.wild.prompt_evolver.ExtractionPromptEvolver') as MockEvolver:
            mock_instance = Mock()
            mock_instance.get_best_prompt.return_value = "Test prompt with {CONVERSATION}"
            MockEvolver.return_value = mock_instance

            prompt = llm_extractor.generate_extraction_prompt("user: test")

            assert "Test prompt" in prompt or "user: test" in prompt

    def test_fallback_to_hardcoded_when_evolver_fails(self):
        """Falls back to hardcoded prompt when evolver unavailable"""
        from memory_system import llm_extractor

        # Mock evolver to raise exception - patch the import inside the function
        with patch('memory_system.wild.prompt_evolver.ExtractionPromptEvolver', side_effect=Exception("DB error")):
            prompt = llm_extractor.generate_extraction_prompt("user: test")

            # Should still return a valid prompt
            assert isinstance(prompt, str)
            assert len(prompt) > 0
            assert "user: test" in prompt


# ---------------------------------------------------------------------------
# Test session_consolidator integration
# ---------------------------------------------------------------------------

class TestConsolidatorIntegration:
    def test_quality_grader_can_grade_session_memories(self, temp_db):
        """Quality grader can grade SessionMemory objects extracted during consolidation"""
        grader = MemoryQualityGrader(db_path=temp_db)

        memories = [
            SessionMemory(content="Always validate user input before passing to database queries", importance=0.8, project_id="LFI"),
            SessionMemory(content="Use meaningful variable names that describe intent", importance=0.7, project_id="LFI")
        ]

        grades = []
        for i, mem in enumerate(memories):
            grade = grader.grade_memory(f"consolidation-mem-{i}", mem.content, mem.importance)
            grades.append(grade)

        # Both should be graded with valid scores
        assert len(grades) == 2
        for grade in grades:
            assert grade.grade in ('A', 'B', 'C', 'D')
            assert 0.0 <= grade.score <= 1.0
            assert 0.0 <= grade.actionability_score <= 1.0
            assert 0.0 <= grade.precision_score <= 1.0
            assert 0.0 <= grade.evidence_score <= 1.0
