# Features 51-75: Wild Features (Autonomous Intelligence)

**Status:** Planning phase
**Category:** Autonomous, self-improving, predictive intelligence
**Database:** intelligence.db (shared schema)

---

## F51: Temporal Pattern Prediction

**Problem:** You ask for the same context at the same time every week.

**What it does:**
- Learns temporal patterns ("Every Monday 9am, needs Connection Lab context")
- Pre-loads likely-needed memories before you ask
- Surfaces predictions for confirmation
- Adapts to changing patterns

**Schema:**
```sql
CREATE TABLE temporal_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- daily, weekly, monthly, event_based
    trigger_condition TEXT NOT NULL,  -- "Monday 9am", "before client meetings"
    predicted_need TEXT NOT NULL,  -- "Connection Lab context", "pricing framework"
    memory_ids TEXT,  -- JSON array of typically-needed memories
    confidence REAL,
    occurrence_count INTEGER,
    last_confirmed INTEGER,
    created_at INTEGER NOT NULL
);
```

**Algorithm:**
- Track time-of-day + day-of-week for each memory access
- Min occurrences: 3 to establish pattern
- Confidence threshold: 0.7 to surface prediction

**API:**
```python
def predict_needs(current_time: datetime) -> List[Prediction]
def confirm_prediction(pattern_id: str)
def dismiss_prediction(pattern_id: str)
```

**Tests:** 12 tests (pattern detection, prediction, confirmation, adaptation)

---

## F52: Conversation Momentum Tracking

**Problem:** Can't tell if you're making progress or spinning wheels.

**What it does:**
- Tracks momentum score 0-100
- Detects "on a roll" (new insights, decisions made)
- Detects "stuck" (repeated questions, topic cycling)
- Suggests interventions when stuck

**Schema:**
```sql
CREATE TABLE momentum_tracking (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    momentum_score REAL NOT NULL,  -- 0-100
    indicators TEXT,  -- JSON: {new_insights: 3, decisions: 2, repeated_questions: 0}
    state TEXT,  -- on_roll, steady, stuck, spinning
    intervention_suggested TEXT
);
```

**Momentum indicators:**
- Positive: New decisions, insights extracted, forward progress
- Negative: Repeated questions, topic cycling, no new info

**API:**
```python
def track_momentum(session_id: str) -> MomentumScore
def get_momentum_history(session_id: str) -> List[MomentumScore]
def suggest_intervention(session_id: str) -> Optional[str]
```

**Tests:** 10 tests (momentum calculation, state detection, interventions)

---

## F53: Energy-Aware Scheduling

**Problem:** Work on hard problems when tired, easy work when fresh.

**What it does:**
- Tracks your best thinking hours from patterns
- Categorizes tasks by cognitive load
- Suggests optimal times for different work
- Learns your energy curve

**Schema:**
```sql
CREATE TABLE energy_patterns (
    id TEXT PRIMARY KEY,
    hour_of_day INTEGER NOT NULL,  -- 0-23
    day_of_week INTEGER,  -- 0-6
    energy_level TEXT NOT NULL,  -- high, medium, low
    confidence REAL,
    sample_count INTEGER,
    updated_at INTEGER NOT NULL
);

CREATE TABLE task_complexity (
    task_type TEXT PRIMARY KEY,
    cognitive_load TEXT NOT NULL,  -- high, medium, low
    optimal_energy TEXT NOT NULL,  -- high, medium, low
    examples TEXT  -- JSON array of example tasks
);
```

**API:**
```python
def get_current_energy_prediction() -> str
def suggest_task_for_current_time() -> List[str]
def record_energy_level(hour: int, level: str)
```

**Tests:** 8 tests (energy tracking, prediction, task matching)

---

## F54: Context Pre-Loading (Dream Mode v2)

**Problem:** Wait for context to load when starting work.

**What it does:**
- Checks calendar for upcoming work
- Pre-loads relevant context before work starts
- Checks recent sessions + patterns
- Ready before you ask

**Schema:**
```sql
CREATE TABLE context_preload_queue (
    id TEXT PRIMARY KEY,
    scheduled_for INTEGER NOT NULL,  -- Unix timestamp
    context_type TEXT NOT NULL,  -- client_meeting, coding_session, writing
    target_id TEXT,  -- project_id or client name
    memories_loaded TEXT,  -- JSON array of memory IDs
    status TEXT NOT NULL,  -- pending, loaded, expired
    created_at INTEGER NOT NULL
);
```

**Triggers:**
- Calendar events (60min before meeting)
- Temporal patterns (detected from F51)
- Manual request

**API:**
```python
def schedule_preload(time: datetime, context_type: str, target: str)
def get_preloaded_context(context_type: str) -> List[Memory]
def clear_preload_queue()
```

**Tests:** 10 tests (scheduling, loading, expiry, calendar integration)

---

## F56: Client Pattern Transfer

**Problem:** Solve same problem for Client A and Client B separately.

**What it does:**
- Identifies similar problems across clients
- Suggests cross-pollinating solutions
- Privacy-aware (only transfers if allowed)
- Tracks transfer effectiveness

**Schema:**
```sql
CREATE TABLE pattern_transfers (
    id TEXT PRIMARY KEY,
    from_project TEXT NOT NULL,
    to_project TEXT NOT NULL,
    pattern_description TEXT NOT NULL,
    transferred_at INTEGER NOT NULL,
    effectiveness_rating REAL,  -- User feedback 0-1
    notes TEXT
);
```

**API:**
```python
def find_transferable_patterns(from_project: str, to_project: str) -> List[Pattern]
def transfer_pattern(pattern_id: str, to_project: str)
def rate_transfer(transfer_id: str, rating: float)
```

**Tests:** 8 tests (pattern detection, transfer, privacy, rating)

---

## F58: Decision Regret Detection

**Problem:** Make same bad decision multiple times.

**What it does:**
- Tracks decisions + outcomes
- Detects regret patterns (chose X, corrected to Y repeatedly)
- Warns before repeating regretted decision
- Learns from mistakes

**Schema:**
```sql
CREATE TABLE decision_outcomes (
    id TEXT PRIMARY KEY,
    decision_content TEXT NOT NULL,
    alternative TEXT,  -- What you chose against
    outcome TEXT,  -- good, bad, neutral
    regret_detected BOOLEAN DEFAULT FALSE,
    created_at INTEGER NOT NULL,
    corrected_at INTEGER
);
```

**API:**
```python
def record_decision(content: str, alternative: str = None)
def detect_regret_pattern(decision: str) -> Optional[Pattern]
def warn_about_decision(decision: str) -> Optional[Warning]
```

**Tests:** 10 tests (decision tracking, regret detection, warnings)

---

## F59: Expertise Mapping

**Problem:** Don't know which agent/person knows what.

**What it does:**
- Tracks which agents have memories in which domains
- Maps expertise by memory count + quality
- Optimal routing suggestions
- Self-organizing knowledge graph

**Schema:**
```sql
CREATE TABLE agent_expertise (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    memory_count INTEGER,
    avg_quality REAL,  -- Average grade A=4, B=3, C=2, D=1
    last_updated INTEGER NOT NULL,
    UNIQUE(agent_name, domain)
);
```

**API:**
```python
def map_expertise() -> Dict[str, List[str]]  # agent -> domains
def get_expert_for_domain(domain: str) -> str
def update_expertise_map()
```

**Tests:** 8 tests (mapping, routing, updates)

---

## F60: Context Decay Prediction

**Problem:** Don't know when context becomes stale.

**What it does:**
- Predicts staleness before it happens
- Checks for updates in source material
- Surfaces memories needing refresh
- Confidence intervals on staleness

**Schema:**
```sql
CREATE TABLE decay_predictions (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    predicted_stale_at INTEGER,  -- Unix timestamp
    confidence REAL,  -- 0-1
    reason TEXT,  -- project_inactive, superseded, outdated_source
    reviewed_at INTEGER,
    UNIQUE(memory_id)
);
```

**API:**
```python
def predict_decay(memory_id: str) -> datetime
def get_memories_becoming_stale(days_ahead: int = 7) -> List[Memory]
def refresh_memory(memory_id: str)
```

**Tests:** 10 tests (prediction, confidence, review triggers)

---

## F64: Learning Intervention System

**Problem:** Ask same question 5 times, never internalize answer.

**What it does:**
- Detects repeated questions
- Suggests creating tutorial/reference
- Auto-generates learning resource
- Tracks if intervention helped

**Schema:**
```sql
CREATE TABLE learning_interventions (
    id TEXT PRIMARY KEY,
    question_pattern TEXT NOT NULL,
    occurrence_count INTEGER,
    intervention_type TEXT,  -- tutorial, reference, automation
    content TEXT,  -- Generated resource
    created_at INTEGER NOT NULL,
    helped BOOLEAN
);
```

**API:**
```python
def detect_repeated_question(question: str) -> Optional[Intervention]
def create_tutorial(topic: str) -> str
def create_reference(topic: str) -> str
```

**Tests:** 8 tests (detection, generation, tracking)

---

## F65: Mistake Compounding Detector

**Problem:** One mistake cascades into many errors.

**What it does:**
- Tracks mistake → downstream error chains
- Root cause analysis
- Predicts cascade risk
- Prevents compound errors

**Schema:**
```sql
CREATE TABLE mistake_cascades (
    id TEXT PRIMARY KEY,
    root_mistake_id TEXT NOT NULL,
    downstream_error_ids TEXT,  -- JSON array
    cascade_depth INTEGER,
    total_cost TEXT,  -- Time/effort wasted
    prevention_strategy TEXT,
    created_at INTEGER NOT NULL
);
```

**API:**
```python
def detect_cascade(mistake_id: str) -> Optional[Cascade]
def analyze_root_cause(error_id: str) -> Optional[str]
def suggest_prevention(cascade_id: str) -> str
```

**Tests:** 10 tests (cascade detection, root cause, prevention)

---

## F66-74: Integration Features (Deferred)

**F66: Screenshot context extraction** - Already covered in F45 (Image Context Extraction)

**F67: Voice tone analysis** - Extension of F44 (Voice Memory Capture)

**F68-70: Meeting/Email/Notion integration** - Defer until core features stable

**F71-73: Git/Code Review/Docs** - Defer until core features stable

**F74: Curiosity-driven exploration** - Research/exploration agent (complex, defer)

---

## Implementation Priority

**Tier 1 (Build first):**
- F51: Temporal Pattern Prediction (high value, clear use case)
- F52: Conversation Momentum Tracking (debugging aid)
- F58: Decision Regret Detection (prevents repeated mistakes)

**Tier 2 (Build next):**
- F53: Energy-Aware Scheduling (productivity boost)
- F59: Expertise Mapping (agent routing)
- F60: Context Decay Prediction (maintenance)

**Tier 3 (Build later):**
- F54: Context Pre-Loading (requires F51)
- F56: Client Pattern Transfer (privacy concerns)
- F64: Learning Intervention (content generation)
- F65: Mistake Compounding (complex analysis)

**Defer:**
- F66-74: Integration features (wait for stability)

---

## Test Coverage Target

**Total tests needed:** ~86 tests for F51-65
**Coverage goal:** >80% per feature
**Integration tests:** 10 tests for pattern interactions

---

## Database Size Impact

**At 10K memories:**
- Temporal patterns: ~500 patterns (~2MB)
- Momentum tracking: ~1K sessions (~3MB)
- Energy patterns: ~168 entries (24h × 7 days) (~1MB)
- Context preload queue: ~100 entries (~1MB)
- Decision outcomes: ~1K decisions (~5MB)
- Expertise mapping: ~50 agents × 20 domains (~1MB)

**Total overhead:** ~13MB (reasonable)

---

## API Cost Impact

**LLM-heavy features:**
- F64: Learning Intervention (tutorial generation, infrequent)
- F65: Mistake Compounding (root cause analysis, infrequent)

**No additional API cost:**
- F51, F52, F53, F54, F56, F58, F59, F60 (all pattern detection + local operations)

**Estimated cost at 10K scale:** <$2/day additional
