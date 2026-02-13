# Changelog

All notable changes to the Memory System v1 project.

---

## [Unreleased]

### Fixed
- **IntelligenceDB initialization bug** (src/intelligence_db.py:45) - Fixed AttributeError where `self.conn.row_factory` was accessed before `self.conn` was initialized. Now properly initializes connection from pool before setting row_factory.
- **PooledConnection attribute proxy** (src/db_pool.py) - Added `__setattr__` method to properly proxy attribute writes (like `row_factory`) to the underlying sqlite3.Connection object.
- **Test coverage improvement** - Fixed 12 intelligence_db tests that were failing due to initialization bug (0/12 → 12/12 passing)

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

## [2026-02-12] - Build Sprint

### Added
- 35 features shipped (F1-22 + F23, F33-35, F44-50, F55, F62-63)
- 5 features coded (F57, F61, F75 - awaiting tests)
- ~6,000 lines of production Python
- 358/369 tests passing (97%)
- intelligence.db: Shared database for features 23-75
- Session history DB: 779 sessions, 177K messages indexed

### Features Implemented
- F23: Memory Versioning
- F33-35: Wild features (Sentiment, Velocity, Personality Drift)
- F44-50: Multimodal + Meta-learning
- F55: Frustration Early Warning
- F62: Quality Auto-Grading
- F63: Prompt Evolution

---

## [Earlier] - Foundation

### Added
- F1-22: Core memory intelligence features
- memory-ts integration
- FSRS-6 spaced repetition
- Pattern detection and mining
- Cross-project memory sharing
- Session consolidation pipeline
