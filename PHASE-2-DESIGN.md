# Phase 2: FSRS-6 promotion system

## Problem

785 memories in memory-ts (468 project, 317 global). No automated way to:
1. Detect when a project-specific learning is actually a universal principle
2. Schedule reviews of memories for validation
3. Promote validated patterns from project → global scope
4. Group related memories into coherent themes

## What we're building

### 1. FSRS scheduler (`src/fsrs_scheduler.py`)
Simplified FSRS-6 for memory review scheduling.

**Core concept:** When a similar insight appears across multiple sessions/projects, that's a "successful review" - the memory gets reinforced and moves toward promotion.

**Fields per memory:**
- `stability` - How well-established (0.0-10.0, starts at 1.0)
- `difficulty` - How often it needs reinforcement (0.0-1.0, starts at 0.5)
- `due_date` - Next scheduled review date
- `review_count` - Number of successful validations
- `last_review` - Date of last validation

**FSRS-6 interval formula (simplified):**
```
next_interval = stability * (1 + (grade - 1) * factor)
where grade = 1 (fail), 2 (hard), 3 (good), 4 (easy)
```

**Storage:** SQLite database at `fsrs.db` in memory-system-v1 directory

### 2. Pattern detector (`src/pattern_detector.py`)
Find cross-session and cross-project reinforcement signals.

**How it works:**
1. Compare new session memories against existing memories
2. Use same fuzzy matching as deduplication (word overlap)
3. When overlap >= 50% (lower than dedup's 70%): that's a "reinforcement"
4. Log the reinforcement to FSRS scheduler
5. Track which projects validated the pattern

**Reinforcement signals:**
- Same insight from different session → `grade: good (3)`
- Same insight from different project → `grade: easy (4)` (stronger signal)
- Insight not seen in N reviews → `grade: hard (2)`

### 3. Promotion executor (`src/promotion_executor.py`)
Promote validated memories from project → global scope.

**Promotion criteria (ALL must be met):**
- `stability >= 3.0` (well-established)
- `review_count >= 3` (seen at least 3 times)
- Cross-project validation (seen in 2+ different projects)
- `importance >= 0.7` (not trivial)

**What promotion does:**
1. Update memory-ts: `scope: project` → `scope: global`
2. Add tag: `#promoted`
3. Log promotion event
4. Queue for weekly synthesis

### 4. Memory clustering (`src/memory_clustering.py`)
Group related memories by theme.

**Algorithm:** Simple keyword-based clustering (no ML needed)
1. Extract keywords from each memory
2. Build keyword co-occurrence matrix
3. Cluster memories with high keyword overlap (>40%)
4. Name clusters by most frequent keywords

**Use cases:**
- Dashboard shows clusters instead of flat list
- Synthesis can work per-cluster
- Identify knowledge gaps (clusters with few memories)

### 5. Weekly synthesis automation
LaunchAgent that runs Friday 5pm.

**What it does:**
1. Collect newly promoted memories since last run
2. Group by cluster/theme
3. Generate draft update for universal-learnings.md
4. Send Pushover notification to Lee for review

## Architecture

```
Daily (3 AM):             Weekly (Friday 5 PM):
  decay + archival          pattern detection
  health check              FSRS review scheduling
                            promotion execution
                            synthesis generation
                            pushover notification

Session end:
  pattern extraction
  LLM extraction
  dedup + save
  pattern detection (against existing memories)
```

## Data schema (fsrs.db)

```sql
CREATE TABLE memory_reviews (
    memory_id TEXT PRIMARY KEY,
    stability REAL DEFAULT 1.0,
    difficulty REAL DEFAULT 0.5,
    due_date TEXT,
    review_count INTEGER DEFAULT 0,
    last_review TEXT,
    projects_validated TEXT DEFAULT '[]',  -- JSON array
    promoted BOOLEAN DEFAULT FALSE,
    promoted_date TEXT
);

CREATE TABLE review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT,
    review_date TEXT,
    grade INTEGER,  -- 1=fail, 2=hard, 3=good, 4=easy
    new_stability REAL,
    new_interval_days REAL,
    source_session TEXT,
    source_project TEXT
);

CREATE TABLE memory_clusters (
    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    keywords TEXT,  -- JSON array
    memory_ids TEXT,  -- JSON array
    created TEXT,
    updated TEXT
);
```

## Success criteria

- [ ] FSRS scheduler correctly calculates review intervals
- [ ] Pattern detector finds cross-session reinforcements
- [ ] Promotion executor promotes when all criteria met
- [ ] Clustering groups related memories coherently
- [ ] Weekly synthesis generates readable draft
- [ ] All modules have full test coverage
- [ ] LaunchAgent runs weekly without intervention
- [ ] Pushover notification reaches Lee's phone
