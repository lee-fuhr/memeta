# Features 23-32: Intelligence & Automation Layer

**Version:** 1.0
**Created:** 2026-02-12
**Status:** In Progress (1/10 complete)
**Developer:** Dev Director (memory-dev team)

---

## Overview

Intelligence and Automation features build on the core memory system (Features 1-22) to add:
- **Intelligence Layer (F23-27):** Version tracking, clustering, relationships, review scheduling, cross-project sharing
- **Automation Layer (F28-32):** Triggers, alerts, smart search, summarization, quality scoring

**Database:** Single unified `intelligence.db` with namespaced tables for all features

---

## Feature 23: Memory Versioning ✅

**Status:** SHIPPED (2026-02-12)
**Code:** `src/intelligence/versioning.py`
**Tests:** 21/21 passing
**Database:** `memory_versions` table in `intelligence.db`

### What it does

Tracks complete edit history for every memory. Every change creates a new version entry, enabling:
- Full version history retrieval
- Diff between any two versions
- Rollback to previous versions (preserves history by creating new version)
- "Why did this change?" queries

### Database schema

```sql
CREATE TABLE memory_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    importance REAL NOT NULL,
    changed_by TEXT DEFAULT 'user',
    change_reason TEXT,
    timestamp INTEGER NOT NULL,
    UNIQUE(memory_id, version)
);

CREATE INDEX idx_versions_memory
ON memory_versions(memory_id, timestamp DESC);
```

### API

```python
from src.intelligence.versioning import MemoryVersioning

versioning = MemoryVersioning()

# Create a new version
v = versioning.create_version(
    memory_id="mem_001",
    content="Always verify work before claiming completion",
    importance=0.9,
    changed_by="user",
    change_reason="Updated based on mistake"
)

# Get version history
history = versioning.get_version_history("mem_001")
for v in history:
    print(f"v{v.version}: {v.content} (by {v.changed_by})")

# Get specific version
v2 = versioning.get_version("mem_001", version_number=2)

# Get latest version
latest = versioning.get_latest_version("mem_001")

# Diff between versions
diff = versioning.diff_versions("mem_001", version_a=1, version_b=3)
print(f"Content changed: {diff['content_changed']}")
print(f"Before: {diff['content_diff']['before']}")
print(f"After: {diff['content_diff']['after']}")

# Rollback (creates new version with old content)
rollback = versioning.rollback_to_version("mem_001", version_number=1)
print(f"Created v{rollback.version} with content from v1")

# Utility methods
count = versioning.get_version_count("mem_001")
all_versioned = versioning.get_all_versioned_memories()
recent = versioning.get_recent_changes(limit=10)
```

### Integration points

- **Session consolidator:** Call `create_version()` when memory is edited
- **LLM extractor:** Set `changed_by="llm"` when AI makes changes
- **Memory dashboard:** Show version history timeline
- **Memory-ts client:** Sync versions when memory is updated

### Design decisions

**Rollback preserves history:** Instead of deleting versions, rollback creates a NEW version with the old content. This maintains complete audit trail.

**Version numbers per memory:** Each memory has independent version numbering starting at 1.

**Timestamps for ordering:** Use Unix timestamps for precise ordering, especially when multiple versions created rapidly.

**Change reason optional:** Not all edits need justification, but capturing it when available helps with "why did this change?" queries.

### Example usage

**Scenario: Memory gets refined over time**

```python
versioning = MemoryVersioning()

# Initial capture
v1 = versioning.create_version(
    "mem_001",
    "Tests are important",
    0.5,
    changed_by="user"
)

# User refines it
v2 = versioning.create_version(
    "mem_001",
    "Always run tests before claiming completion",
    0.7,
    changed_by="user",
    change_reason="Made more specific"
)

# LLM enhances it further
v3 = versioning.create_version(
    "mem_001",
    "Always run tests AND verify they pass before claiming task completion",
    0.9,
    changed_by="llm",
    change_reason="Added verification step based on pattern of test failures"
)

# Later: User wants to see evolution
history = versioning.get_version_history("mem_001")
# Returns v1, v2, v3 in order

# Or compare specific versions
diff = versioning.diff_versions("mem_001", 1, 3)
# Shows journey from vague → specific → actionable
```

### Test coverage

21 tests covering:
- Version creation (4 tests): first version, subsequent versions, independent numbering, defaults
- Version retrieval (6 tests): history, empty, specific version, nonexistent, latest, latest nonexistent
- Diff functionality (3 tests): changes, no changes, nonexistent version
- Rollback (3 tests): rollback to version, preserves history, nonexistent version
- Utility methods (5 tests): version count, count zero, all versioned memories, recent changes, limit

### Known limitations

- No automatic versioning on every memory edit (requires explicit `create_version()` call)
- No version deletion (by design - preserves complete history)
- Version numbers are integers, not semantic versioning
- No branching or merging (linear version history only)

---

## Feature 24: Clustering & Topic Detection 🚧

**Status:** NOT STARTED
**Planned:** `src/intelligence/clustering.py`

### What it will do

Auto-group related memories by semantic similarity using K-means clustering. LLM generates human-readable topic labels for each cluster.

### Planned capabilities

- K-means clustering on memory embeddings (sentence-transformers)
- Automatic cluster count selection (elbow method)
- LLM-generated topic labels (2-4 words)
- Re-clustering on demand or schedule
- Browse memories by topic in UI

### Database schema

```sql
CREATE TABLE memory_clusters (
    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_label TEXT NOT NULL,
    keywords TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_updated INTEGER NOT NULL,
    member_count INTEGER DEFAULT 0
);

CREATE TABLE cluster_memberships (
    memory_id TEXT NOT NULL,
    cluster_id INTEGER NOT NULL,
    similarity_score REAL NOT NULL,
    added_at INTEGER NOT NULL,
    PRIMARY KEY (memory_id, cluster_id),
    FOREIGN KEY (cluster_id) REFERENCES memory_clusters(cluster_id)
);
```

---

## Feature 25: Memory Relationships Graph 🚧

**Status:** NOT STARTED
**Planned:** `src/intelligence/relationships.py`

### What it will do

Track explicit relationships between memories: "led_to", "contradicts", "references", "supports".

### Database schema

```sql
CREATE TABLE memory_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_memory_id TEXT NOT NULL,
    to_memory_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL,
    auto_detected BOOLEAN DEFAULT FALSE,
    UNIQUE(from_memory_id, to_memory_id, relationship_type)
);
```

---

## Feature 26: Forgetting Curve Integration 🚧

**Status:** NOT STARTED
**Planned:** Extend `src/fsrs_scheduler.py`

### What it will do

Integrates FSRS-6 review scheduling (already implemented) with notification system for "due for review" memories.

---

## Feature 27: Cross-Project Sharing 🚧

**Status:** NOT STARTED
**Planned:** `src/intelligence/sharing.py`

### What it will do

Privacy-aware sharing of universal insights across client projects. Suggests "this worked for Client A, try for Client B?"

### Database schema

```sql
CREATE TABLE sharing_rules (
    memory_id TEXT PRIMARY KEY,
    is_universal BOOLEAN DEFAULT FALSE,
    privacy_level TEXT DEFAULT 'private',
    allowed_projects TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE sharing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    source_project TEXT NOT NULL,
    target_project TEXT NOT NULL,
    shared_at INTEGER NOT NULL,
    shared_by TEXT DEFAULT 'auto'
);
```

---

## Feature 28: Memory Triggers 🚧

**Status:** NOT STARTED
**Planned:** `src/automation/triggers.py`

### What it will do

Rule engine: "When memory X detected, execute action Y". Example: "When client mentions deadline, add to Todoist".

---

## Feature 29: Smart Alerts 🚧

**Status:** NOT STARTED
**Planned:** `src/automation/alerts.py`

### What it will do

Proactive notifications for expiring memories, detected patterns, contradictions. Daily digest of important alerts.

---

## Feature 30: Memory-Aware Search 🚧

**Status:** NOT STARTED
**Planned:** `src/automation/search.py`

### What it will do

Natural language queries: "Find memories about X from last month", "What did I learn about Y while working on Z?"

---

## Feature 31: Auto-Summarization 🚧

**Status:** NOT STARTED
**Planned:** `src/automation/summarization.py`

### What it will do

LLM synthesis of all memories on a topic. "Tell me everything about X" → coherent narrative with timeline.

---

## Feature 32: Quality Scoring 🚧

**Status:** NOT STARTED
**Planned:** `src/automation/quality.py`

### What it will do

Auto-detect low-quality memories (too vague, duplicate, unclear). Suggest improvements or archival.

---

## Development roadmap

### Completed
- ✅ F23: Memory Versioning (2026-02-12)

### In Progress
- 🚧 F24: Clustering (next up)

### Remaining
- ⏸️ F25: Memory Relationships
- ⏸️ F26: Forgetting Curve Integration
- ⏸️ F27: Cross-Project Sharing
- ⏸️ F28: Memory Triggers
- ⏸️ F29: Smart Alerts
- ⏸️ F30: Memory-Aware Search
- ⏸️ F31: Auto-Summarization
- ⏸️ F32: Quality Scoring

### Timeline
- **Week 1 (current):** F23-27 (Intelligence Layer)
- **Week 2:** F28-32 (Automation Layer)
- **Week 3:** Integration testing, documentation, deployment

---

## Integration with existing features

### With Features 1-22
- **Session consolidator:** Version memories on edit
- **FSRS scheduler:** F26 adds review notifications
- **Pattern detector:** F25 auto-detects relationships
- **Memory clustering:** F24 groups memories for synthesis
- **Weekly synthesis:** F31 uses clusters for narrative generation

### With Operations scripts
- **EA Brain:** F27 shares client learnings
- **Todoist:** F28 triggers create tasks
- **Pushover:** F29 sends alert notifications
- **Dashboard:** All features export metrics

---

## Testing strategy

- **Unit tests:** Each feature has comprehensive test suite (target 80%+ coverage)
- **Integration tests:** Cross-feature interaction tests
- **Performance tests:** Clustering on 1000+ memories, search latency
- **Edge case tests:** Empty data, corrupted state, concurrent access

---

## Documentation checklist

Per feature:
- [ ] API documentation (docstrings)
- [ ] Usage examples
- [ ] Integration guide
- [ ] Database schema
- [ ] Test coverage report
- [ ] Known limitations

System-wide:
- [x] This document (features-23-32.md)
- [ ] Update main README.md
- [ ] Update roadmap.md
- [ ] Update changelog.md
- [ ] LaunchAgent configs (F28-29)

---

*Last updated: 2026-02-12 19:50 PST*
*Next update: After F24 ships*
