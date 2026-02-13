"""
Feature 63: Extraction Prompt Evolution

Uses genetic algorithm to evolve better extraction prompts over time.

Process:
1. Maintain population of extraction prompt variants
2. Test variants on real sessions
3. Grade memories produced by each variant
4. Keep high-performing prompts, mutate/cross new ones
5. Continuous evolution toward better extraction

Mutations:
- Add/remove instructions
- Adjust emphasis (specific → actionable)
- Change examples
- Modify tone (terse → verbose)

Selection criteria:
- Average memory quality grade (from quality_grader)
- Extraction yield (memories per session)
- Deduplication rate (lower is better - means more unique insights)
- User correction rate (lower is better)

Integration: Runs weekly, tests variants on recent sessions, evolves population
"""

import sqlite3
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict


@dataclass
class ExtractionPrompt:
    """An extraction prompt variant"""
    id: str  # Unique identifier
    generation: int  # Which generation of evolution
    content: str  # The actual prompt text
    parent_ids: List[str]  # Parent prompts (for crossover)
    mutations: List[str]  # Mutation history
    fitness_score: float  # 0.0-1.0 overall fitness
    avg_quality: float  # Average memory quality from this prompt
    extraction_yield: float  # Memories per session
    dedup_rate: float  # Deduplication rate (lower is better)
    correction_rate: float  # Correction rate (lower is better)
    sessions_tested: int  # How many sessions tested on
    created_at: datetime
    last_tested: datetime


@dataclass
class PromptTestResult:
    """Result of testing a prompt on a session"""
    prompt_id: str
    session_id: str
    memories_extracted: int
    avg_quality_grade: float
    dedup_count: int
    correction_count: int
    tested_at: datetime


class ExtractionPromptEvolver:
    """
    Evolves extraction prompts using genetic algorithm.

    Algorithm:
    1. Initialize population with base + variants
    2. Test each prompt on sample of sessions
    3. Calculate fitness scores
    4. Select top performers for breeding
    5. Create next generation via crossover + mutation
    6. Repeat

    Population size: 10 prompts
    Generation cycle: Weekly
    Selection: Top 4 breed, bottom 6 replaced
    """

    POPULATION_SIZE = 10
    TOP_PERFORMERS = 4
    MUTATION_RATE = 0.3
    CROSSOVER_RATE = 0.6

    # Base prompt (generation 0)
    BASE_PROMPT = """Extract key learnings and insights from this session.

Focus on:
- Concrete, actionable patterns that can be reused
- Technical solutions that worked
- Mistakes to avoid in the future
- Client-specific insights
- Process improvements

Be specific. Avoid vague generalizations. Include evidence."""

    # Mutation operators
    MUTATIONS = {
        'add_specificity': 'Add more emphasis on specific details and examples',
        'add_actionability': 'Add more emphasis on actionable takeaways',
        'add_evidence': 'Add requirement for supporting evidence',
        'simplify': 'Remove verbose instructions, make more concise',
        'add_examples': 'Add example memories to guide extraction',
        'change_tone_terse': 'Make tone more terse and direct',
        'change_tone_verbose': 'Make tone more explanatory',
        'prioritize_corrections': 'Emphasize extracting from user corrections',
        'prioritize_decisions': 'Emphasize extracting decision points',
    }

    def __init__(self, db_path: str = None):
        """Initialize evolver with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for prompt evolution"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_prompts (
                    id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    parent_ids TEXT,  -- JSON array
                    mutations TEXT,  -- JSON array
                    fitness_score REAL NOT NULL DEFAULT 0.0,
                    avg_quality REAL NOT NULL DEFAULT 0.0,
                    extraction_yield REAL NOT NULL DEFAULT 0.0,
                    dedup_rate REAL NOT NULL DEFAULT 0.0,
                    correction_rate REAL NOT NULL DEFAULT 0.0,
                    sessions_tested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_tested TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    memories_extracted INTEGER NOT NULL,
                    avg_quality_grade REAL NOT NULL,
                    dedup_count INTEGER NOT NULL,
                    correction_count INTEGER NOT NULL,
                    tested_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evolution_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation INTEGER NOT NULL,
                    population_size INTEGER NOT NULL,
                    avg_fitness REAL NOT NULL,
                    best_fitness REAL NOT NULL,
                    mutations_applied TEXT,  -- JSON array
                    evolved_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_gen ON extraction_prompts(generation)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_fitness ON extraction_prompts(fitness_score DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_test_results_prompt ON prompt_test_results(prompt_id)")

    def initialize_population(self):
        """Initialize first generation with base prompt + variants"""
        # Check if already initialized
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM extraction_prompts WHERE generation = 0").fetchone()[0]
            if count > 0:
                return  # Already initialized

        # Create base prompt
        base = ExtractionPrompt(
            id='gen0-base',
            generation=0,
            content=self.BASE_PROMPT,
            parent_ids=[],
            mutations=[],
            fitness_score=0.0,
            avg_quality=0.0,
            extraction_yield=0.0,
            dedup_rate=0.0,
            correction_rate=0.0,
            sessions_tested=0,
            created_at=datetime.now(),
            last_tested=datetime.now()
        )
        self._save_prompt(base)

        # Create initial variants via mutation
        for i in range(self.POPULATION_SIZE - 1):
            variant = self._mutate_prompt(base, generation=0, variant_num=i+1)
            self._save_prompt(variant)

    def test_prompt(self, prompt: ExtractionPrompt, session_data: Dict) -> PromptTestResult:
        """
        Test a prompt on a session and return results.

        Args:
            prompt: Prompt to test
            session_data: Session data with 'id', 'messages', 'extracted_memories'

        Returns:
            PromptTestResult with test outcomes
        """
        # In real implementation, would run extraction with this prompt
        # For now, simulate based on session data

        session_id = session_data['id']
        memories = session_data.get('extracted_memories', [])

        # Calculate metrics
        memories_count = len(memories)
        avg_quality = sum(m.get('quality_score', 0.5) for m in memories) / max(1, memories_count)
        dedup_count = session_data.get('dedup_count', 0)
        correction_count = session_data.get('correction_count', 0)

        result = PromptTestResult(
            prompt_id=prompt.id,
            session_id=session_id,
            memories_extracted=memories_count,
            avg_quality_grade=avg_quality,
            dedup_count=dedup_count,
            correction_count=correction_count,
            tested_at=datetime.now()
        )

        self._save_test_result(result)
        return result

    def calculate_fitness(self, prompt_id: str) -> float:
        """
        Calculate fitness score for a prompt based on test results.

        Fitness components:
        - Quality (40%): Average memory quality grade
        - Yield (30%): Memories extracted per session
        - Uniqueness (20%): Low deduplication rate
        - Accuracy (10%): Low correction rate
        """
        results = self._get_test_results(prompt_id)

        if not results:
            return 0.0

        # Calculate averages
        avg_quality = sum(r.avg_quality_grade for r in results) / len(results)
        avg_yield = sum(r.memories_extracted for r in results) / len(results)
        avg_dedup = sum(r.dedup_count for r in results) / len(results)
        avg_corrections = sum(r.correction_count for r in results) / len(results)

        # Normalize yield (assume 3-15 memories per session is good range)
        norm_yield = min(1.0, max(0.0, (avg_yield - 3) / 12))

        # Normalize dedup rate (inverse - lower is better)
        norm_dedup = max(0.0, 1.0 - (avg_dedup / max(1, avg_yield)))

        # Normalize correction rate (inverse - lower is better)
        norm_corrections = max(0.0, 1.0 - (avg_corrections / max(1, avg_yield)))

        # Weighted combination
        fitness = (
            avg_quality * 0.40 +
            norm_yield * 0.30 +
            norm_dedup * 0.20 +
            norm_corrections * 0.10
        )

        return fitness

    def evolve_generation(self) -> int:
        """
        Evolve to next generation.

        Steps:
        1. Calculate fitness for all active prompts
        2. Select top performers
        3. Create new generation via crossover + mutation
        4. Deactivate poor performers
        5. Return new generation number
        """
        # Get current generation
        with sqlite3.connect(self.db_path) as conn:
            current_gen = conn.execute("""
                SELECT MAX(generation) FROM extraction_prompts
            """).fetchone()[0] or 0

        # Get all active prompts from current generation
        prompts = self._get_active_prompts(generation=current_gen)

        # Calculate fitness for each
        for prompt in prompts:
            fitness = self.calculate_fitness(prompt.id)
            self._update_fitness(prompt.id, fitness)

        # Reload with updated fitness
        prompts = sorted(self._get_active_prompts(current_gen), key=lambda p: p.fitness_score, reverse=True)

        # Select top performers
        top_performers = prompts[:self.TOP_PERFORMERS]

        # Create next generation
        next_gen = current_gen + 1
        new_prompts = []

        # Keep top performer as-is
        elite = top_performers[0]
        elite_copy = ExtractionPrompt(
            id=f'gen{next_gen}-elite',
            generation=next_gen,
            content=elite.content,
            parent_ids=[elite.id],
            mutations=['elitism'],
            fitness_score=0.0,
            avg_quality=0.0,
            extraction_yield=0.0,
            dedup_rate=0.0,
            correction_rate=0.0,
            sessions_tested=0,
            created_at=datetime.now(),
            last_tested=datetime.now()
        )
        new_prompts.append(elite_copy)

        # Create rest via crossover + mutation
        for i in range(self.POPULATION_SIZE - 1):
            # Select two parents from top performers
            parent1, parent2 = random.sample(top_performers, 2)

            # Crossover?
            if random.random() < self.CROSSOVER_RATE:
                child = self._crossover_prompts(parent1, parent2, next_gen, i)
            else:
                child = self._mutate_prompt(random.choice(top_performers), next_gen, i)

            new_prompts.append(child)

        # Save new generation
        for prompt in new_prompts:
            self._save_prompt(prompt)

        # Deactivate old generation (except elite)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE extraction_prompts
                SET is_active = 0
                WHERE generation = ? AND id != ?
            """, (current_gen, elite.id))

        # Log evolution history
        avg_fitness = sum(p.fitness_score for p in top_performers) / len(top_performers)
        best_fitness = top_performers[0].fitness_score
        mutations_applied = [m for p in new_prompts for m in p.mutations]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO evolution_history
                (generation, population_size, avg_fitness, best_fitness, mutations_applied, evolved_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (next_gen, len(new_prompts), avg_fitness, best_fitness,
                  json.dumps(mutations_applied), datetime.now().isoformat()))

        return next_gen

    def get_best_prompt(self) -> ExtractionPrompt:
        """Get current best-performing prompt"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT id, generation, content, parent_ids, mutations,
                       fitness_score, avg_quality, extraction_yield,
                       dedup_rate, correction_rate, sessions_tested,
                       created_at, last_tested
                FROM extraction_prompts
                WHERE is_active = 1
                ORDER BY fitness_score DESC
                LIMIT 1
            """).fetchone()

        if not row:
            return None

        return self._row_to_prompt(row)

    def _mutate_prompt(self, parent: ExtractionPrompt, generation: int, variant_num: int) -> ExtractionPrompt:
        """Apply random mutation to create variant"""
        mutation = random.choice(list(self.MUTATIONS.keys()))
        mutation_text = self.MUTATIONS[mutation]

        # Apply mutation to content
        new_content = parent.content

        if mutation == 'add_specificity':
            new_content += "\n\nBe extremely specific. Include concrete examples, numbers, and exact details."
        elif mutation == 'add_actionability':
            new_content += "\n\nFocus on actionable takeaways. What should be done differently next time?"
        elif mutation == 'add_evidence':
            new_content += "\n\nAlways include supporting evidence: what led to this insight?"
        elif mutation == 'simplify':
            # Remove verbose parts (simplified simulation)
            new_content = new_content.replace('Focus on:', 'Extract:')
        elif mutation == 'add_examples':
            new_content += '\n\nExample: "Always run tests before committing - caught 3 bugs this way"'
        elif mutation == 'change_tone_terse':
            new_content = new_content.replace('Extract key learnings', 'Extract learnings')
        elif mutation == 'change_tone_verbose':
            new_content = new_content.replace('Extract', 'Carefully extract and document')
        elif mutation == 'prioritize_corrections':
            new_content += "\n\nPay special attention to user corrections - these are high-value signals."
        elif mutation == 'prioritize_decisions':
            new_content += "\n\nCapture decision points: what was decided and why?"

        return ExtractionPrompt(
            id=f'gen{generation}-var{variant_num}',
            generation=generation,
            content=new_content,
            parent_ids=[parent.id],
            mutations=[mutation],
            fitness_score=0.0,
            avg_quality=0.0,
            extraction_yield=0.0,
            dedup_rate=0.0,
            correction_rate=0.0,
            sessions_tested=0,
            created_at=datetime.now(),
            last_tested=datetime.now()
        )

    def _crossover_prompts(self, parent1: ExtractionPrompt, parent2: ExtractionPrompt,
                           generation: int, variant_num: int) -> ExtractionPrompt:
        """Combine two prompts to create offspring"""
        # Simple crossover: take first half from parent1, second half from parent2
        lines1 = parent1.content.split('\n')
        lines2 = parent2.content.split('\n')

        split_point = len(lines1) // 2
        child_content = '\n'.join(lines1[:split_point] + lines2[split_point:])

        return ExtractionPrompt(
            id=f'gen{generation}-cross{variant_num}',
            generation=generation,
            content=child_content,
            parent_ids=[parent1.id, parent2.id],
            mutations=['crossover'],
            fitness_score=0.0,
            avg_quality=0.0,
            extraction_yield=0.0,
            dedup_rate=0.0,
            correction_rate=0.0,
            sessions_tested=0,
            created_at=datetime.now(),
            last_tested=datetime.now()
        )

    def _save_prompt(self, prompt: ExtractionPrompt):
        """Save prompt to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO extraction_prompts
                (id, generation, content, parent_ids, mutations, fitness_score,
                 avg_quality, extraction_yield, dedup_rate, correction_rate,
                 sessions_tested, created_at, last_tested)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prompt.id, prompt.generation, prompt.content,
                json.dumps(prompt.parent_ids), json.dumps(prompt.mutations),
                prompt.fitness_score, prompt.avg_quality, prompt.extraction_yield,
                prompt.dedup_rate, prompt.correction_rate, prompt.sessions_tested,
                prompt.created_at.isoformat(), prompt.last_tested.isoformat()
            ))

    def _save_test_result(self, result: PromptTestResult):
        """Save test result to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO prompt_test_results
                (prompt_id, session_id, memories_extracted, avg_quality_grade,
                 dedup_count, correction_count, tested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                result.prompt_id, result.session_id, result.memories_extracted,
                result.avg_quality_grade, result.dedup_count, result.correction_count,
                result.tested_at.isoformat()
            ))

    def _get_test_results(self, prompt_id: str) -> List[PromptTestResult]:
        """Get all test results for a prompt"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT prompt_id, session_id, memories_extracted, avg_quality_grade,
                       dedup_count, correction_count, tested_at
                FROM prompt_test_results
                WHERE prompt_id = ?
            """, (prompt_id,)).fetchall()

        return [
            PromptTestResult(
                prompt_id=r[0], session_id=r[1], memories_extracted=r[2],
                avg_quality_grade=r[3], dedup_count=r[4], correction_count=r[5],
                tested_at=datetime.fromisoformat(r[6])
            )
            for r in rows
        ]

    def _update_fitness(self, prompt_id: str, fitness: float):
        """Update fitness score for a prompt"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE extraction_prompts
                SET fitness_score = ?, last_tested = ?
                WHERE id = ?
            """, (fitness, datetime.now().isoformat(), prompt_id))

    def _get_active_prompts(self, generation: int = None) -> List[ExtractionPrompt]:
        """Get all active prompts, optionally filtered by generation"""
        with sqlite3.connect(self.db_path) as conn:
            if generation is not None:
                rows = conn.execute("""
                    SELECT id, generation, content, parent_ids, mutations,
                           fitness_score, avg_quality, extraction_yield,
                           dedup_rate, correction_rate, sessions_tested,
                           created_at, last_tested
                    FROM extraction_prompts
                    WHERE is_active = 1 AND generation = ?
                """, (generation,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, generation, content, parent_ids, mutations,
                           fitness_score, avg_quality, extraction_yield,
                           dedup_rate, correction_rate, sessions_tested,
                           created_at, last_tested
                    FROM extraction_prompts
                    WHERE is_active = 1
                """).fetchall()

        return [self._row_to_prompt(r) for r in rows]

    def _row_to_prompt(self, row) -> ExtractionPrompt:
        """Convert database row to ExtractionPrompt"""
        return ExtractionPrompt(
            id=row[0],
            generation=row[1],
            content=row[2],
            parent_ids=json.loads(row[3]) if row[3] else [],
            mutations=json.loads(row[4]) if row[4] else [],
            fitness_score=row[5],
            avg_quality=row[6],
            extraction_yield=row[7],
            dedup_rate=row[8],
            correction_rate=row[9],
            sessions_tested=row[10],
            created_at=datetime.fromisoformat(row[11]),
            last_tested=datetime.fromisoformat(row[12]) if row[12] else datetime.now()
        )
