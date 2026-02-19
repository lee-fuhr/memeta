# Features

Every feature in Total Rekall, organized by layer. Each one coexists additively — adding feature N+1 makes features 1 through N better.

**Current:** v0.19.1 · 2,035 tests passing · 101 features shipped

---

## Foundation — the basics done right

| Feature | What it does | File |
|---------|-------------|------|
| Session consolidation | Extracts memories from session transcripts with deduplication | `src/session_consolidator.py` |
| Importance scoring | 0.0–1.0 scores with decay, reinforcement boost, trigger weighting | `src/importance_engine.py` |
| Pattern detection | Identifies repeated themes and behavioral patterns across sessions | `src/pattern_detector.py` |
| Contradiction detection | Spots conflicting memories via LLM analysis | `src/contradiction_detector.py` |
| Daily maintenance | Nightly VACUUM, ANALYZE, backups with 7-day retention | `src/daily_memory_maintenance.py` |
| File-based storage | Markdown files with YAML frontmatter — readable, portable, yours | `src/memory_ts_client.py` |
| Provenance tracking | Every memory traces back to its source session via `source_session_id` | `src/memory_ts_client.py` |
| Decision journal | Records decisions, rationale, outcomes for future reference | `src/decision_journal.py` |
| Session history | Tracks every session: message counts, tool usage, memory links | `src/session_history_db.py` |
| Importance auto-tuning | Learns what makes a good memory by watching which ones actually help | `src/importance_auto_tuning.py` |
| Memory versioning | Full edit history per memory with diff and rollback | `src/memory_versioning.py` |
| Project scoping | Maps sessions to projects, scopes memories to prevent leakage | `src/project_resolver.py` |
| LLM extraction | Claude API calls for smart extraction, protected by circuit breaker | `src/llm_extractor.py` |
| FSRS-6 spaced repetition | Science-backed retention scheduling: stability, difficulty, intervals | `src/fsrs_scheduler.py` |
| Confidence scoring | Estimates reliability of extracted memories | `src/confidence_scoring.py` |
| Correction promotion | Corrections automatically promote to higher importance | `src/correction_promoter.py` |
| Event detection | Identifies significant events in the memory stream | `src/event_detector.py` |
| Pattern mining | Extracts patterns from the memory relationship graph | `src/pattern_miner.py` |
| Confidence persistence | Persists confidence scores across sessions with SQLite backing | `src/confidence_persistence.py` |
| Directed forgetting | Detects "scratch that"/"remember this" intent markers, adjusts importance | `src/directed_forgetting.py` |
| Encoding depth scoring | Rates memory depth 1-3 (shallow/intermediate/deep) via Craik & Lockhart heuristics | `src/encoding_depth.py` |
| Entity extraction | Extracts and links persons, tools, projects from memory text | `src/entity_extractor.py` |
| Emotional tagging | Detects valence/arousal from session context for flashbulb memory prioritization | `src/emotional_tagging.py` |

---

## Intelligence — the compounding layer

| Feature | What it does | File |
|---------|-------------|------|
| Semantic clustering | K-means grouping with LLM-generated topic labels | `src/intelligence/clustering.py` |
| Relationship mapping | Explicit graph: causal, contradicts, references, supports | `src/intelligence/relationship_mapper.py` |
| Memory graph | Query support for relationship chains and paths | `src/intelligence/relationships.py` |
| Summarization | Cluster, project, period, and topic summaries via LLM | `src/intelligence/summarization.py` |
| Reinforcement scheduling | Review scheduling based on FSRS reinforcement data | `src/intelligence/reinforcement_scheduler.py` |
| Cache-aware search | 24h TTL cache + multi-factor ranking (semantic × 0.5 + keyword × 0.2 + recency × 0.2 + importance × 0.1) | `src/intelligence/search_optimizer.py` |
| Smart alerts | Proactive notifications for expiring memories, patterns, contradictions | `src/automation/alerts.py` |
| Hybrid search | 70% semantic + 30% BM25 with corpus IDF, score normalization, pre-computed embeddings | `src/hybrid_search.py` |
| Natural language queries | Ask questions in plain English, get ranked results | `src/automation/search.py` |
| Quality scoring | Auto-detects low-quality memories (vague, duplicate, unclear) | `src/automation/quality.py` |
| Sentiment tracking | Detect frustration and satisfaction trends as optimization triggers | `src/wild/sentiment_tracker.py` |
| Learning velocity | Correction rate tracking, ROI calculation, acceleration detection | `src/wild/learning_velocity.py` |
| Writing style tracking | Catches unintentional drift vs intentional compression | `src/wild/personality_drift.py` |
| Relevance explanation | Shows why each search result matched with highlighted snippets | `src/relevance_explanation.py` |
| Temporal knowledge graph | Tracks entities and relationships across time with evolution queries | `src/temporal_knowledge_graph.py` |
| Memory PageRank | Iterative PageRank on relationship graph for structural importance | `src/memory_pagerank.py` |
| Schema classifier | Classifies new memories as assimilation/extension/accommodation (Bartlett) | `src/schema_classifier.py` |
| Retrieval-induced forgetting | Detects retrieval blind spots where few memories dominate search (Gini) | `src/retrieval_forgetting.py` |

---

## Autonomous — the system that works while you sleep

| Feature | What it does | File |
|---------|-------------|------|
| Daily episodic summaries | End-of-day session summaries for next-day context injection | `src/daily_episodic_summary.py` |
| Dream mode synthesis | Overnight consolidation finds hidden cross-domain connections | `src/wild/dream_synthesizer.py` |
| Frustration early warning | Detects repeated corrections before you spiral, suggests interventions | `src/wild/frustration_detector.py` |
| Momentum tracking | Knows when you're "on a roll" vs "spinning" (0–100 score) | `src/wild/momentum_tracker.py` |
| Energy-aware scheduling | Learns your best thinking hours, suggests optimal times | `src/wild/energy_scheduler.py` |
| Decision regret detection | Warns before you repeat a mistake — "You've made this call 4 times. 3 times you regretted it." | `src/wild/regret_detector.py` |
| Decision regret loop | Real-time fuzzy matching against regret database before decisions | `src/decision_regret_loop.py` |
| Pattern transfer | Solutions from one project surface for similar problems elsewhere | `src/wild/pattern_transfer.py` |
| Cross-client synthesis | Reads consent-tagged memories across projects, generates transfer hypotheses | `src/cross_client_synthesizer.py` |
| Prompt evolution | Genetic algorithm optimizes extraction prompts using quality grades | `src/wild/prompt_evolver.py` |
| Context pre-loading | Checks calendar, pre-loads relevant context before meetings | `src/wild/context_preloader.py` |
| Temporal prediction | Predicts what you'll need from memory access patterns | `src/wild/temporal_predictor.py` |
| Context decay prediction | Predicts staleness before it happens | `src/wild/decay_predictor.py` |
| Frustration archaeology | Mines session history for recurring frustration patterns | `src/wild/frustration_archaeology.py` |
| Memory interview | Interactive Q&A to deepen shallow memories via guided elicitation | `src/memory_interview.py` |
| Prospective triggers | Event/topic/time-based "remember when X" triggers from conversation | `src/prospective_triggers.py` |
| Expertise mapping | Maps agent expertise by domain for intelligent routing | `src/wild/expertise_mapper.py` |
| Mistake cascade detection | Tracks mistake cascades to prevent compound errors | `src/wild/mistake_cascade.py` |
| Learning intervention | Detects repeated questions, suggests learning resources | `src/wild/learning_interventioner.py` |
| A/B testing | Test extraction and ranking strategies against live corpus | `src/wild/ab_tester.py` |
| Quality grading | Grade memories A/B/C/D, learns quality patterns over time | `src/wild/quality_grader.py` |
| Conflict prediction | Pre-save contradiction detection with confidence scoring | `src/wild/conflict_predictor.py` |
| Memory lifespan prediction | Predicts how long a memory will stay relevant, flags for review | `src/wild/lifespan_integration.py` |
| Meta-learning | A/B testing memory strategies on live corpus | `src/meta_learning_system.py` |

---

## Multimodal capture

| Feature | What it does | File |
|---------|-------------|------|
| Voice capture | Transcribe voice memos, extract insights as memories | `src/multimodal/voice_capture.py` |
| Image capture | Screenshots and OCR → vision analysis → memories | `src/multimodal/image_capture.py` |
| Code memory | Code snippet library with semantic search | `src/multimodal/code_memory.py` |

---

## Dashboard — see what your memory knows

| Feature | What it does | Endpoint |
|---------|-------------|----------|
| Overview | Stat cards, grade distribution, domain breakdown, 26-week activity heatmap | `/` |
| Memory library | Searchable, filterable, click-to-detail with full content modal | `/api/memories` |
| Session history | Every session indexed with message, tool, and memory counts | `/api/sessions` |
| Session replay | Click session → view transcript turns + linked memories | `/api/session/<id>` |
| Knowledge map | Tag cloud + domain breakdown | `/api/knowledge-map` |
| Export | JSON and CSV, one click | `/api/export` |
| Memory freshness | Staleness indicators (opacity + colored pips), stale filter | `/api/memories` |
| Search with explanation | Match reasons + highlighted snippets on every search result | `/api/memories?q=` |
| Morning briefing | Cluster-based briefing with content previews and divergence signals | `/api/briefing` |
| Intelligence dashboard | Synthesized signals from 5 sources into prioritized daily briefing | `/api/intelligence` |
| Cross-client patterns | Transfer hypotheses across projects | `/api/cross-client` |
| Regret check | Real-time decision regret warnings | `/api/regret-check` |
| Notifications | Alert feed with badge count, dismissable | `/api/notifications` |

---

## Infrastructure — what keeps it running

| Feature | What it does | File |
|---------|-------------|------|
| Circuit breaker | LLM calls protected: closed/open/half_open states, SQLite persistence, fallback support, 5-failure threshold, 600s recovery | `src/circuit_breaker.py` |
| FAISS vector store | Indexed similarity search with L2-normalized cosine, dual-write with SQLite fallback | `src/vector_store.py` |
| Centralized config | All paths and constants overridable via `MEMORY_SYSTEM_*` environment variables | `src/config.py` |
| Async consolidation | Queue-based background memory extraction (<1s to queue) | `src/async_consolidation.py` |
| Session end hook | Automatic memory extraction on every session close | `hooks/session-memory-consolidation-async.py` |
| GitHub Actions CI | Pytest on push/PR, Python 3.11/3.12/3.13 matrix | `.github/workflows/test.yml` |
| Memory freshness review | Weekly scan/refresh/archive cycle with notification summary | `src/memory_freshness_reviewer.py` |
| Intelligence orchestrator | Central "brain stem" wiring all features into coherent signals | `src/intelligence_orchestrator.py` |
| Cluster briefing | Surfaces cluster summaries and divergence signals | `src/cluster_briefing.py` |
| Log rotation | Automated log file management | `src/log_rotation.py` |
| Compaction triggers | Time/size/quality/access-based triggers for memory compaction | `src/compaction_triggers.py` |
| Energy-aware loading | Throttles memory loading based on system/user energy state | `src/energy_aware_loading.py` |
| Persona filter | Filters memories by persona/context for role-appropriate recall | `src/persona_filter.py` |
| Memory compressor | Lossless and lossy compression strategies preserving key insights | `src/memory_compressor.py` |
| Memory health score | Composite health metric across freshness, quality, connections, access | `src/memory_health.py` |
| Event stream | Pub/sub event system for memory lifecycle with persistence | `src/event_stream.py` |
| Access tracker | Tracks memory access patterns with frequency analytics | `src/access_tracker.py` |
| Context budget optimizer | Greedy token-budget optimizer for memory retrieval within limits | `src/context_budget.py` |
| Cross-project sharing DB | SQLite-backed cross-project memory sharing with permissions | `src/cross_project_sharing_db.py` |
| Embedding maintenance | Pre-computes and refreshes embeddings for fast search | `src/embedding_maintenance.py` |
| Unified API | Single `MemorySystem` class wrapping all features | `src/api.py` |
| Self-test diagnostics | Validates system integrity: DB, files, config, search | `src/self_test.py` |
| Intelligence DB pool | Connection pooling for intelligence.db with WAL mode | `src/intelligence_db.py` |
| Generational GC | Three-generation memory lifecycle with graduated collection (Ungar 1984) | `src/generational_gc.py` |
| Content hash dedup | Multi-level deduplication: exact, normalized, semantic hash | `src/content_dedup.py` |
| Reference counter | Tracks memory dependency counts, protects referenced memories from archival | `src/reference_counter.py` |

---

## Architecture

**Single database** — All features share `intelligence.db` with schema namespacing. Enables cross-feature queries like "show A-grade memories that triggered frustration warnings."

**Local embeddings** — sentence-transformers (`all-MiniLM-L6-v2`). No API costs per query. 384-dim vectors. Runs offline.

**Hybrid search** — 70% semantic + 30% BM25 keyword. Semantic understanding meets exact-match precision.

**FAISS vector store** — `IndexFlatIP` with L2-normalized inner product (= cosine similarity). Dual-write: FAISS for fast indexed search, SQLite fallback for compatibility.

**FSRS-6 spaced repetition** — Tracks memory stability, difficulty, and intervals. FAIL/HARD/GOOD/EASY grading on reinforcements.

**Circuit breaker** — CLOSED/OPEN/HALF_OPEN states. 3-failure threshold, 60s recovery timeout. Separate breakers per LLM call pathway.

**Additive design** — New features layer on existing, never replace. The contradiction detector doesn't disable the quality grader — it feeds it. Adding feature N+1 makes features 1 through N better.
