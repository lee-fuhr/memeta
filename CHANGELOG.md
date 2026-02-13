# Changelog

All notable changes to the Memory System v1 project.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

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
