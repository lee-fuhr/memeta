# Changelog

All notable changes to Total Rekall.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [0.18.0] - 2026-02-18

### Added — Build sprint (5 features)
- **Provenance tracking** — `source_session_id` field traces every memory to its originating session. Conditionally written to YAML frontmatter (omitted when None), backward-compatible with legacy files.
- **Daily episodic summaries** — `src/daily_episodic_summary.py`: End-of-day summary generation from session history. `generate()` queries sessions, aggregates content (6000 char cap), calls Claude API. `load_recent()` for next-day context injection. LaunchAgent at 23:55.
- **Hybrid search unification** — `compute_idf()` with smoothed IDF formula replaces hardcoded 1.0. `normalize_scores()` scales BM25 to [0,1] before weighted combination. `embeddings` parameter for pre-computed vectors avoids per-doc model calls. Full backward compatibility.
- **Circuit breaker persistence** — SQLite persistence (WAL mode) so breaker state survives process restarts. Built-in `fallback` parameter on `call()`. `get_stats()` for dashboard. Thresholds adjusted to 5 failures / 600s recovery.
- **Memory decay archival** — Stale memories (importance < 0.2) moved to `archived/` directory during nightly maintenance. Manifest files document what was archived and why. `list(include_archived=True)` to include archived memories. DecayPredictor integration.

### Tests
- 10 new tests for provenance tracking
- 18 new tests for daily episodic summaries
- 27 new tests for hybrid search (IDF, normalization, embeddings, weights)
- 27 new tests for circuit breaker (persistence, fallback, stats, edge cases)
- Memory decay archival tests (count TBD)

### Status
- **Test suite:** 1,064+ passing (82+ new tests)
- **Features shipped:** 72

---

## [0.17.0] - 2026-02-17

### Added — Intelligence layer (tier 2 complete)
- **Cluster-based morning briefing** — `src/cluster_briefing.py`: `ClusterBriefing` class reads memory clusters from intelligence.db, generates `MorningBriefing` with top clusters, content previews, divergence signals. `/api/briefing` dashboard endpoint.
- **FAISS vector store** — `src/vector_store.py`: `VectorStore` class backed by FAISS `IndexFlatIP` (L2-normalized inner product = cosine similarity). Persistent save/load, batch operations, SQLite migration. Dual-write in `embedding_manager.py` (FAISS primary, SQLite fallback). Chose over ChromaDB due to Python 3.14 pydantic incompatibility.
- **Intelligence orchestrator** — `src/intelligence_orchestrator.py`: Central "brain stem" collecting signals from 5 sources (dream synthesis, momentum tracking, energy scheduling, regret detection, frustration events). Synthesizes into prioritized `DailyBriefing`. `/api/intelligence` dashboard endpoint.
- **Cross-client pattern synthesizer** — `src/cross_client_synthesizer.py`: Reads global-scope and consent-tagged memories, groups by knowledge domain, generates `TransferHypothesis` with confidence boosted by prior transfer effectiveness. `/api/cross-client` dashboard endpoint.
- **Decision regret loop** — `src/decision_regret_loop.py`: Real-time warning before repeating regretted decisions. Fuzzy keyword matching against historical `decision_outcomes` table, decision categorization, formatted warnings with regret rate and alternatives. `/api/regret-check` dashboard endpoint.
- **Embeddings migration script** — `scripts/migrate_embeddings_to_faiss.py`: One-time migration from SQLite embeddings to FAISS index.

### Tests
- 20 new tests in `tests/test_cluster_briefing.py`
- 24 new tests in `tests/test_vector_store.py`
- 20 new tests in `tests/test_intelligence_orchestrator.py`
- 25 new tests in `tests/test_cross_client_synthesizer.py`
- 24 new tests in `tests/test_decision_regret_loop.py`

### Status
- **Test suite:** 1,256 passing (113 new tests)
- **Features shipped:** 58 + 10 dashboard/infra improvements
- **Backlog tier 2:** Complete (items #6-#10 shipped)

---

## [0.16.0] - 2026-02-17

### Added — Dashboard UX + freshness review
- **"Explain why" on search results** — `_extract_snippet()` centers ~120-char window on match, `_match_reasons()` identifies body/tag/domain matches. Search cards show highlighted snippet + match reason tags.
- **Memory freshness indicators** — `days_stale` field on `/api/memories`, CSS opacity classes (stale-1/2/3), colored freshness pips (green/amber/yellow/rose), stale toggle filter
- **Memory freshness review cycle** — `src/memory_freshness_reviewer.py`: `scan_stale_memories()`, `refresh_memory()`, `archive_memory()`, interactive CLI review, Pushover notification summary, weekly LaunchAgent (Sundays 9am)
- **Session replay modal** — click session row to view transcript turns + linked memories. `/api/session/<id>` endpoint with `_summarise_transcript()`. Shows user/assistant turns with 300-char previews, session stats, memory chips
- **GitHub Actions CI** — `.github/workflows/test.yml`: pytest on push/PR, Python 3.11/3.12/3.13 matrix, pip caching, ignores tests/wild

### Tests
- 16 new tests in `tests/test_dashboard_search.py` (snippet extraction, match reasons)
- 18 new tests in `tests/test_memory_freshness_reviewer.py` (scan, refresh, archive, summary, _days_since)

### Status
- **Test suite:** 1,145 passing (34 new tests)
- **Features shipped:** 58 + 5 dashboard/infra improvements

---

## [0.15.0] - 2026-02-17

### Fixed — Consolidation hook broken since Feb 12
- **`dashboard_export.py` IndentationError** — entire `with` block body was at wrong indent level, causing import-time crash
- **Hook using system python instead of venv** — `python3` couldn't resolve `from memory_system.config import cfg`; changed to `~/.local/venvs/memory-system/bin/python3`
- **5 days of sessions had zero memories captured** — all consolidation attempts failed silently since Feb 12

### Added — Pushover notification on consolidation
- Hook now sends push notification via Pushover when new memories are saved or reinforcements detected
- Notification includes: memories saved, deduplicated, reinforcements, promotions, high-value count
- Gracefully fails — doesn't break the hook if Pushover is unavailable

### Status
- **Test suite:** 1,111 passing (pre-existing flaky tests unchanged)
- **Features shipped:** 58

---

## [0.14.0] - 2026-02-17

### Added — Circuit breaker + Total Recall rename
- **Circuit breaker for LLM calls (TDD)** — `src/circuit_breaker.py` with CLOSED/OPEN/HALF_OPEN states, 3-failure threshold, 60s recovery timeout, thread-safe via `threading.Lock`, singleton registry via `get_breaker(name)`
- **12 circuit breaker tests** — state machine (6), registry (3), edge cases (3)
- **Wired into 3 LLM call sites:** `llm_extractor.extract_with_llm()` → breaker "llm_extraction", `llm_extractor.ask_claude()` → breaker "llm_ask_claude", `contradiction_detector.ask_claude_quick()` → breaker "llm_contradiction"

### Changed — Rename to Total Recall + charter
- **Project renamed from Engram to Total Recall** across all files (dashboard, pyproject.toml, CONTRIBUTING, SECURITY, all tracking docs)
- **README rewritten** with project charter framing: every methodology, all additive, predict what's next
- **SHOWCASE updated** with charter statement, current stats (1,111 tests), and condensed progress log

### Status
- **Test suite:** 1,111 passing, 2 skipped (99.8%)
- **Features shipped:** 58

---

## [0.13.0] - 2026-02-16

### Added — Dashboard enhancements
- **Memory detail modal** — click any memory card to see full content, metadata, tags, and grade info in an overlay
- **`/api/memory/<id>` endpoint** — returns full body, all metadata for a single memory
- **Export (JSON + CSV)** — `/api/export?format=json|csv` endpoint + export buttons in Memories tab
- **LaunchAgent** — `com.lfi.total-recall-dashboard.plist` auto-starts dashboard on login with KeepAlive
- **Prioritized backlog** — `BACKLOG.md` with 23 items across 5 tiers (compiled from ideas.md, UX analysis, ROADMAP)

### Fixed
- Wordmark in dashboard: Mnemora → Total Recall
- YAML frontmatter parser: single-quoted arrays (`['tag1', 'tag2']`) now parsed as lists instead of strings (was causing character-by-character iteration in export/display)
- `.gitignore` — added BACKLOG.md to excluded working docs

---

## [0.12.0] - 2026-02-16

### Added — Total Recall dashboard
- **`dashboard/server.py`** — Flask server with JSON API endpoints (`/api/stats`, `/api/memories`, `/api/sessions`, `/api/refresh`)
- **`dashboard/index.html`** — full-stack UI with Obsidian + amber design (Fraunces + IBM Plex Mono/Sans)
  - Overview: stat cards, grade distribution bar, domain bars, 26-week activity heatmap
  - Memories: searchable/filterable cards with grade indicators, pagination
  - Sessions: table with date, name, message/tool/memory counts
  - Knowledge map: tag cloud (frequency-scaled) + domain breakdown
  - Sidebar with domain quick-filters

### Fixed
- Memories tab race condition — eliminated with concurrent load guard
- Error handling for API failures in frontend

---

## [0.11.0] - 2026-02-16

### Changed — Rename to Total Recall
- Project renamed from Mnemora to Total Recall throughout (commit c8a7545)
- README, dashboard, CHANGELOG, package metadata all updated

### Fixed
- **F30→F28 search delegation** — `MemoryAwareSearch.search()` now delegates to `SearchOptimizer.search_with_cache()` + `rank_results()` instead of bare client call
- **IntelligenceDB connection leak** — replaced `pool.get_connection()` with `sqlite3.connect()` directly (pool connections were borrowed at init and never returned)
- **Dream Mode O(n²)** — `MAX_MEMORIES = 1000` cap confirmed in place

---

## [0.10.0] - 2026-02-15

### Added — Config centralization
- **`src/config.py`** — `MemorySystemConfig` frozen dataclass, module singleton `cfg`. All paths and constants overridable via `MEMORY_SYSTEM_*` env vars.
- Centralized: `memory_dir`, `session_dir`, `project_id`, `session_db_path`, `shared_db_path`, `fsrs_db_path`, `intelligence_db_path`, `cluster_db_path`, `max_pre_compaction_facts`, `cache_ttl_seconds`

### Changed
- `session_history_db.py` — `SESSION_DB_PATH` now reads from `cfg`
- `shared_knowledge.py` — `SHARED_DB_PATH` now reads from `cfg`
- `session_consolidator.py` — hardcoded `~/.claude/projects` → `cfg.session_dir`
- `fsrs_scheduler.py` — relative `Path(__file__)` → `cfg.fsrs_db_path`
- `intelligence/search_optimizer.py` — relative `Path(__file__)` → `cfg.intelligence_db_path`

### Fixed
- `test_search_optimizer.py` — `sys.modules` mock patched wrong key (`memory_ts_client` → `memory_system.memory_ts_client`) after import migration

### Status
- **Test suite:** 1085 passing, 2 flaky (LLM timeout — pre-existing), 2 skipped (99.6%)

---

## [0.9.0] - 2026-02-15

### Changed — Package infrastructure + import cleanup
- **`pyproject.toml`** — package now installable via `pip install -e .`. Maps `memory_system` → `src/` via `[tool.setuptools.package-dir]`.
- **`conftest.py`** — minimal root conftest enables pytest discovery without sys.path tricks
- **Venv** — at `~/.local/venvs/memory-system/` (project is in Google Drive, can't create venv inside)
- **All imports standardized** — `from memory_system.X import ...` everywhere. Removed 71 sys.path hacks across tests, src, hooks, and scripts.

### Fixed
- Pre-existing ordering bug in `scripts/nightly_maintenance_master.py` — `SCRIPTS_DIR` used before definition

### Status
- **sys.path hacks remaining:** 2 (intentional — `decision_journal.py` optional ea_brain integration, `update_fsrs_manual.py` code generator)
- **Test suite:** 1085 passing (was 1086 before fix noted above)

---

## [0.8.1] - 2026-02-15

### Added — Critical infrastructure tests
- **db_pool.py** — 50 new tests (connection pooling, thread safety, context managers)
- **embedding_manager.py** — 62 new tests (storage, SHA-256 deduplication, batch ops)
- **semantic_search.py** — 72 new tests (vector similarity, ranking, filters)
- **hybrid_search.py** — 73 new tests (combined scoring, query parsing, project scoping)
- **session_history_db.py** — 65 new tests (transcript storage, search, stats)
- **Total added:** 322 tests

### Fixed
- 3 bugs in `session_history_db.py` found during test writing: docstring syntax error, indentation error, FTS5 bad column reference

### Status
- **Test suite:** 1086 passing, 2 skipped (was 765 before this release)

---

## [0.8.0] - 2026-02-13

### Changed
- **F63 (Prompt Evolution)** — discovered already built and shipped; updated all docs to correctly reflect 58 features
- SHOWCASE.md, HANDOFF.md, PLAN.md updated to v0.7.0 final state

### Status
- **Features shipped:** 58 | **Test suite:** 765 passing, 2 skipped

---

## [0.7.0] - 2026-02-13

### Fixed - Test Suite Cleanup
- **All failures resolved** - 8 failing tests → 0 failing (765 passing, 2 skipped)
- **F29 Smart Alerts test API mismatch** - Tests used `priority` parameter but implementation uses `severity`. Fixed `get_pending_alerts()` → `get_unread_alerts()`, `mark_delivered()` → `dismiss_alert()`.
- **F31 TopicSummary dataclass** - Tests omitted required fields `summary_id`, `created_at`, `memory_ids`.
- **F51 Temporal Predictor hook import contamination** - Fixed with `_load_hook_module()` helper that forces clean reload.

### Added - Test Coverage Expansion
- **F61 A/B Testing** - 4 → 14 tests (experiment lifecycle, variant assignment, statistical significance, auto-adoption, history)
- **F75 Dream Synthesis** - 4 → 16 tests (connection discovery, synthesis generation, queue priority, morning briefing)

### Status
- **Features shipped:** 57 | **Deferred:** 17 (F36-43, F66-74 integrations)
- **Test suite:** 765 passing, 0 failing, 2 skipped (99.7%)

---

## [0.6.0] - 2026-02-13

### Added - Wild Features Batch (F52-F65)
- **F52: Conversation Momentum Tracking** - Tracks momentum score 0-100 to detect "on a roll" vs "stuck" states. Calculates momentum from new insights (+20 each), decisions (+15 each), repeated questions (-10 each), topic cycles (-15 each). Provides state-specific intervention suggestions. 18 tests covering momentum calculation, state detection (on_roll/steady/stuck/spinning), interventions, statistics, and trend analysis.
- **F53: Energy-Aware Scheduling** - Learns energy patterns by hour/day and suggests optimal task timing. Tracks high/medium/low energy with confidence scores. Maps 6 default task types (deep_work, writing, meetings, code_review, admin, learning) to cognitive load. Suggests tasks matching current predicted energy level. 18 tests covering energy recording, pattern learning, prediction, task suggestion, and confidence building.
- **F54: Context Pre-Loading (Dream Mode v2)** - Pre-loads context before work sessions. Schedule preloads by time + context_type (client_meeting, coding_session, writing). Queue system with pending/loaded/expired states. Retrieves preloaded memories by type and optional target. Auto-cleanup of old tasks. 11 tests covering scheduling, pending detection, mark loaded/expired, retrieval, cleanup, and statistics.
- **F56: Client Pattern Transfer** - Identifies and transfers patterns across projects. Records pattern transfers with effectiveness ratings. Finds transferable patterns based on successful transfers (rating >= 0.7). Tracks transfer history per project. Privacy-aware cross-project learning. 11 tests covering pattern transfer, rating, history, successful transfers, and pattern discovery.
- **F58: Decision Regret Detection** - Tracks decisions and warns before repeating regretted choices. Records decision content, alternatives, and outcomes (good/bad/neutral). Detects regret patterns (50%+ regret rate, min 2 occurrences). Generates warnings with regret statistics. Supports decision history and regret-only filtering. 14 tests covering decision recording, regret marking, pattern detection, warnings, history, and statistics.
- **F59: Expertise Mapping** - Maps agent expertise by domain for optimal routing. Records memory_count × avg_quality scores per agent/domain. Updates existing expertise with weighted averages. Routes to best expert by score. Returns full expertise map and per-agent breakdowns. 11 tests covering expertise recording, updates, expert lookup, mapping, per-agent queries, and statistics.
- **F60: Context Decay Prediction** - Predicts staleness before it happens. Records predicted_stale_at with confidence by reason (project_inactive 0.7, superseded 0.9, outdated_source 0.8). Surfaces memories becoming stale within N days. Tracks refresh/review status. Provides statistics by reason. 11 tests covering prediction, updates, stale detection, refresh tracking, and statistics.
- **F64: Learning Intervention System** - Detects repeated questions and suggests learning resources. Tracks question occurrence counts. Detects high-frequency questions (3+ occurrences). Generates tutorials and reference docs (template-based MVP). Marks intervention effectiveness. 12 tests covering question recording, increment logic, detection, tutorial/reference generation, intervention saving, effectiveness tracking, and statistics.
- **F65: Mistake Compounding Detector** - Tracks mistake cascades to prevent compound errors. Records root_mistake_id → downstream_error_ids chains. Detects cascades by root or downstream error. Analyzes root causes. Generates prevention strategies by cascade depth. Provides cascade statistics and depth distribution. 13 tests covering cascade recording, detection (by root/downstream), root cause analysis, prevention suggestions, filtering, and statistics.

### Test Coverage
- **Total tests:** 735 passing, 2 skipped, 8 failing (98.9% pass rate)
- **New tests this release:** 109 tests across 9 wild features (F52-F65)
- **Wild features implemented:** F52, F53, F54, F56, F58, F59, F60, F64, F65 (9 features, 109 tests)

---

## [0.5.0] - 2026-02-13

### Added
- **F29: Smart Alerts** - Proactive notification system for memory events with 5 alert types (expiring_memory, contradiction, pattern_detected, stale_memory, quality_issue) and 4 severity levels (low, medium, high, critical). Features daily digest generation, alert dismissal/action tracking, statistics, and automatic cleanup of old dismissed alerts. 16 comprehensive tests covering initialization, alert creation, filtering, dismissal, action tracking, daily digest, statistics, and cleanup.
- **F30: Memory-Aware Search** - Multi-dimensional search with semantic content matching, temporal filtering (absolute and relative dates), project/tag filtering, and natural language query parsing. Extracts temporal references (last week, yesterday, January), importance indicators, project mentions, and tags from queries. Includes search history tracking and relevance scoring with three ordering modes (importance, recency, relevance). 16 tests covering initialization, content search, natural language parsing (temporal, importance, project, tags), history tracking, and relevance calculation.
- **F31: Auto-Summarization** - LLM-powered topic summarization with narrative generation, timeline building, key insights extraction, and database persistence. Generates 2-3 paragraph summaries via Sonnet 4.5 with fallback to structured summaries on timeout. Supports topic-based summarization, summary retrieval/filtering, and regeneration from saved memory IDs. 14 tests covering initialization, empty/populated summarization, timeline generation, database persistence, retrieval, filtering, regeneration, and metadata tracking.
- **F32: Quality Scoring** - Automated quality assessment for memories checking 5 dimensions: length (min 10, optimal 30-200, max 500 chars), vague language detection (12 vague word triggers), actionability (verb presence), sentence completion, and capitalization. Provides scored assessments (0.0-1.0) with specific issues and improvement suggestions. Supports batch assessment and low-quality filtering with custom thresholds. 13 tests covering high-quality detection, length checks, vague language, verbs, sentence structure, capitalization, batch processing, filtering, and suggestion provision.

---

## [0.4.0] - 2026-02-13

### Added
- **F26: Memory Summarization** - LLM-powered summarization of memories with three types: cluster summaries (theme + key points), project summaries (30-day progress reports), and period summaries (weekly/monthly digests). Generates 2-3 paragraph summaries via Sonnet 4.5 with fallback to generic summaries on timeout. 17 comprehensive tests covering initialization, cluster/project/period summarization, filtering, regeneration, statistics, and LLM fallback.

---

## [0.3.1] - 2026-02-13

### Fixed
- **F28 cache bug (CRITICAL)** - Fixed cache hit hydration that was still calling `search_fn()` on cache hit, making cache non-functional. Cache now properly hydrates Memory objects from cached IDs using MemoryTSClient.get() with FileNotFoundError handling for deleted memories.
- **F28 cache key mismatch** - Fixed `invalidate_cache()` to use same composite key format as storage: `{query}|{project_id or 'global'}` instead of just query hash.
- **F28 test coverage** - Updated `test_cache_hit_second_search()` to verify search_fn NOT called on cache hit. Fixed `test_cache_invalidation()` to use correct composite key format. Added `test_cache_efficiency()` to verify cache prevents redundant search calls across 10 consecutive hits.

---

## [0.3.0] - 2026-02-13

### Added
- **F24: Memory Relationship Mapping** - Graph-based relationship system with 5 types (causal, contradicts, supports, requires, related), BFS causal chain discovery, bidirectional queries, contradiction detection, and global/per-memory statistics. 28 comprehensive tests covering initialization, link creation, retrieval, causal chains, contradictions, updates/deletions, and statistics.
- **F27: Memory Reinforcement Scheduler** - FSRS-6 based review scheduling with due review surfacing, review history tracking, and automatic rescheduling. Progressive interval doubling for non-FSRS memories. 24 tests covering initialization, scheduling, due reviews, recording, rescheduling, statistics, and FSRS integration.
- **F28: Memory Search Optimization** - Query result caching with 24h TTL and project-scoped cache keys. Improved ranking algorithm: semantic (0.5) + keyword (0.2) + recency (0.2) + importance (0.1) with clamped recency scores. Search analytics tracking for future CTR learning. 14 tests covering initialization, caching (miss/hit/expiry/invalidation), ranking, selection recording, and analytics.
- **F51: Temporal Pattern Prediction** - Learns temporal patterns from memory access behavior and predicts needs proactively. Passive learning logs every memory access (time/day/context). Pattern detection identifies daily/weekly/monthly patterns (min 3 occurrences). Feedback loop (confirm/dismiss) adjusts confidence. Topic resumption detector hook auto-surfaces memories when user references past discussions. 25 tests covering access logging, pattern detection, prediction, feedback loop, hook integration, and MemoryTSClient instrumentation.
- **Test files for F61 and F75** - Created `tests/wild/test_ab_tester.py` (4 tests) and `tests/wild/test_dream_synthesizer.py` (4 tests) for basic module initialization and data structure validation
- **Progressive timeout increases in ask_claude** - LLM retry logic now increases timeout on each attempt: initial → +10s → +20s (e.g., 30s → 40s → 50s). Gives Claude more time on retries.
- **Planning documentation** - Created comprehensive implementation plans for F24 (relationship mapping), F27 (reinforcement scheduler), F28 (search optimization), plus feature specs for F24-32 (intelligence enhancement), F36-43 (integrations - deferred), and F51-75 (wild features with tier prioritization).

### Fixed
- **IntelligenceDB initialization bug** (src/intelligence_db.py:45) - Fixed AttributeError where `self.conn.row_factory` was accessed before `self.conn` was initialized. Now properly initializes connection from pool before setting row_factory.
- **PooledConnection attribute proxy** (src/db_pool.py) - Added `__setattr__` method to properly proxy attribute writes (like `row_factory`) to the underlying sqlite3.Connection object.
- **MemoryTSClient API mismatch** (src/session_consolidator.py:564) - Fixed incorrect `search()` call using non-existent `query=` and `limit=` parameters. Now correctly uses `content=` parameter as defined in MemoryTSClient API.
- **Deduplication LLM timeout** (src/session_consolidator.py:421) - Fixed timeout in `_smart_dedup_decision` by increasing from 10s to 30s, reducing retries from 3 to 2, and adding fallback to similarity-based decision (>0.75 = duplicate) when LLM times out.
- **SQL WHERE clause precedence** (src/intelligence/relationship_mapper.py) - Fixed operator precedence issue when combining OR and AND conditions by wrapping OR conditions in parentheses: `(from_memory_id = ? OR to_memory_id = ?) AND relationship_type = ?`
- **Test coverage improvement** - Fixed 12 intelligence_db tests (0/12 → 12/12), 12 session_consolidator tests (14/26 → 26/26), added 8 new wild feature tests, and added 28 relationship mapping tests

### Changed
- Repository cleanup: Archived obsolete documentation (PHASE-*.md, old QA passes, _working/) to _archive/
- **SHOWCASE.md rewrite** - Restructured using VBF framework (Values → Benefits → Features). Leads with problem/pain, shows how world improves, grounds all features in benefits.

---

## [0.2.0] - 2026-02-12

### Added
- embedding_manager.py: Persistent embedding storage with SHA-256 content hashing
- async_consolidation.py: Queue-based async consolidation system
- nightly_maintenance_master.py: Orchestrates all nightly jobs
- scripts/consolidation_worker.py: Background worker for async processing
- scripts/nightly_embedding_precompute.py: Pre-computes embeddings nightly
- hooks/session-memory-consolidation-async.py: Fast SessionEnd hook (<1s)
- PERFORMANCE-ANALYSIS.md: Comprehensive scaling analysis by Performance Architect
- RELIABILITY-ANALYSIS.md: Failure modes and recovery by Reliability Engineer
- UX-ANALYSIS.md: Usability assessment by UX Reviewer
- tests/wild/test_writing_analyzer.py: 18 tests for F57 Writing Style Analyzer

### Changed
- Semantic search now uses pre-computed embeddings from intelligence.db (500s → <1s)
- Session consolidation moved to async queue (60-120s hook → <1s)
- Database optimization (VACUUM + ANALYZE) now runs nightly
- SQLite backups automated with 7-day retention

### Fixed
- Semantic search O(n) embedding bottleneck
- SessionEnd hook timeout risk from blocking consolidation
- Unbounded in-memory embedding cache (memory leak)

### Performance Impact
- Semantic search: 500s → <1s per search at 10K memories
- Hook execution: 60-120s → <1s (queue only)
- API costs at 10K scale: $1,000/day → $4/day (with optimizations)

---

## [0.1.0] - 2026-02-12

### Added
- 35 features shipped (F1-22 + F23, F33-35, F44-50, F55, F62-63)
- 5 features coded (F57, F61, F75 - awaiting tests)
- ~6,000 lines of production Python
- 358/369 tests passing (97%)
- intelligence.db: Shared database for features 23-75
- Session history DB: 779 sessions, 177K messages indexed

### Features Implemented
- F1-22: Core memory intelligence features
- F23: Memory Versioning
- F33-35: Wild features (Sentiment, Velocity, Personality Drift)
- F44-50: Multimodal + Meta-learning
- F55: Frustration Early Warning
- F62: Quality Auto-Grading
- F63: Prompt Evolution

### Infrastructure
- memory-ts integration
- FSRS-6 spaced repetition
- Pattern detection and mining
- Cross-project memory sharing
- Session consolidation pipeline
