# Wild Features (51-75) - Production Implementation

**Status:** Phase 1 Complete (6 HIGH PRIORITY features built)
**Date:** 2026-02-12
**Architecture:** Self-improving, anticipatory intelligence layer

---

## Overview

Wild Features transform the memory system from reactive to **prescient**:
- **Don't just remember** → Anticipate needs before asking
- **Don't just store** → Learn and evolve extraction quality
- **Don't just retrieve** → Find hidden connections you didn't know existed
- **Don't just wait** → Intervene when frustration patterns emerge

All features use shared `intelligence.db` SQLite database and integrate with the existing session consolidation pipeline.

---

## Feature 55: Frustration Early Warning System

**File:** `src/wild/frustration_detector.py`
**Status:** ✅ Production Ready

### What it does

Detects frustration patterns BEFORE they peak and suggests interventions.

### Signals tracked

| Signal | Threshold | Example |
|--------|-----------|---------|
| **Repeated corrections** | 3+ on same topic in 30min | Correcting "hook" 3 times |
| **Topic cycling** | Returning to topic 3+ times in 60min | Authentication → DB → Auth → API → Auth |
| **Negative sentiment** | 2+ frustration keywords in message | "This is frustrating", "broken again" |
| **High velocity** | 5+ corrections in 15min | Rapid-fire corrections |

### Interventions

When combined frustration score > 0.7:
- **Repeated corrections:** "Add a hook or verification step to prevent 'X' errors permanently"
- **Topic cycling:** "'X' seems to be a blocker. Should we solve it before continuing?"
- **Negative sentiment:** "Detected frustration. Want to step back and reassess the approach?"
- **High velocity:** "High correction rate detected. Consider taking a 5-minute break to reset."

### Usage

```python
from src.wild.frustration_detector import FrustrationDetector

detector = FrustrationDetector()

# Analyze a session
messages = [
    {'role': 'user', 'content': 'The hook is broken', 'timestamp': ...},
    {'role': 'user', 'content': 'Actually, still broken', 'timestamp': ...},
    # ... more messages
]

event = detector.analyze_session('session_id', messages)

if event and event.intervention_suggested:
    print(event.intervention_text)
    # ⚠️ Frustration detected: Add a hook to prevent 'hook' errors permanently
```

### Database schema

```sql
CREATE TABLE frustration_signals (
    session_id TEXT,
    signal_type TEXT,  -- repeated_correction, topic_cycling, negative_sentiment, high_velocity
    severity REAL,     -- 0.0-1.0
    evidence TEXT,
    intervention TEXT,
    timestamp TEXT
);

CREATE TABLE frustration_events (
    session_id TEXT UNIQUE,
    combined_score REAL,  -- 0.0-1.0
    peak_time TEXT,
    intervention_suggested INTEGER,
    intervention_text TEXT
);
```

---

## Feature 62: Memory Quality Auto-Grading

**File:** `src/wild/quality_grader.py`
**Status:** ✅ Production Ready

### What it does

Grades every memory (A/B/C/D) and learns what makes good memories from user behavior.

### Grading scale

| Grade | Score | Characteristics |
|-------|-------|----------------|
| **A** | 0.85-1.0 | Precise, actionable, well-evidenced, validated |
| **B** | 0.65-0.84 | Good but could be more specific/actionable |
| **C** | 0.40-0.64 | Vague or limited usefulness |
| **D** | 0.0-0.39 | Too vague, not actionable, or invalidated |

### Component scores

```
Total Score = precision*0.35 + actionability*0.35 + evidence*0.20 + importance*0.10
```

**Precision** (0.0-1.0): How specific vs vague
- Penalizes: filler words (maybe, possibly, sometimes)
- Rewards: specifics (numbers, proper nouns, code references)
- Sweet spot: 50-200 words

**Actionability** (0.0-1.0): Does it lead to action?
- Rewards: action verbs (use, do, create, avoid)
- Rewards: imperatives (should, must, always, never)
- Rewards: concrete examples

**Evidence** (0.0-1.0): How well-supported?
- Rewards: evidence markers (because, found that, measured)
- Rewards: data (numbers, percentages)
- Rewards: references (session, meeting, document)

### Learning loop

1. Grade memory at creation
2. Track validation events (reinforcement, correction, cross-project, contradiction)
3. Update grade based on real-world signals:
   - Reinforcement: +0.03 per occurrence (max +0.15)
   - Cross-project validation: +0.05 per project (max +0.15)
   - Referenced in correction: +0.02 per reference (max +0.10)
   - Contradicted: -0.10 per contradiction (max -0.30)

### Usage

```python
from src.wild.quality_grader import MemoryQualityGrader

grader = MemoryQualityGrader()

# Grade a memory
grade = grader.grade_memory(
    memory_id='mem_123',
    content='Always run tests before committing - caught 3 bugs this way in Connection Lab project',
    importance=0.7
)

print(f"Grade: {grade.grade}, Score: {grade.score:.2f}")
# Grade: A, Score: 0.87

# Update grade from validation
grader.update_grade_from_validation(
    memory_id='mem_123',
    event_type='cross_project',  # Saw same pattern in different project
    session_id='session_456',
    evidence='Applied in Russell Hamilton project'
)

# Learn quality patterns
patterns = grader.learn_quality_patterns(min_examples=10)
for pattern in patterns:
    if pattern.pattern_type == 'high_quality':
        print(f"High-quality memories have: {pattern.characteristics}")
        # {'avg_precision': 0.78, 'avg_actionability': 0.82, 'avg_evidence': 0.65}
```

---

## Feature 63: Extraction Prompt Evolution

**File:** `src/wild/prompt_evolver.py`
**Status:** ✅ Production Ready

### What it does

Uses genetic algorithm to evolve better extraction prompts over time.

### Genetic algorithm

**Population:** 10 prompts
**Generation cycle:** Weekly
**Selection:** Top 4 performers breed, bottom 6 replaced
**Mutation rate:** 30%
**Crossover rate:** 60%

### Mutations

9 mutation operators:
1. `add_specificity` - Emphasize specific details and examples
2. `add_actionability` - Emphasize actionable takeaways
3. `add_evidence` - Require supporting evidence
4. `simplify` - Remove verbosity, make concise
5. `add_examples` - Include example memories
6. `change_tone_terse` - More terse and direct
7. `change_tone_verbose` - More explanatory
8. `prioritize_corrections` - Focus on user corrections
9. `prioritize_decisions` - Focus on decision points

### Fitness function

```
Fitness = quality*0.40 + yield*0.30 + uniqueness*0.20 + accuracy*0.10
```

- **Quality:** Average memory quality grade from quality_grader
- **Yield:** Memories extracted per session (normalized 3-15 range)
- **Uniqueness:** Low deduplication rate (fewer duplicates = better)
- **Accuracy:** Low correction rate (fewer user corrections = better)

### Evolution process

1. Initialize with base prompt + 9 variants
2. Test each prompt on sample sessions
3. Calculate fitness scores
4. Select top 4 for breeding
5. Create next generation:
   - 1 elite (copy of best)
   - 3 crossover children
   - 6 mutated variants
6. Deactivate old generation
7. Repeat weekly

### Auto-adoption

When fitness confidence >= 0.95, winning prompt automatically adopted for production extraction.

### Usage

```python
from src.wild.prompt_evolver import ExtractionPromptEvolver, Strategy

evolver = ExtractionPromptEvolver()

# Initialize first generation
evolver.initialize_population()

# Create experiment: test two strategies
experiment = evolver.create_experiment(
    name="Specificity vs Brevity",
    description="Test if more specific prompts extract higher quality memories",
    strategy_a=Strategy(
        id='specific_v1',
        name='High Specificity',
        description='Emphasize concrete details',
        parameters={'focus': 'specificity'}
    ),
    strategy_b=Strategy(
        id='brief_v1',
        name='High Brevity',
        description='Emphasize conciseness',
        parameters={'focus': 'brevity'}
    ),
    success_metric='avg_quality',
    target_samples=50
)

# Run evolution
next_gen = evolver.evolve_generation()
print(f"Evolved to generation {next_gen}")

# Get best prompt
best = evolver.get_best_prompt()
print(f"Best prompt (fitness {best.fitness_score:.2f}): {best.content[:100]}...")
```

---

## Feature 57: Writing Style Evolution Tracker

**File:** `src/wild/writing_analyzer.py`
**Status:** ✅ Production Ready

### What it does

Tracks Lee's writing style changes over time and detects intentional vs accidental drift.

### Metrics tracked (11 dimensions)

**Length:**
- Avg headline length (words)
- Avg sentence length (words)
- Avg paragraph length (sentences)

**Word choice:**
- Compression score (0.0-1.0, higher = less filler)
- Formality score (0.0-1.0, based on formal words)
- Technical density (technical terms per 100 words)

**Tone:**
- Question rate (questions per 100 sentences)
- Imperative rate (commands per 100 sentences)
- Passive rate (passive voice per 100 sentences)

**Variety:**
- Sentence length variance
- Vocabulary richness (unique words / total words)

### Trend detection

**Window:** 30 days (old period vs new period)
**Threshold:** 20% change = significant
**Minimum samples:** 10 sessions per period

### Alerts

When significant trends detected:
- **Headline compression:** "Headlines compressed 20% (8.2 → 6.5 words). Intentional tightening?"
- **Sentence variety:** "Sentence variety up 40%. More rhythm or losing consistency?"
- **Technical density:** "Technical density down 25% in client docs. Matching audience or oversimplifying?"

### Usage

```python
from src.wild.writing_analyzer import WritingStyleAnalyzer

analyzer = WritingStyleAnalyzer()

# Analyze text
snapshot = analyzer.analyze_text(
    session_id='session_789',
    text="""Your messaging framework needs three things:

    First, clarity. No jargon, no fluff.
    Second, specificity. Generic claims don't land.
    Third, proof. Show don't tell.""",
    content_type='body'
)

print(f"Compression: {snapshot.compression_score:.2f}")
print(f"Avg sentence length: {snapshot.avg_sentence_length:.1f} words")

# Detect trends
trends = analyzer.detect_trends(days=30)
for trend in trends:
    if trend.is_significant:
        print(f"⚠️ {trend.interpretation}")
        # ⚠️ Headlines compressed 22% (8.2 → 6.4 words). Intentional compression?
```

---

## Feature 61: A/B Testing Memory Strategies

**File:** `src/wild/ab_tester.py`
**Status:** ✅ Production Ready

### What it does

System experiments on itself to find optimal strategies.

### Test framework

**Parallel execution:** Both strategies run on same sessions
**Statistical significance:** t-test with p < 0.05
**Auto-adoption:** Winner adopted when confidence > 0.95
**Sample size:** 50 sessions per experiment (configurable)

### Testable strategies

- Semantic search vs hybrid search
- Deduplication thresholds (60% vs 70% vs 80%)
- Importance score weighting
- FSRS parameters (stability multipliers)
- Promotion criteria (review count, stability threshold)

### Experiment lifecycle

1. **Planned:** Experiment created, strategies defined
2. **Running:** Testing on sample sessions
3. **Completed:** All samples tested, results analyzed
4. **Adopted:** Winner auto-adopted (if confidence > 0.95)
5. **Rejected:** No clear winner or insufficient confidence

### Metrics tracked

- Recall accuracy
- Precision
- User correction rate
- Search satisfaction
- Deduplication rate
- Memory quality grades

### Usage

```python
from src.wild.ab_tester import MemoryStrategyTester, Strategy

tester = MemoryStrategyTester()

# Create experiment
experiment = tester.create_experiment(
    name="Dedup Threshold Test",
    description="Test 70% vs 80% word overlap threshold",
    strategy_a=Strategy(
        id='dedup_70',
        name='70% Threshold',
        description='More aggressive deduplication',
        parameters={'threshold': 0.70}
    ),
    strategy_b=Strategy(
        id='dedup_80',
        name='80% Threshold',
        description='More permissive deduplication',
        parameters={'threshold': 0.80}
    ),
    success_metric='dedup_rate',
    target_samples=50
)

# Run experiment (with test function)
tester.run_experiment(
    experiment_id=experiment.id,
    test_function=lambda strategy, session: run_dedup_test(strategy, session),
    test_sessions=sample_sessions
)

# Analyze results
analysis = tester.analyze_results(experiment.id)

print(f"Winner: {analysis['winning_strategy']}")
print(f"Improvement: +{analysis['improvement_pct']:.1f}%")
print(f"Confidence: {analysis['confidence']:.0%}")
print(f"Auto-adopted: {analysis['adopted']}")
```

---

## Feature 75: Dream Synthesis (Hidden Connections)

**File:** `src/wild/dream_synthesizer.py`
**Status:** ✅ Production Ready

### What it does

Nightly process that finds non-obvious connections across ALL memories.

### Discovery strategies

**1. Semantic Bridging**
- Memories with overlapping concepts but different keywords
- Cross-project patterns
- Threshold: 60% similarity

**2. Temporal Clustering**
- Memories from different projects in same time window
- Co-occurrence window: 7 days
- Theme detection from common keywords

**3. Causal Chain Inference**
- A→B, B→C implies A→C relationship
- Causal language: "because of", "led to", "caused", "resulted in"

**4. Contradiction Synthesis**
- Opposing memories → identify context difference
- "Always X" vs "Never X" about similar topics
- Resolution: what differs between contexts?

### Synthesis generation

**Inputs:** Discovered connections (semantic, temporal, causal, contradiction)
**Outputs:** Higher-level insights

**Novelty score** (0.0-1.0):
```
Novelty = (1 - avg_connection_strength)*0.5 + project_diversity*0.5
```

**Confidence score** (0.0-1.0):
```
Confidence = min(1.0, connection_count / 10)
```

**Queue threshold:** Novelty >= 0.5

### Morning briefing

Top 5 syntheses queued for review, prioritized by:
```
Priority = novelty_score * confidence
```

### Usage

```python
from src.wild.dream_synthesizer import DreamSynthesizer

synthesizer = DreamSynthesizer()

# Run nightly (scheduled for 3am)
syntheses = synthesizer.run_nightly_synthesis()

print(f"Generated {len(syntheses)} syntheses")
for syn in syntheses:
    if syn.novelty_score >= 0.5:
        print(f"📊 {syn.title}: {syn.insight}")
        print(f"   Projects: {', '.join(syn.projects_spanned)}")
        print(f"   Novelty: {syn.novelty_score:.0%}, Confidence: {syn.confidence:.0%}")

# Morning briefing
briefing = synthesizer.get_morning_briefing(limit=5)
for syn in briefing:
    print(f"💡 {syn.title}")
    print(f"   {syn.insight}")
    print(f"   → {len(syn.supporting_memories)} memories across {len(syn.projects_spanned)} projects")
```

---

## Integration with Base System

### Session Consolidation Hook

```python
from src.wild import (
    FrustrationDetector,
    MemoryQualityGrader,
    WritingStyleAnalyzer
)

def consolidate_session_with_wild_features(session_id, messages, extracted_memories):
    """Enhanced consolidation with wild features"""

    # 1. Check for frustration patterns
    frustration = FrustrationDetector()
    event = frustration.analyze_session(session_id, messages)
    if event and event.intervention_suggested:
        # Surface intervention to user
        notify_user(event.intervention_text)

    # 2. Grade extracted memories
    grader = MemoryQualityGrader()
    for memory in extracted_memories:
        grade = grader.grade_memory(
            memory_id=memory.id,
            content=memory.content,
            importance=memory.importance
        )
        memory.quality_grade = grade.grade

    # 3. Analyze writing style
    analyzer = WritingStyleAnalyzer()
    session_text = ' '.join(m['content'] for m in messages if m['role'] == 'user')
    snapshot = analyzer.analyze_text(session_id, session_text)

    # 4. Check for significant style trends
    trends = analyzer.detect_trends(days=30)
    for trend in trends:
        if trend.is_significant:
            log_trend_alert(trend)

    return extracted_memories
```

### Nightly Processes (3am LaunchAgent)

```python
#!/usr/bin/env python3
"""Nightly wild features processes"""

from src.wild import DreamSynthesizer, ExtractionPromptEvolver

# 1. Dream synthesis
synthesizer = DreamSynthesizer()
syntheses = synthesizer.run_nightly_synthesis()

print(f"💭 Generated {len(syntheses)} syntheses")

# 2. Weekly: Evolve extraction prompts (Fridays only)
import datetime
if datetime.datetime.now().weekday() == 4:  # Friday
    evolver = ExtractionPromptEvolver()
    next_gen = evolver.evolve_generation()
    print(f"🧬 Evolved prompts to generation {next_gen}")

    best = evolver.get_best_prompt()
    print(f"   Best fitness: {best.fitness_score:.2f}")
```

---

## Database Schema

All features use `intelligence.db`:

```sql
-- Feature 55: Frustration Detection
CREATE TABLE frustration_signals (...);
CREATE TABLE frustration_events (...);

-- Feature 62: Quality Grading
CREATE TABLE memory_quality_grades (...);
CREATE TABLE quality_validation_events (...);
CREATE TABLE quality_patterns (...);

-- Feature 63: Prompt Evolution
CREATE TABLE extraction_prompts (...);
CREATE TABLE prompt_test_results (...);
CREATE TABLE evolution_history (...);

-- Feature 57: Writing Analysis
CREATE TABLE writing_snapshots (...);
CREATE TABLE style_trends (...);

-- Feature 61: A/B Testing
CREATE TABLE ab_experiments (...);
CREATE TABLE ab_strategies (...);
CREATE TABLE ab_results (...);

-- Feature 75: Dream Synthesis
CREATE TABLE dream_connections (...);
CREATE TABLE dream_syntheses (...);
CREATE TABLE synthesis_queue (...);
```

---

## Testing

Tests in `tests/wild/`:
- `test_frustration_detector.py` - Frustration detection patterns
- `test_quality_grader.py` - Grading + learning
- `test_prompt_evolver.py` - Genetic algorithm
- `test_writing_analyzer.py` - Style tracking
- `test_ab_tester.py` - A/B testing framework
- `test_dream_synthesizer.py` - Connection discovery

Run tests:
```bash
pytest tests/wild/ -v
```

---

## Next Steps

**Phase 2 features (Medium priority):**
- Feature 51: Temporal Pattern Prediction
- Feature 54: Context Pre-loading
- Feature 58: Decision Regret Detection
- Feature 59: Expertise Mapping
- Feature 64: Anomaly Detection
- Feature 65: Memory Archaeology
- Feature 74: Curiosity-Driven Exploration

**Future enhancements:**
- Integration with session-index for better context retrieval
- Real-time frustration detection during sessions (not just post-session)
- Visual dashboard for writing style evolution
- Export dream syntheses to morning triage
- Auto-adoption notifications for evolved prompts

---

**Status:** 6 HIGH PRIORITY features complete and production-ready
**Code:** `/Users/lee/CC/LFI/_ Operations/memory-system-v1/src/wild/`
**Tests:** `/Users/lee/CC/LFI/_ Operations/memory-system-v1/tests/wild/`
**Database:** `intelligence.db` (auto-created on first use)
