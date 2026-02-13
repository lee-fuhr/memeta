# Features 24-32: Intelligence Enhancement Layer

**Status:** Planning phase
**Category:** Core intelligence features that amplify existing memory system
**Database:** intelligence.db (shared schema)

---

## F24: Memory Relationship Mapping

**Problem:** Memories exist in isolation. You can't see how they connect.

**What it does:**
- Builds explicit relationship graph between memories
- Tracks causal links (A led to decision B)
- Identifies contradicting memories
- Shows dependency chains (A requires B, B requires C)

**Schema:**
```sql
CREATE TABLE memory_relationships (
    id TEXT PRIMARY KEY,
    from_memory_id TEXT NOT NULL,
    to_memory_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,  -- causal, contradicts, supports, requires, related
    strength REAL DEFAULT 0.5,         -- 0.0-1.0 confidence
    evidence TEXT,                      -- Why they're related
    created_at INTEGER NOT NULL,
    UNIQUE(from_memory_id, to_memory_id, relationship_type)
);
```

**API:**
```python
def link_memories(from_id: str, to_id: str, type: str, evidence: str) -> str
def get_related_memories(memory_id: str, type: str = None) -> List[Memory]
def find_causal_chain(start_id: str, end_id: str) -> List[Memory]
```

**Tests:** 10 tests (link creation, retrieval, chain finding, duplicate prevention)

---

## F25: Memory Clustering

**Problem:** Hard to see themes across many memories.

**What it does:**
- Auto-clusters memories by topic/theme
- Uses semantic similarity + temporal co-occurrence
- Updates clusters as new memories arrive
- Surfaces clusters for review

**Schema:**
```sql
CREATE TABLE memory_clusters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    memory_ids TEXT NOT NULL,  -- JSON array
    centroid_embedding BLOB,    -- Average embedding
    cohesion_score REAL,        -- How tight the cluster
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

**Algorithm:**
- DBSCAN clustering with semantic distance
- Min cluster size: 3 memories
- Distance threshold: 0.3 (semantic similarity >0.7)

**API:**
```python
def cluster_memories(project_id: str = None) -> List[Cluster]
def get_cluster(cluster_id: str) -> Cluster
def add_to_cluster(cluster_id: str, memory_id: str)
```

**Tests:** 12 tests (clustering, cohesion, updates, edge cases)

---

## F26: Memory Summarization

**Problem:** Too many memories to review individually.

**What it does:**
- Generates cluster summaries
- Monthly/weekly memory digests
- Project-level summaries
- Timeline views

**Schema:**
```sql
CREATE TABLE memory_summaries (
    id TEXT PRIMARY KEY,
    summary_type TEXT NOT NULL,  -- cluster, project, period
    target_id TEXT,               -- cluster_id or project_id
    period_start INTEGER,
    period_end INTEGER,
    summary TEXT NOT NULL,
    memory_count INTEGER,
    created_at INTEGER NOT NULL
);
```

**API:**
```python
def summarize_cluster(cluster_id: str) -> str
def summarize_project(project_id: str, days: int = 30) -> str
def summarize_period(start: datetime, end: datetime) -> str
```

**Tests:** 8 tests (cluster summaries, project summaries, period summaries)

---

## F27: Memory Reinforcement Scheduler

**Problem:** FSRS tracks reviews but doesn't trigger them.

**What it does:**
- Scheduler for memory reviews based on FSRS intervals
- Surfaces memories due for reinforcement
- Tracks review history
- Adjusts scheduling based on grades

**Schema:**
```sql
CREATE TABLE review_schedule (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    due_at INTEGER NOT NULL,
    last_reviewed INTEGER,
    review_count INTEGER DEFAULT 0,
    difficulty REAL,
    stability REAL,
    INDEX(due_at)
);
```

**API:**
```python
def get_due_reviews(limit: int = 10) -> List[Memory]
def record_review(memory_id: str, grade: str)  # FAIL/HARD/GOOD/EASY
def reschedule_memory(memory_id: str)
```

**Tests:** 10 tests (scheduling, rescheduling, FSRS integration)

---

## F28: Memory Search Optimization

**Problem:** Search is slow at scale, no ranking.

**What it does:**
- Caches frequently-searched terms
- Pre-computes popular query embeddings
- Ranks results by relevance + recency + importance
- A/B tests ranking algorithms

**Schema:**
```sql
CREATE TABLE search_cache (
    query_hash TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    results TEXT NOT NULL,  -- JSON array of memory IDs
    hits INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE search_analytics (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    result_count INTEGER,
    selected_memory_id TEXT,  -- Which result user chose
    position INTEGER,          -- Position in results
    created_at INTEGER NOT NULL
);
```

**API:**
```python
def search_with_cache(query: str, use_cache: bool = True) -> List[Memory]
def record_selection(query: str, memory_id: str, position: int)
def optimize_ranking()  -- Learn from selection patterns
```

**Tests:** 15 tests (caching, analytics, ranking, optimization)

---

## F29: Memory Import/Export

**Problem:** Can't move memories between systems, no backup format.

**What it does:**
- Export memories to JSON/CSV
- Import from other systems (Obsidian, Roam, Notion)
- Merge imports intelligently (dedupe, resolve conflicts)
- Maintains provenance during import

**Schema:**
```sql
CREATE TABLE import_history (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,  -- obsidian, roam, notion, json
    file_path TEXT,
    memory_count INTEGER,
    duplicates_found INTEGER,
    created_at INTEGER NOT NULL
);
```

**API:**
```python
def export_memories(format: str = "json", project_id: str = None) -> str
def import_from_json(file_path: str, merge_strategy: str = "dedupe")
def import_from_obsidian(vault_path: str)
def import_from_notion(export_zip: str)
```

**Tests:** 12 tests (export formats, import sources, deduplication, conflicts)

---

## F30: Memory Archival

**Problem:** Old memories clutter active set but shouldn't be deleted.

**What it does:**
- Auto-archives stale memories (not accessed in 180 days)
- Manual archive with reason tracking
- Archived memories excluded from search by default
- Restore with full history

**Schema:**
```sql
CREATE TABLE archive_log (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    archived_at INTEGER NOT NULL,
    reason TEXT,  -- auto_stale, manual, superseded
    archived_by TEXT,  -- user or system
    restored_at INTEGER
);
```

**API:**
```python
def archive_memory(memory_id: str, reason: str)
def restore_memory(memory_id: str)
def get_archived_memories(project_id: str = None) -> List[Memory]
def auto_archive_stale(days_threshold: int = 180)
```

**Tests:** 10 tests (archiving, restoring, auto-archive, search exclusion)

---

## F31: Memory Annotations

**Problem:** Can't add notes to existing memories without editing them.

**What it does:**
- Add annotations/comments to memories
- Track annotation history
- Tag annotations by type (clarification, correction, addition)
- Surface annotated memories

**Schema:**
```sql
CREATE TABLE memory_annotations (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    annotation_type TEXT NOT NULL,  -- clarification, correction, addition, question
    content TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    created_by TEXT  -- user or agent name
);
```

**API:**
```python
def annotate_memory(memory_id: str, type: str, content: str, author: str = "user")
def get_annotations(memory_id: str) -> List[Annotation]
def search_annotated_memories() -> List[Memory]
```

**Tests:** 8 tests (annotation creation, retrieval, types, search)

---

## F32: Memory Validation

**Problem:** Memories can become outdated/incorrect, no validation mechanism.

**What it does:**
- Flags memories for validation
- Tracks validation state (validated, needs_review, invalidated)
- Auto-flags memories with contradictions
- Validation expiry (revalidate after 90 days)

**Schema:**
```sql
CREATE TABLE memory_validation (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    validation_state TEXT NOT NULL,  -- validated, needs_review, invalidated
    validated_at INTEGER,
    validated_by TEXT,
    expires_at INTEGER,  -- When validation expires
    validation_notes TEXT,
    UNIQUE(memory_id)
);
```

**API:**
```python
def validate_memory(memory_id: str, notes: str = None)
def invalidate_memory(memory_id: str, reason: str)
def flag_for_review(memory_id: str, reason: str)
def get_memories_needing_validation() -> List[Memory]
```

**Tests:** 10 tests (validation, invalidation, expiry, flagging)

---

## Implementation Priority

**High priority:**
- F24: Memory Relationship Mapping (enables many other features)
- F27: Memory Reinforcement Scheduler (FSRS integration)
- F28: Memory Search Optimization (performance)

**Medium priority:**
- F25: Memory Clustering (UX improvement)
- F26: Memory Summarization (UX improvement)
- F30: Memory Archival (maintenance)

**Lower priority:**
- F29: Memory Import/Export (nice-to-have)
- F31: Memory Annotations (nice-to-have)
- F32: Memory Validation (nice-to-have)

---

## Test Coverage Target

**Total tests needed:** ~95 tests across F24-32
**Coverage goal:** >80% per feature
**Integration tests:** 10 tests for cross-feature interactions

---

## Database Size Impact

**At 10K memories:**
- Relationships: ~50K relationships (~5MB)
- Clusters: ~500 clusters (~2MB)
- Summaries: ~100 summaries (~1MB)
- Schedule: 10K entries (~5MB)
- Search cache: ~1K queries (~2MB)
- Annotations: ~5K annotations (~5MB)

**Total overhead:** ~20MB for 10K memories (reasonable)

---

## API Cost Impact

**LLM-heavy features:**
- F26: Summarization (1 call per summary, infrequent)
- F25: Clustering names (1 call per cluster, infrequent)

**No additional API cost:**
- F24, F27, F28, F29, F30, F31, F32 (all local operations)

**Estimated cost at 10K scale:** <$1/day additional
