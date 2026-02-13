# F27: Memory Reinforcement Scheduler - Implementation Plan

**Status:** Planning
**Priority:** Tier 1 (High - FSRS integration needed)
**Estimated effort:** 6 hours (2h code, 2h tests, 2h integration)

---

## Goals

**Primary:**
- Schedule memory reviews based on FSRS intervals
- Surface memories due for reinforcement
- Track review history
- Adjust scheduling based on grades

**Secondary:**
- Daily review digest
- Smart scheduling (avoid overload)
- Review reminders

---

## Database Schema

```sql
CREATE TABLE review_schedule (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL UNIQUE,  -- One schedule per memory
    due_at INTEGER NOT NULL,
    last_reviewed INTEGER,
    review_count INTEGER DEFAULT 0,
    difficulty REAL,  -- From FSRS
    stability REAL,   -- From FSRS
    next_interval_days INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_review_due ON review_schedule(due_at ASC);
CREATE INDEX idx_review_memory ON review_schedule(memory_id);

CREATE TABLE review_history (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    reviewed_at INTEGER NOT NULL,
    grade TEXT NOT NULL,  -- FAIL, HARD, GOOD, EASY
    previous_interval_days INTEGER,
    new_interval_days INTEGER,
    difficulty_before REAL,
    difficulty_after REAL,
    stability_before REAL,
    stability_after REAL
);

CREATE INDEX idx_history_memory ON review_history(memory_id, reviewed_at DESC);
```

**Why two tables:**
- `review_schedule`: Current state (one row per memory)
- `review_history`: Audit trail (many rows per memory)

---

## API Design

```python
class ReinforcementScheduler:
    def __init__(self, db_path: str = None, fsrs_db_path: str = None):
        """Initialize with intelligence.db and fsrs.db"""

    def schedule_memory(
        self,
        memory_id: str,
        initial_interval_days: int = 1
    ) -> str:
        """
        Add memory to review schedule.
        Uses FSRS defaults if memory not in FSRS DB yet.
        Returns schedule ID.
        """

    def get_due_reviews(
        self,
        limit: int = 10,
        project_id: Optional[str] = None
    ) -> List[Memory]:
        """
        Get memories due for review.
        Ordered by: overdue first, then by importance.
        """

    def record_review(
        self,
        memory_id: str,
        grade: str  # FAIL, HARD, GOOD, EASY
    ):
        """
        Record review and reschedule.
        Updates FSRS DB and review_schedule.
        """

    def reschedule_memory(
        self,
        memory_id: str,
        new_due_at: datetime = None
    ):
        """
        Manually reschedule memory.
        If new_due_at None, calculates from FSRS.
        """

    def get_review_stats(
        self,
        memory_id: Optional[str] = None
    ) -> dict:
        """
        Get review statistics.
        If memory_id provided, stats for that memory.
        Otherwise, global stats.
        """

    def get_daily_review_count(self) -> int:
        """Number of reviews due today"""

    def get_overdue_count(self) -> int:
        """Number of overdue reviews"""
```

---

## Integration with FSRS

**Current FSRS implementation:** `fsrs.db` with tables:
- `fsrs`: Tracks D (difficulty), S (stability), last_reviewed, next_review
- `fsrs_history`: Review history with grades

**Integration strategy:**

1. **On schedule_memory():**
   - Check if memory exists in FSRS DB
   - If yes, read next_review → due_at
   - If no, create FSRS entry with defaults

2. **On record_review():**
   - Call FSRS `record_review()` first
   - Read updated D, S, next_review from FSRS
   - Update review_schedule with new due_at

3. **On get_due_reviews():**
   - Query review_schedule WHERE due_at <= NOW()
   - Join with memory-ts to get full Memory objects
   - Filter by project_id if provided

**Why not just use FSRS DB?**
- FSRS DB doesn't have `due_at` index for fast queries
- review_schedule adds project filtering, importance sorting
- Separates scheduling logic from spaced repetition math

---

## Integration with Pattern Detector

**Problem:** Pattern detector records reviews but doesn't schedule next review.

**Solution:**
```python
# In pattern_detector.py
from intelligence.reinforcement_scheduler import ReinforcementScheduler

def record_reinforcement(memory_id: str, grade: str):
    # Existing FSRS logic
    current_state = fsrs_db.get_state(memory_id)
    new_state = fsrs.review(current_state, grade)
    fsrs_db.save_state(memory_id, new_state)

    # NEW: Update schedule
    scheduler = ReinforcementScheduler()
    scheduler.record_review(memory_id, grade)
```

---

## Scheduling Algorithm

**Priority formula:**
```
priority_score = overdue_days * 2 + importance * 100

Where:
- overdue_days = max(0, days_since_due)
- importance = memory.importance (0.0-1.0)
```

**Why this formula:**
- Overdue reviews prioritized (×2 multiplier)
- Important memories surface even if not overdue
- Prevents review overload (limit=10 default)

**Example:**
```
Memory A: 5 days overdue, importance 0.7 → score = 10 + 70 = 80
Memory B: 0 days overdue, importance 0.9 → score = 0 + 90 = 90
Memory C: 2 days overdue, importance 0.5 → score = 4 + 50 = 54

Order: B (90), A (80), C (54)
```

---

## Review Workflow

**User flow:**

1. Morning: Check `/triage` or dedicated review command
2. System shows: "5 memories due for review"
3. User reviews each memory (reads, confirms understanding)
4. User grades: FAIL (forgot), HARD (struggled), GOOD (remembered), EASY (trivial)
5. System reschedules based on grade
6. Repeat for next review

**Implementation:**
```python
# In morning triage ritual
scheduler = ReinforcementScheduler()
due_reviews = scheduler.get_due_reviews(limit=5)

if due_reviews:
    print(f"\n📚 {len(due_reviews)} memories due for review:")
    for i, memory in enumerate(due_reviews, 1):
        print(f"{i}. {memory.content[:80]}...")

    # User reviews and grades
    # (manual for now, could be interactive CLI later)
```

---

## Test Strategy

### Unit Tests (tests/intelligence/test_reinforcement_scheduler.py)

**Test coverage:** 12 tests

1. **Initialization**
   - `test_scheduler_initialization`: Schema creation
   - `test_scheduler_with_existing_fsrs`: Integration with existing FSRS DB

2. **Scheduling**
   - `test_schedule_new_memory`: Add memory to schedule
   - `test_schedule_existing_memory`: Update existing schedule
   - `test_schedule_with_fsrs_data`: Use existing FSRS state

3. **Retrieval**
   - `test_get_due_reviews_empty`: No reviews due
   - `test_get_due_reviews_ordered`: Correct priority ordering
   - `test_get_due_reviews_limit`: Respects limit parameter
   - `test_get_due_reviews_filtered_by_project`: Project filtering

4. **Recording**
   - `test_record_review_updates_schedule`: due_at updated after review
   - `test_record_review_updates_fsrs`: FSRS DB updated
   - `test_record_review_history`: review_history populated

5. **Statistics**
   - `test_get_review_stats_global`: Global statistics
   - `test_get_review_stats_per_memory`: Per-memory statistics

### Integration Tests (tests/integration/test_scheduler_integration.py)

**Test coverage:** 5 tests

1. `test_pattern_detector_integration`: record_reinforcement() calls scheduler
2. `test_triage_shows_due_reviews`: Morning triage integration
3. `test_fsrs_consistency`: FSRS and scheduler stay in sync
4. `test_review_workflow_end_to_end`: Full review cycle
5. `test_overdue_prioritization`: Overdue reviews surface first

---

## Edge Cases

1. **Memory deleted but schedule exists**
   - Accept (schedule is orphaned)
   - get_due_reviews() filters out non-existent memories

2. **FSRS DB out of sync with schedule**
   - On record_review(), FSRS is source of truth
   - Schedule updates from FSRS state

3. **Review overload (100+ due)**
   - limit=10 prevents UI overload
   - Oldest/most important surface first

4. **Manual reschedule conflicts with FSRS**
   - Manual reschedule wins
   - Next review recalculates from FSRS

---

## Performance

**At 10K memories:**
- 10K rows in review_schedule (~5MB)
- Query with idx_review_due: <5ms
- Daily reviews: ~50-100 due (FSRS curve)

**Optimization:**
- Index on due_at for fast filtering
- Limit default=10 prevents large result sets

---

## Future Enhancements

1. **Review reminders:** LaunchAgent daily notification
2. **Adaptive limit:** More reviews if user is on a roll
3. **Review clustering:** Group related memories for batch review
4. **Gamification:** Review streaks, completion percentage

---

## Success Criteria

**Minimum viable:**
- ✅ Schedule memories with FSRS integration
- ✅ Query due reviews with priority ordering
- ✅ Record reviews and update schedule
- ✅ 12+ unit tests passing
- ✅ Integration with pattern_detector

**Nice to have:**
- Morning triage integration
- Review statistics dashboard
- Daily review reminders

---

## Implementation Checklist

- [ ] Define schema
- [ ] Design API
- [ ] Implement ReinforcementScheduler class
- [ ] Write unit tests (12)
- [ ] Write integration tests (5)
- [ ] Integrate with pattern_detector
- [ ] Document API
- [ ] Update CHANGELOG.md
- [ ] Commit with tests passing
