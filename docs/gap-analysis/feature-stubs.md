# Feature stubs — gap analysis

**Created:** 2026-02-14
**Purpose:** Gaps identified by comparing Lee's 58-feature memory-system-v1 against Ben's ZeroBot (11 layers, 10 mechanisms, Google A-grade).

---

## Gap 1: Provenance not wired to session IDs

**Problem:** `confidence_scoring.py` and `memory_ts_client.py` exist but memories are not tagged with the session/conversation ID that produced them. The SHOWCASE.md claims "Provenance tracking — every memory tagged with session ID" but a grep across `src/` finds `conversation_id` only in `session_consolidator.py` and `voice_capture.py` — not in the core save path. "When did I say that?" queries can't be answered precisely.

**Proposed solution:** Add `source_session_id: Optional[str]` field to memory-ts YAML frontmatter. Modify `MemoryTSClient.add()` to accept and write that field. Update `session_consolidator.py` to pass the session ID on every save. Expose a `recall_provenance(memory_id)` method that returns the session ID + a `claude --resume <id>` link.

**Acceptance criteria:**
1. Every memory written after the change includes `source_session_id` in its YAML frontmatter.
2. `recall_provenance("mem_abc")` returns `{"session_id": "...", "resume_link": "claude --resume ..."}` or `None` for legacy memories.
3. Existing memories without the field continue to load correctly (backward-compatible).

**Estimated effort:** S (< 1hr)

**Dependencies:** None. `memory_ts_client.py` and `session_consolidator.py` already exist.

---

## Gap 2: Daily episodic summary cron is absent

**Problem:** SHOWCASE.md shows a daily summary in the "Morning (Wake up to insights)" example. ZeroBot generates `memory/YYYY-MM-DD.md` via a cron at 11:55 PM. Lee's system has `daily_memory_maintenance.py` (decay/archival) and `weekly_synthesis.py` but neither generates a human-readable daily episodic summary file. There is no cron for end-of-day summarization. The episodic layer is thin — only conversation compaction summaries exist.

**Proposed solution:** Add `daily_episodic_summary.py` in `src/`. On execution: query `session_history_db.py` for all sessions from today, feed the combined transcript (capped at 6000 chars) to Claude API, write output to `~/memory/YYYY-MM-DD.md`. Register a LaunchAgent plist that runs at 23:55 daily. Inject today + yesterday summaries into MEMORY.md context at session start via `session_consolidator.py`.

**Acceptance criteria:**
1. Running `python -m src.daily_episodic_summary` produces a `~/memory/YYYY-MM-DD.md` file with a non-empty AI-generated summary.
2. LaunchAgent plist exists at `launch-agents/com.memory.daily-summary.plist` and passes `launchctl load` without error.
3. Summary is injected into the next session's context (verified via `session_consolidator.py` dry-run output).

**Estimated effort:** M (1–4hr)

**Dependencies:** `session_history_db.py`, Claude API key in 1Password. LaunchAgent infrastructure already exists (other plists present).

---

## Gap 3: Hybrid search scoring is incomplete (IDF = 1.0 hardcoded)

**Problem:** `hybrid_search.py` claims 70/30 semantic+BM25 weighting but the BM25 implementation uses `idf = 1.0` (line 64), ignoring corpus frequency. This means common terms (like "the", "memory") score the same as rare, meaningful terms. The hybrid score is biased toward raw term frequency and produces inflated scores for common words. The semantic side has a different problem: it calls `semantic_search()` per-document in a loop (O(n) model calls), making hybrid search O(n × embedding_time) — unusable at scale.

**Proposed solution:** (1) Compute a proper IDF from the corpus before scoring: `idf = log((N + 1) / (df + 1)) + 1`. (2) Pre-embed all memories once using `embedding_manager.py`'s pre-computation capability before running hybrid search — pass embeddings in as a parameter rather than computing per-document. (3) Add `normalize_scores()` to bring semantic and BM25 scores to the same [0, 1] range before weighting.

**Acceptance criteria:**
1. `bm25_score()` with a stopword query ("the the the") scores lower than a meaningful query ("morning standup preference") on the same document.
2. `hybrid_search(query, memories, embeddings=precomputed)` runs in < 200ms for 1000 memories (no per-doc model calls).
3. Existing tests pass without modification.

**Estimated effort:** M (1–4hr)

**Dependencies:** `embedding_manager.py` (exists), `semantic_search.py` (exists).

---

## Gap 4: Confidence scores are computed but never persisted

**Problem:** `confidence_scoring.py` has solid math — `calculate_confidence()`, `update_confidence_on_confirmation()`, `update_confidence_on_contradiction()` — but these functions operate on dict inputs and return floats. There is no mechanism that writes updated confidence back to the memory file or to `intelligence.db`. Every session starts with `confidence_score = 0.5` for all memories because nothing increments `confirmations` or `contradictions` at runtime.

**Proposed solution:** Add `confidence_score`, `confirmations`, and `contradictions` fields to memory-ts YAML frontmatter. When `contradiction_detector.py` fires and resolves a conflict, increment `contradictions` on the superseded memory before archiving it. When a memory is retrieved and reinforced (user says "yes, that's right"), increment `confirmations`. Expose a `memory-ts confidence-summary` report showing distribution across memories.

**Acceptance criteria:**
1. After a contradiction is detected, the superseded memory's YAML includes `contradictions: 1`.
2. After a reinforcement event, the target memory's YAML shows `confirmations` incremented.
3. `get_confidence_stats(client.list())` returns non-default values after 5 simulated events.

**Estimated effort:** M (1–4hr)

**Dependencies:** `contradiction_detector.py`, `correction_promoter.py`, `memory_ts_client.py`.

---

## Gap 5: Cross-project sharing is a stub (no persistence layer)

**Problem:** `cross_project_sharing.py` is 29 lines of pure in-memory functions. It has no DB persistence, no actual propagation mechanism, and no privacy controls. The `suggest_cross_project()` function returns all projects for universal memories with a comment "would use LLM to determine relevance — for now, return all projects." This is a placeholder, not a feature.

**Proposed solution:** Add a `shared_insights` table to `intelligence.db` (schema: id, source_project, target_project, memory_content, relevance_score, created_at, status). Wire `cross_project_sharing.py` to write to this table. Add a `share_insight()` function that calls Claude API to estimate relevance before writing. Expose a `get_shared_insights(project_id)` query in `intelligence_db.py`. Add basic privacy controls: opt-in per project (flag in project config).

**Acceptance criteria:**
1. `share_to_project(memory, "ZeroArc")` writes a row to the `shared_insights` table with `relevance_score > 0`.
2. `get_shared_insights("ZeroArc")` returns the shared row.
3. A project flagged `share_enabled: false` receives no shared insights.

**Estimated effort:** M (1–4hr)

**Dependencies:** `intelligence_db.py`, Claude API.

---

## Gap 6: No circuit breaker on LLM calls

**Problem:** PLAN.md explicitly lists "No circuit breaker for LLM failures" as a known issue. Multiple modules (contradiction_detector, llm_extractor, session_consolidator, daily_memory_maintenance) make Claude API calls. If the API is down or rate-limited, every module fails independently with no shared state tracking. This means a 30-minute API outage could trigger 50+ retry loops across different modules simultaneously, amplifying rate-limit problems.

**Proposed solution:** Add `src/circuit_breaker.py` implementing the standard 3-state pattern (closed → open → half-open). Track failure count in a shared `intelligence.db` table (`circuit_breaker_state`). After 5 consecutive failures, open the circuit for 10 minutes. During open state, LLM-dependent modules fall back to their non-LLM paths gracefully (e.g., `contradiction_detector` skips LLM check, `llm_extractor` skips extraction). Wrap all Claude API call sites with `circuit_breaker.call(fn, fallback=...)`.

**Acceptance criteria:**
1. After 5 simulated API failures, circuit state transitions to `open` and all subsequent calls return fallback immediately (no API calls made).
2. After 10 minutes, circuit transitions to `half-open`, tries one call, closes on success.
3. `get_circuit_state()` returns `{"state": "open", "failures": 5, "opens_at": ..., "resets_at": ...}`.

**Estimated effort:** M (1–4hr)

**Dependencies:** `intelligence_db.py`. All LLM call sites need wrapping.

---

## Gap 7: Memory decay is a prediction stub, not an archival action

**Problem:** `wild/decay_predictor.py` (F60) predicts when memories will become stale and stores predictions in `decay_predictions` table. But it doesn't act on those predictions. `daily_memory_maintenance.py` applies mathematical decay (0.99^days) to importance scores but doesn't archive memories once they fall below threshold — it just decrements values. Nothing actually moves stale memories out of the active corpus. Memories from 2 years ago sit alongside yesterday's insights with no differentiation.

**Proposed solution:** In `daily_memory_maintenance.py`, after applying decay, query memories where `importance < 0.2` OR where `decay_predictions.predicted_stale_at < now()` and `reviewed_at IS NULL`. Move those memories to an `archived/` subdirectory (not delete). Write a `~/memory/archived/YYYY-MM-DD-archive.md` manifest. Expose a `memory-ts archived list` command. Add a "review before archive" option for high-tag memories.

**Acceptance criteria:**
1. Memories with `importance < 0.2` are moved to `archived/` after maintenance run.
2. Archived memories are not returned by `client.list()` unless `include_archived=True`.
3. Archive manifest exists at `~/memory/archived/YYYY-MM-DD-archive.md` after each run.

**Estimated effort:** M (1–4hr)

**Dependencies:** `daily_memory_maintenance.py`, `decay_predictor.py`, `memory_ts_client.py`.

---

## Gap 8: Semantic search embeddings are not pre-computed by default

**Problem:** PLAN.md lists "5 critical infrastructure modules untested: db_pool, embedding_manager, semantic_search, hybrid_search, session_history_db." `embedding_manager.py` exists and is designed for pre-computation but semantic search still falls back to on-demand embedding generation. Without pre-computed embeddings, `semantic_search()` is called per-query with model load time (~90MB, ~2s cold start). At the scale Lee's system runs (2,300+ memories), this makes semantic search impractical in real-time use.

**Proposed solution:** Add a startup check in `session_consolidator.py` that calls `embedding_manager.pre_compute_all()` if the cache is stale (older than 24h or after any new memory write). Pre-compute on nightly maintenance cycle (add to `nightly_maintenance_master.py`). Store embeddings in `intelligence.db` in the `memory_embeddings` table (or in the existing pre-computation cache). The startup check should be async and non-blocking.

**Acceptance criteria:**
1. After `nightly_maintenance_master.py` runs, embeddings exist for all memories in the cache.
2. `semantic_search(query, memories)` with pre-computed embeddings completes in < 100ms for 500 memories.
3. Cold start (no pre-computed embeddings) still works via fallback to on-demand embedding.

**Estimated effort:** M (1–4hr)

**Dependencies:** `embedding_manager.py`, `nightly_maintenance_master.py`.

---

## Gap 9: No unified API entry point (orchestration gap)

**Problem:** Design review flagged "no unified entry point" as organizational debt. With 58 features and 85+ Python modules, there is no single `MemorySystem` class or CLI entry point that orchestrates the pipeline. Callers must know which of `session_consolidator.py`, `llm_extractor.py`, `contradiction_detector.py`, `hybrid_search.py`, etc. to call and in what order. This makes integration brittle and makes it impossible to power a frontend or REST API without substantial wrapper work.

**Proposed solution:** Add `src/memory_system.py` with a `MemorySystem` class exposing: `save(content, session_id)`, `search(query, top_k)`, `get_recent(n)`, `get_stats()`, `run_maintenance()`. This class orchestrates the existing modules — it does not reimplement them. Add a CLI entry point `scripts/memory.py` using argparse that wraps the same methods for shell access.

**Acceptance criteria:**
1. `MemorySystem().save("prefers dark mode", session_id="abc")` runs contradiction detection, saves with provenance, returns the saved memory ID.
2. `MemorySystem().search("dark mode preferences")` returns ranked results using hybrid search.
3. `python scripts/memory.py search "dark mode"` works from the shell and returns the same results.

**Estimated effort:** M (1–4hr)

**Dependencies:** All major modules. No new logic, coordination only.

---

## Gap 10: intelligence.db connection leak (known issue, not fixed)

**Problem:** PLAN.md explicitly lists "IntelligenceDB connection leak (get/return per operation needed)" as a known architectural issue. `IntelligenceDB` stores `self.conn` as an instance attribute but the class is used across many modules. When multiple modules create `IntelligenceDB()` instances in the same process (which happens during overnight automation), connections accumulate and are never returned. SQLite has a limit on open file descriptors. This is a time-bomb — the system fails silently after enough automation runs.

**Proposed solution:** Migrate `IntelligenceDB` to use `db_pool.get_connection()` (already exists in `db_pool.py`). Replace `self.conn = sqlite3.connect(...)` with `self._db_path = db_path` and use `with get_connection(self._db_path) as conn:` in each method. This is a refactor of how connections are acquired, not a logic change.

**Acceptance criteria:**
1. `IntelligenceDB` no longer holds a persistent `self.conn` attribute after refactor.
2. Running 100 sequential `IntelligenceDB()` operations in a test does not increase open file descriptor count.
3. All existing `IntelligenceDB` tests pass without modification.

**Estimated effort:** S (< 1hr)

**Dependencies:** `db_pool.py` (exists and tested), `intelligence_db.py`.

---

## Gap 11: sys.path hacks in 20+ files (fragile imports)

**Problem:** PLAN.md lists "sys.path hacks in 20+ files" as a known architectural issue. Every file that does cross-module imports has something like `sys.path.insert(0, str(Path(__file__).parent.parent))`. This is fragile, breaks IDEs, makes relative imports unreliable, and causes import contamination in tests (already manifested as 8 pre-existing test failures that required manual fixes).

**Proposed solution:** Convert the project to a proper Python package. Add `pyproject.toml` (or `setup.py`) that declares `memory_system` as an installable package. Install with `pip install -e .` in the venv. All imports become `from memory_system.src.hybrid_search import hybrid_search`. Remove all `sys.path` hacks. Run tests to verify imports work cleanly.

**Acceptance criteria:**
1. No `sys.path.insert` or `sys.path.append` anywhere in `src/` after refactor.
2. `pytest tests/` passes with 0 import errors (baseline: 765/767 passing).
3. `from memory_system.src.db_pool import get_connection` works in a fresh Python shell without path manipulation.

**Estimated effort:** S (< 1hr to set up package; M if many import paths need updating)

**Dependencies:** None. Self-contained cleanup.

---

## Gap 12: No time-based or event-based compaction triggers

**Problem:** ZeroBot implements 3 compaction strategies per Google's recommendation: count-based (>50 messages), time-based (inactivity timeout), and event-based (task completion detection). Lee's system only has count-based compaction. This means a session that goes dormant without hitting 50 messages never compacts, and a session that explicitly ends ("that's all for today") doesn't trigger a flush of durable facts.

**Proposed solution:** Add two trigger modes to `conversation_compactor.py`: (1) Time-based: expose a `check_inactivity_timeout(session_id, timeout_minutes=60)` method that flushes and compacts if the last message timestamp is > timeout; wire to the hourly cron. (2) Event-based: in `event_detector.py` (which already exists), add detection patterns for session-end signals ("that's all", "done for today", "signing off") and emit a `COMPACT_TRIGGER` event that `conversation_compactor.py` handles.

**Acceptance criteria:**
1. Session inactive for 60+ minutes triggers pre-compaction flush (verified via test with mocked timestamps).
2. Message "that's all for today" triggers `COMPACT_TRIGGER` event from `event_detector.py`.
3. Both triggers result in the same outcome as count-based compaction (durable facts saved, old messages summarized).

**Estimated effort:** M (1–4hr)

**Dependencies:** `conversation_compactor.py`, `event_detector.py`, `pre_compaction_flush.py`.

---

## Gap 13: No REST API or webhook surface for frontend integration

**Problem:** All 58 features are Python modules with no HTTP interface. Powering a ZeroBot-style frontend (memory event cards, feedback buttons, search, momentum health state) requires a server. There is no FastAPI/Flask app, no webhook endpoint for Claude Code hooks to POST events to, and no SSE stream for real-time updates. The dashboard at `localhost:8766` exists but its API surface is undocumented.

**Proposed solution:** Add `src/api/server.py` using FastAPI. Expose the core endpoints documented in `ui-api-surface.md`. Start with 5 essential endpoints: `POST /memories`, `GET /memories/search`, `GET /memories/recent`, `POST /memories/{id}/feedback`, `GET /health`. Add a `scripts/start_api.py` and LaunchAgent plist. Document the API surface in `docs/api.md`.

**Acceptance criteria:**
1. `uvicorn src.api.server:app --port 8767` starts without error.
2. `curl http://localhost:8767/health` returns `{"status": "ok", "memories": N, "db": "ok"}`.
3. `POST /memories` with `{"content": "test", "session_id": "abc"}` saves a memory and returns its ID.

**Estimated effort:** L (4+hr)

**Dependencies:** Gap 9 (unified `MemorySystem` class) should exist first. FastAPI dependency.

---
