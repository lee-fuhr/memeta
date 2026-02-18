# Total Recall — prioritized backlog

**Last updated:** 2026-02-17
**Version:** v0.16.0 (search explain, freshness review, session replay, CI)
**Total memories:** 1,255 | **Sessions:** 500 | **Tests:** 1,145

---

## Tier 1 — high impact, low effort (do next)

These are concrete improvements that build on existing infrastructure with minimal risk.

### ~~1. Circuit breaker for LLM calls~~ ✅ Done (v0.14.0)
Shipped: `src/circuit_breaker.py` — 12 tests, 3 LLM call sites wired (extraction, ask_claude, contradiction)

### ~~2. Session end hook for automatic memory extraction~~ ✅ Done (v0.15.0)
Already existed at `hooks/session-memory-consolidation.py` but was broken since Feb 12 (venv python + dashboard_export syntax error). Fixed and added Pushover notification on save.

### ~~3. Memory freshness review cycle~~ ✅ Done (v0.16.0)
Shipped: `src/memory_freshness_reviewer.py` — scan/refresh/archive CLI, Pushover summary, weekly LaunchAgent (Sundays 9am). 18 tests.

### ~~4. "Explain why" on search results~~ ✅ Done (v0.16.0)
Shipped: `_extract_snippet()` + `_match_reasons()` in server.py. Search cards show highlighted snippet + match reason tags. 16 tests.

### ~~5. Dashboard: memory freshness indicators~~ ✅ Done (v0.16.0)
Shipped: `days_stale` field, CSS staleness classes (opacity), colored freshness pips, stale toggle filter.

---

## Tier 2 — high impact, medium effort (this month)

### 6. Intelligence orchestrator ("memory brain stem")
**Why:** 58 features exist but they're disconnected. Dream synthesis, momentum tracking, energy scheduling, regret detection each run independently. No conductor wires them together.
**What:** `src/intelligence_orchestrator.py` — background process that reads all wild/ feature outputs, synthesizes into 3-5 high-priority daily signals, surfaces via morning briefing.
**Effort:** ~8 hours
**Depends on:** Circuit breaker (#1)

### 7. Cluster-based morning briefing
**Why:** Memory clustering (F25) runs but output goes nowhere. Cluster summaries are computed and stored but never surfaced.
**What:** When session starts, load cluster summaries instead of raw memories. Detect cluster divergence as insight signal. "Your thinking about X has split into two distinct clusters."
**Effort:** ~4 hours (clustering already runs via F25)
**Depends on:** Intelligence orchestrator (#6) or standalone

### 8. Cross-client pattern transfer
**Why:** Lee solves problems for one client that apply to others. `pattern_transfer.py` and `cross_project_sharing.py` exist but aren't wired together.
**What:** Synthesis layer that reads across tagged insights and generates cross-client hypotheses. Tag-based consent model (cross_client_ok: true).
**Effort:** ~6 hours
**Depends on:** Nothing (but better after #6)

### 9. Decision regret loop — real-time warning
**Why:** `regret_detector.py` tracks decisions and outcomes but only retrospectively. Should warn before repeating mistakes.
**What:** Hook on session decisions that checks regret database. "You've made this call 4 times. Three times you regretted it."
**Effort:** ~4 hours (event_detector.py + regret_detector.py exist)
**Depends on:** Circuit breaker (#1)

### 10. Vector migration to ChromaDB
**Why:** Current embedding search is brute-force cosine over SQLite blobs. Won't scale past ~5K memories.
**What:** `src/vector_store.py` backed by ChromaDB. Dual-write during migration. TDD spec exists in ROADMAP.md.
**Effort:** ~6 hours
**Depends on:** Circuit breaker (#1)

---

## Tier 3 — medium impact, medium effort (this quarter)

### 11. Energy-aware memory loading
**Why:** Morning sessions need strategic memories, afternoon sessions need operational ones. Currently all memories are treated equally regardless of time of day.
**What:** Extend session startup to consult energy_scheduler.py. Different memory priority queues based on cognitive state.
**Effort:** ~4 hours
**Depends on:** Intelligence orchestrator (#6)

### 12. Frustration archaeology report
**Why:** Frustration detector (F55) only looks back 20 minutes. Monthly patterns go unnoticed.
**What:** Weekly report analyzing all frustration events over 90 days. Cluster into patterns. Suggest preventive hooks.
**Effort:** ~4 hours
**Depends on:** Nothing

### 13. Persona-aware memory filtering
**Why:** Lee has multiple modes (business, health, personal). Memories from one mode leak into others.
**What:** `MemoryFilter` class that uses project context to load relevant subset. Session startup enforces relevance.
**Effort:** ~3 hours
**Depends on:** Nothing

### 14. Memory interview (weekly structured review)
**Why:** Corpus grows without quality maintenance. Need structured pruning that doesn't feel like chores.
**What:** Dream synthesizer generates 5 questions from contradiction clusters, stale memories, un-rated decisions. Lee responds inline. 10 minutes/week.
**Effort:** ~5 hours
**Depends on:** Memory freshness review (#3)

### 15. Memory-as-training-data export
**Why:** 1,255 memories + quality grades = fine-tuning dataset for extraction quality improvement.
**What:** `corpus_exporter.py` — export A/B/C/D graded memories as classification examples, corrections as preference examples, session→memory pairs as training data.
**Effort:** ~3 hours
**Depends on:** Nothing

---

## Tier 4 — dashboard enhancements

### 16. Memory relationship graph
**Why:** Memories have `related_memories` fields but no visualization. Knowledge structure is invisible.
**What:** Force-directed graph view in Knowledge Map tab. Nodes = memories, edges = semantic similarity above threshold.
**Effort:** ~6 hours (D3.js or similar)
**Depends on:** Nothing

### ~~17. Session replay / context view~~ ✅ Done (v0.16.0)
Shipped: Click session row → transcript modal with user/assistant turns, session stats, linked memory chips. `/api/session/<id>` endpoint.

### 18. Dashboard notifications panel
**Why:** System generates signals (frustration events, contradiction detections, stale memories) but they're only in logs.
**What:** Notification feed in dashboard sidebar. Badge count. Dismissable.
**Effort:** ~4 hours
**Depends on:** Intelligence orchestrator (#6)

### 19. Search with explanation
**Why:** Dashboard search works but returns results without explaining relevance ranking.
**What:** Extend /api/memories to return relevance scores and explanation. Show in memory cards.
**Effort:** ~2 hours
**Depends on:** "Explain why" (#4)

---

## Tier 5 — infrastructure (as needed)

### 20. Search merge (consolidate search backends)
**Why:** F28 (SearchOptimizer) and F30 (MemoryAwareSearch) are two search layers. F30 delegates to F28 but the split is unnecessary.
**What:** Merge into single search module. Remove indirection.
**Effort:** ~3 hours
**Depends on:** Vector migration (#10)

### 21. Full test suite stabilization
**Why:** 2 flaky tests (LLM timeout). 1,085 of 1,087 pass consistently.
**What:** Mock LLM calls in flaky tests. Add circuit breaker integration.
**Effort:** ~2 hours
**Depends on:** Circuit breaker (#1)

### ~~22. GitHub Actions CI~~ ✅ Done (v0.16.0)
Shipped: `.github/workflows/test.yml` — pytest on push/PR, Python 3.11/3.12/3.13 matrix, pip caching.

### 23. PyPI packaging
**Why:** Currently install via `pip install -e .` from git clone. No public package.
**What:** Build and publish to PyPI. Version bump automation.
**Effort:** ~2 hours
**Depends on:** Push to GitHub

---

## Deferred (external dependencies)

These require third-party APIs or infrastructure not yet available:

- F36-43: External integrations (Slack, Notion, email, calendar)
- F66-74: Advanced integrations (webhook, API gateway, SSO)
- Voice memory capture (requires MacWhisper integration)
- Image context extraction (requires vision API)

---

## Completed (for reference)

| Item | Version | Date |
|------|---------|------|
| Rename to Total Recall | v0.11.0 | 2026-02-16 |
| Dashboard (Flask + full UI) | v0.12.0 | 2026-02-16 |
| F30→F28 search delegation | v0.11.0 | 2026-02-15 |
| IntelligenceDB connection leak | v0.11.0 | 2026-02-15 |
| Dream mode O(n²) fix | v0.10.0 | 2026-02-14 |
| F26+F31 summarization merge | v0.10.0 | 2026-02-14 |
| Config centralization (src/config.py) | v0.9.0 | 2026-02-14 |
| sys.path elimination (71 files) | v0.8.0 | 2026-02-14 |
| Memory detail modal | v0.13.0 | 2026-02-16 |
| Export JSON/CSV | v0.13.0 | 2026-02-16 |
| LaunchAgent auto-start | v0.13.0 | 2026-02-16 |
| Circuit breaker for LLM calls | v0.14.0 | 2026-02-17 |
| Consolidation hook fix + Pushover | v0.15.0 | 2026-02-17 |
| "Explain why" on search results | v0.16.0 | 2026-02-17 |
| Dashboard freshness indicators | v0.16.0 | 2026-02-17 |
| GitHub Actions CI | v0.16.0 | 2026-02-17 |
| Memory freshness review cycle | v0.16.0 | 2026-02-17 |
| Session replay modal | v0.16.0 | 2026-02-17 |
