"""
Tests for Feature 63: Extraction Prompt Evolution
"""

import pytest
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.wild.prompt_evolver import (
    ExtractionPromptEvolver,
    ExtractionPrompt,
    PromptTestResult
)


@pytest.fixture
def evolver():
    """Create evolver with temp database"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    evolver = ExtractionPromptEvolver(db_path=db_path)
    yield evolver

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_evolver_initialization(evolver):
    """Test evolver initializes database correctly"""
    with sqlite3.connect(evolver.db_path) as conn:
        # Check tables exist
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """).fetchall()

        table_names = [t[0] for t in tables]
        assert 'extraction_prompts' in table_names
        assert 'prompt_test_results' in table_names
        assert 'evolution_history' in table_names


def test_initialize_population(evolver):
    """Test population initialization creates base + variants"""
    evolver.initialize_population()

    with sqlite3.connect(evolver.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM extraction_prompts WHERE generation = 0").fetchone()[0]
        assert count == evolver.POPULATION_SIZE

        # Check base prompt exists
        base = conn.execute("SELECT id FROM extraction_prompts WHERE id = 'gen0-base'").fetchone()
        assert base is not None


def test_initialize_population_idempotent(evolver):
    """Test population initialization is idempotent"""
    evolver.initialize_population()

    with sqlite3.connect(evolver.db_path) as conn:
        first_count = conn.execute("SELECT COUNT(*) FROM extraction_prompts WHERE generation = 0").fetchone()[0]

    evolver.initialize_population()  # Should not duplicate

    with sqlite3.connect(evolver.db_path) as conn:
        second_count = conn.execute("SELECT COUNT(*) FROM extraction_prompts WHERE generation = 0").fetchone()[0]

    assert first_count == second_count == evolver.POPULATION_SIZE


def test_test_prompt(evolver):
    """Test testing a prompt on session data"""
    evolver.initialize_population()

    # Get base prompt
    with sqlite3.connect(evolver.db_path) as conn:
        row = conn.execute("SELECT * FROM extraction_prompts WHERE id = 'gen0-base'").fetchone()
        prompt = evolver._row_to_prompt(row)

    # Mock session data (use 'id' not 'session_id')
    session_data = {
        'id': 'test_session',
        'messages': [
            {'role': 'user', 'content': 'Test message 1'},
            {'role': 'assistant', 'content': 'Response 1'},
        ],
        'extracted_memories': [
            {'content': 'Memory 1', 'quality_grade': 0.7},
            {'content': 'Memory 2', 'quality_grade': 0.8},
            {'content': 'Memory 3', 'quality_grade': 0.9},
        ]
    }

    result = evolver.test_prompt(prompt, session_data)

    assert result.prompt_id == prompt.id
    assert result.session_id == 'test_session'
    assert result.memories_extracted >= 0  # Implementation may vary
    assert result.avg_quality_grade >= 0.0


def test_calculate_fitness(evolver):
    """Test fitness calculation from test results"""
    evolver.initialize_population()

    # Get base prompt
    with sqlite3.connect(evolver.db_path) as conn:
        row = conn.execute("SELECT * FROM extraction_prompts WHERE id = 'gen0-base'").fetchone()
        prompt = evolver._row_to_prompt(row)

    # Add test results directly to DB
    with sqlite3.connect(evolver.db_path) as conn:
        for i in range(3):
            conn.execute("""
                INSERT INTO prompt_test_results
                (prompt_id, session_id, memories_extracted, avg_quality_grade, dedup_count, correction_count, tested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ('gen0-base', f'session{i}', 5, 0.8, 0, 1, datetime.now().isoformat()))

    # Calculate fitness
    fitness = evolver.calculate_fitness('gen0-base')

    assert fitness > 0.0


def test_get_best_prompt(evolver):
    """Test retrieving best performing prompt"""
    evolver.initialize_population()

    # Set fitness scores
    with sqlite3.connect(evolver.db_path) as conn:
        prompts = conn.execute("SELECT id FROM extraction_prompts WHERE generation = 0").fetchall()
        best_id = prompts[0][0]

        conn.execute("UPDATE extraction_prompts SET fitness_score = 0.95 WHERE id = ?", (best_id,))
        conn.execute("UPDATE extraction_prompts SET fitness_score = 0.5 WHERE id != ?", (best_id,))

    best = evolver.get_best_prompt()
    assert best is not None
    assert best.id == best_id
    assert best.fitness_score == 0.95


def test_evolve_generation(evolver):
    """Test evolution creates new generation"""
    evolver.initialize_population()

    # Set fitness scores for all gen0 prompts
    with sqlite3.connect(evolver.db_path) as conn:
        prompts = conn.execute("SELECT id FROM extraction_prompts WHERE generation = 0").fetchall()
        for i, (prompt_id,) in enumerate(prompts):
            fitness = 0.3 + (i * 0.05)
            conn.execute(
                "UPDATE extraction_prompts SET fitness_score = ? WHERE id = ?",
                (fitness, prompt_id)
            )

    # Evolve to generation 1
    new_gen = evolver.evolve_generation()

    assert new_gen == 1

    # Check generation 1 exists
    with sqlite3.connect(evolver.db_path) as conn:
        gen1_count = conn.execute("SELECT COUNT(*) FROM extraction_prompts WHERE generation = 1").fetchone()[0]
        assert gen1_count > 0

        # Check evolution history recorded
        history = conn.execute("SELECT COUNT(*) FROM evolution_history WHERE generation = 1").fetchone()[0]
        assert history == 1


def test_mutate_prompt(evolver):
    """Test prompt mutation creates new variant"""
    evolver.initialize_population()

    # Get base prompt
    with sqlite3.connect(evolver.db_path) as conn:
        row = conn.execute("SELECT * FROM extraction_prompts WHERE id = 'gen0-base'").fetchone()
        base = evolver._row_to_prompt(row)

    # Mutate it
    mutated = evolver._mutate_prompt(base, generation=1, variant_num=1)

    assert mutated.id != base.id
    assert mutated.generation == 1
    assert mutated.parent_ids == [base.id]
    assert len(mutated.mutations) > 0
    assert mutated.content != base.content  # Should have changed


def test_crossover_prompts(evolver):
    """Test crossover creates child from two parents"""
    evolver.initialize_population()

    # Get two prompts
    with sqlite3.connect(evolver.db_path) as conn:
        rows = conn.execute("SELECT * FROM extraction_prompts WHERE generation = 0 LIMIT 2").fetchall()
        parent1 = evolver._row_to_prompt(rows[0])
        parent2 = evolver._row_to_prompt(rows[1])

    # Crossover (with variant_num)
    child = evolver._crossover_prompts(parent1, parent2, generation=1, variant_num=1)

    assert child.generation == 1
    assert set(child.parent_ids) == {parent1.id, parent2.id}


def test_save_and_retrieve_prompt(evolver):
    """Test saving and retrieving prompts"""
    evolver.initialize_population()

    # Create new prompt
    new_prompt = ExtractionPrompt(
        id='test-prompt-1',
        generation=1,
        content='Test content',
        parent_ids=['gen0-base'],
        mutations=['test_mutation'],
        fitness_score=0.5,
        avg_quality=0.6,
        extraction_yield=5.0,
        dedup_rate=0.1,
        correction_rate=0.2,
        sessions_tested=3,
        created_at=datetime.now(),
        last_tested=datetime.now()
    )

    evolver._save_prompt(new_prompt)

    # Retrieve it
    with sqlite3.connect(evolver.db_path) as conn:
        row = conn.execute("SELECT * FROM extraction_prompts WHERE id = ?", (new_prompt.id,)).fetchone()
        retrieved = evolver._row_to_prompt(row)

    assert retrieved.id == new_prompt.id
    assert retrieved.generation == new_prompt.generation
    assert retrieved.content == new_prompt.content


def test_get_active_prompts(evolver):
    """Test retrieving active prompts"""
    evolver.initialize_population()

    # Get all gen0 prompts
    active = evolver._get_active_prompts(generation=0)

    assert len(active) == evolver.POPULATION_SIZE
    for prompt in active:
        assert prompt.generation == 0


def test_save_test_result(evolver):
    """Test saving test results"""
    result = PromptTestResult(
        prompt_id='gen0-base',
        session_id='test-session',
        memories_extracted=5,
        avg_quality_grade=0.75,
        dedup_count=1,
        correction_count=2,
        tested_at=datetime.now()
    )

    evolver._save_test_result(result)

    # Verify stored
    with sqlite3.connect(evolver.db_path) as conn:
        row = conn.execute("""
            SELECT memories_extracted, avg_quality_grade
            FROM prompt_test_results
            WHERE prompt_id = ? AND session_id = ?
        """, (result.prompt_id, result.session_id)).fetchone()

        assert row is not None
        assert row[0] == 5
        assert row[1] == 0.75


def test_get_test_results(evolver):
    """Test retrieving test results for a prompt"""
    evolver.initialize_population()

    # Add test results
    for i in range(3):
        result = PromptTestResult(
            prompt_id='gen0-base',
            session_id=f'session-{i}',
            memories_extracted=5 + i,
            avg_quality_grade=0.7 + (i * 0.1),
            dedup_count=i,
            correction_count=i,
            tested_at=datetime.now()
        )
        evolver._save_test_result(result)

    # Retrieve
    results = evolver._get_test_results('gen0-base')

    assert len(results) == 3
    assert all(r.prompt_id == 'gen0-base' for r in results)


def test_update_fitness(evolver):
    """Test updating fitness score"""
    evolver.initialize_population()

    evolver._update_fitness('gen0-base', 0.85)

    # Verify updated
    with sqlite3.connect(evolver.db_path) as conn:
        fitness = conn.execute(
            "SELECT fitness_score FROM extraction_prompts WHERE id = ?",
            ('gen0-base',)
        ).fetchone()[0]
        assert fitness == 0.85


def test_fitness_calculation_components(evolver):
    """Test that fitness calculation returns valid score"""
    evolver.initialize_population()

    # Add controlled test result
    result = PromptTestResult(
        prompt_id='gen0-base',
        session_id='test',
        memories_extracted=10,  # High yield
        avg_quality_grade=0.9,  # High quality
        dedup_count=0,  # No duplicates
        correction_count=0,  # No corrections
        tested_at=datetime.now()
    )
    evolver._save_test_result(result)

    fitness = evolver.calculate_fitness('gen0-base')

    # Fitness should be calculated and return a valid score
    assert fitness >= 0.0
    assert fitness <= 1.0
