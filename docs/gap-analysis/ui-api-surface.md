# UI API surface

**Created:** 2026-02-14
**Purpose:** Document every endpoint the backend must expose to power a ZeroBot-style frontend.

ZeroBot UI features: inline memory event cards, feedback ingestion, version history, diffs, search, momentum/health state, event stream.

---

## Overview

The memory system currently has no HTTP surface. All 58 features are Python modules invoked via scripts or LaunchAgents. To power a frontend, a FastAPI server must be created at `src/api/server.py`. The endpoints below map to the existing `src/` modules that back them.

**Proposed server:** `uvicorn src.api.server:app --port 8767`
**Auth strategy:** Local-only (localhost binding). No auth required for single-user desktop app.
**Format:** JSON, snake_case keys throughout.

---

## Endpoint catalog

### Core memory operations

---

#### `POST /memories`

**Purpose:** Save a new memory with optional session provenance.

**Input schema:**
```json
{
  "content": "string (required)",
  "session_id": "string (optional) — session that produced this memory",
  "tags": ["string"] "(optional)",
  "intent": "high|medium|low (optional, default: medium)",
  "type": "breakthrough|decision|personal|technical|... (optional)"
}
```

**Output schema:**
```json
{
  "id": "string",
  "content": "string",
  "session_id": "string|null",
  "created_at": "ISO 8601",
  "tags": ["string"],
  "importance": 0.7,
  "confidence": 0.5,
  "status": "saved|duplicate_merged|contradiction_resolved"
}
```

**Backing module:** `src/memory_ts_client.py` → `add()`, `src/contradiction_detector.py` (called inline).
**Gap:** Requires Gap 1 (provenance) and Gap 6 (circuit breaker) to be production-ready.

---

#### `GET /memories/search`

**Purpose:** Search memories using hybrid semantic + BM25 search.

**Input schema (query params):**
```
q: string (required) — search query
top_k: int (optional, default: 10)
include_archived: bool (optional, default: false)
tag: string (optional) — filter by tag
min_importance: float (optional, default: 0.0)
```

**Output schema:**
```json
{
  "results": [
    {
      "id": "string",
      "content": "string",
      "score": 0.87,
      "semantic_score": 0.91,
      "bm25_score": 0.73,
      "tags": ["string"],
      "created_at": "ISO 8601",
      "session_id": "string|null"
    }
  ],
  "query": "string",
  "total": 42,
  "search_method": "hybrid|semantic|keyword"
}
```

**Backing module:** `src/hybrid_search.py` → `hybrid_search()`, `src/semantic_search.py`.
**Gap:** Requires Gap 3 (hybrid search fix) for scores to be meaningful.

---

#### `GET /memories/recent`

**Purpose:** Get the most recently created or accessed memories. Used for the "Recent activity" sidebar in the frontend.

**Input schema (query params):**
```
n: int (optional, default: 20)
days: int (optional) — restrict to last N days
```

**Output schema:**
```json
{
  "memories": [
    {
      "id": "string",
      "content": "string",
      "created_at": "ISO 8601",
      "importance": 0.7,
      "tags": ["string"],
      "session_id": "string|null"
    }
  ]
}
```

**Backing module:** `src/memory_ts_client.py` → `list()` with sort by created_at.
**Gap:** None — this module exists and works.

---

#### `GET /memories/{id}`

**Purpose:** Get a single memory by ID, including its full history.

**Output schema:**
```json
{
  "id": "string",
  "content": "string",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",
  "session_id": "string|null",
  "importance": 0.7,
  "confidence": 0.5,
  "confirmations": 2,
  "contradictions": 0,
  "tags": ["string"],
  "archived": false,
  "versions": [
    {
      "version": 1,
      "content": "previous content",
      "changed_at": "ISO 8601",
      "reason": "updated"
    }
  ]
}
```

**Backing module:** `src/memory_ts_client.py` → `get()`, `src/memory_versioning.py` for version history.
**Gap:** `memory_versioning.py` exists (F23) — wire it here.

---

#### `PATCH /memories/{id}`

**Purpose:** Update a memory's content or metadata.

**Input schema:**
```json
{
  "content": "string (optional)",
  "tags": ["string"] "(optional)",
  "importance": "float (optional)",
  "intent": "string (optional)"
}
```

**Output schema:** Full memory object (same as `GET /memories/{id}`).

**Backing module:** `src/memory_ts_client.py` → `update()`.
**Gap:** None.

---

#### `DELETE /memories/{id}`

**Purpose:** Archive a memory (not hard delete).

**Output schema:**
```json
{
  "id": "string",
  "archived": true,
  "archived_at": "ISO 8601"
}
```

**Backing module:** Extended `MemoryTSClient.archive()` (Gap 7 / Spec 5).
**Gap:** Archive mechanism doesn't exist yet.

---

### Feedback and learning

---

#### `POST /memories/{id}/feedback`

**Purpose:** Record user feedback on a memory — confirmation ("yes, that's right"), contradiction ("no, that's wrong"), or irrelevant ("this wasn't useful"). Drives confidence scoring.

**Input schema:**
```json
{
  "type": "confirm|contradict|irrelevant|helpful|unhelpful",
  "note": "string (optional) — user's comment"
}
```

**Output schema:**
```json
{
  "id": "string",
  "confidence": 0.8,
  "confirmations": 3,
  "contradictions": 0,
  "feedback_recorded": true
}
```

**Backing module:** `src/confidence_scoring.py` → `update_confidence_on_confirmation()` / `update_confidence_on_contradiction()`. Needs persistence wiring (Gap 4).
**Gap:** Gap 4 (confidence persistence) must be implemented first.

---

#### `POST /memories/{id}/reinforce`

**Purpose:** Explicitly mark a memory as reinforced (spaced repetition trigger).

**Input schema:**
```json
{
  "grade": "FAIL|HARD|GOOD|EASY"
}
```

**Output schema:**
```json
{
  "id": "string",
  "next_review": "ISO 8601",
  "stability": 2.4,
  "difficulty": 0.3
}
```

**Backing module:** `src/fsrs_scheduler.py`, `src/intelligence/reinforcement_scheduler.py` (F27).
**Gap:** None — FSRS is implemented. Needs HTTP wiring only.

---

### Intelligence and analytics

---

#### `GET /health`

**Purpose:** System health check. Used by frontend to show the intelligence system's operational status.

**Output schema:**
```json
{
  "status": "ok|degraded|down",
  "memories": {
    "total": 2341,
    "active": 2280,
    "archived": 61,
    "avg_importance": 0.64
  },
  "db": "ok|error",
  "embedding_cache": {
    "status": "warm|cold|stale",
    "cached_count": 2280,
    "last_computed": "ISO 8601"
  },
  "circuit_breaker": {
    "state": "closed|open|half_open",
    "failures": 0
  },
  "last_maintenance": "ISO 8601",
  "last_daily_summary": "ISO 8601|null"
}
```

**Backing module:** `src/intelligence_db.py`, `src/db_pool.py`, `src/circuit_breaker.py` (Gap 6), `src/embedding_manager.py`.
**Gap:** Circuit breaker (Gap 6) not yet built.

---

#### `GET /stats`

**Purpose:** Rich intelligence statistics for the dashboard.

**Output schema:**
```json
{
  "memory_quality": {
    "grade_distribution": {"A": 120, "B": 340, "C": 89, "D": 12},
    "avg_grade": "B",
    "graded_count": 561
  },
  "learning_velocity": {
    "by_domain": {"client-work": 0.15, "dev": 0.05},
    "trend": "accelerating|steady|declining"
  },
  "sentiment": {
    "today": 7.2,
    "week_avg": 6.8,
    "trend": "up"
  },
  "confidence_distribution": {
    "very_high": 120, "high": 340, "medium": 890, "low": 210, "very_low": 45
  },
  "sessions": {
    "total": 779,
    "indexed_messages": 177000,
    "today": 3
  },
  "frustration": {
    "active_warning": false,
    "last_spike": "2026-02-12T15:30:00"
  }
}
```

**Backing module:** `src/intelligence_db.py`, `src/wild/sentiment_tracker.py` (F33), `src/wild/learning_velocity.py` (F34), `src/wild/quality_grader.py` (F62), `src/confidence_scoring.py`, `src/session_history_db.py`.
**Gap:** None — all modules exist. Aggregation query needed.

---

#### `GET /momentum`

**Purpose:** Current conversation momentum state — "on a roll" vs "stuck spinning." Powers momentum health card in frontend.

**Output schema:**
```json
{
  "state": "flowing|stuck|idle",
  "score": 0.73,
  "indicators": {
    "insights_per_hour": 4.2,
    "topic_cycling": false,
    "repeated_questions": 0,
    "decisions_made_today": 3
  },
  "suggestion": "string|null — intervention suggestion if stuck"
}
```

**Backing module:** `src/wild/momentum_tracker.py` (F52).
**Gap:** None — F52 exists. HTTP wiring only.

---

#### `GET /daily-summary`

**Purpose:** Get the daily episodic summary for a given date.

**Input schema (query params):**
```
date: YYYY-MM-DD (optional, default: today)
```

**Output schema:**
```json
{
  "date": "2026-02-14",
  "summary": "string — AI-generated summary",
  "session_count": 4,
  "generated_at": "ISO 8601",
  "available": true
}
```

**Backing module:** `src/daily_episodic_summary.py` (Gap 2 — doesn't exist yet).
**Gap:** Gap 2 (daily episodic summaries) must be built first.

---

### Event stream

---

#### `GET /events` (Server-Sent Events)

**Purpose:** Real-time stream of memory events for the frontend event cards feed. Emits events as they occur: new memories saved, contradictions detected, frustration warnings, maintenance completion, etc.

**Event types:**
```
memory_saved: { id, content, session_id, importance }
memory_archived: { id, reason }
contradiction_detected: { old_id, new_id, old_content, new_content }
frustration_warning: { level, trigger, suggestion }
maintenance_complete: { archived_count, decay_count, duration_ms }
daily_summary_ready: { date, summary_preview }
circuit_open: { failures, recovery_at }
circuit_closed: {}
```

**Output format:** Standard SSE (`text/event-stream`):
```
event: memory_saved
data: {"id": "mem_123", "content": "prefers dark mode", ...}

event: contradiction_detected
data: {"old_id": "mem_100", "new_id": "mem_123", ...}
```

**Backing module:** New `src/event_bus.py` — a simple in-memory pub/sub that modules can publish to. FastAPI SSE endpoint subscribes and streams.
**Gap:** Event bus doesn't exist. This is the highest-effort frontend endpoint but enables the most compelling UI (live event cards like ZeroBot).

---

### Version history and diffs

---

#### `GET /memories/{id}/versions`

**Purpose:** Get version history for a memory.

**Output schema:**
```json
{
  "id": "string",
  "versions": [
    {
      "version": 3,
      "content": "current content",
      "changed_at": "ISO 8601",
      "reason": "user_updated",
      "diff": "+ added phrase\n- removed phrase"
    }
  ]
}
```

**Backing module:** `src/memory_versioning.py` (F23), `src/intelligence/versioning.py`.
**Gap:** None — versioning is implemented. HTTP wiring + diff generation needed.

---

#### `POST /memories/{id}/rollback`

**Purpose:** Roll back a memory to a previous version.

**Input schema:**
```json
{
  "version": 2
}
```

**Output schema:** Full memory object after rollback.

**Backing module:** `src/memory_versioning.py` → rollback functionality.
**Gap:** None — if rollback is in `memory_versioning.py`. Verify before implementing.

---

## Implementation priority

| Priority | Endpoint | Backing gap | Effort |
|----------|----------|------------|--------|
| P0 | `GET /health` | Circuit breaker (partial gap) | S |
| P0 | `POST /memories` | Provenance gap | S |
| P0 | `GET /memories/search` | Hybrid search fix | M |
| P0 | `GET /memories/recent` | None | S |
| P1 | `GET /memories/{id}` | None | S |
| P1 | `POST /memories/{id}/feedback` | Confidence persistence | M |
| P1 | `GET /stats` | None | M |
| P1 | `GET /momentum` | None | S |
| P2 | `GET /daily-summary` | Daily episodic summary | M |
| P2 | `DELETE /memories/{id}` | Archive mechanism | M |
| P2 | `POST /memories/{id}/reinforce` | None | S |
| P3 | `GET /events` (SSE) | Event bus (new) | L |
| P3 | `GET /memories/{id}/versions` | None | M |
| P3 | `POST /memories/{id}/rollback` | None | S |

**Total:** ~8 P0/P1 endpoints could ship in a weekend. P3 (event stream) is the "ZeroBot moment" but requires the most new infrastructure.
