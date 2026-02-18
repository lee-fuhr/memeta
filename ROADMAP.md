# Total Recall — build roadmap

**Status:** v0.16.0 — search explain, freshness review, session replay, CI
**Last updated:** 2026-02-17

## Progress log

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Gap analysis | ✅ Done | 1,368 lines across 4 files. Key finds: IDF=1.0 bug, cross_project_sharing.py is a stub |
| 2 | Test critical modules | ✅ Done | 318 new tests, 1,085 total passing. Fixed 4 mock issues in hybrid_search |
| 3 | Connection leak fix | ✅ Done | IntelligenceDB: replaced pool.get_connection() with sqlite3.connect() directly |
| 4 | sys.path cleanup | ✅ Done | 71 files migrated to `from memory_system.X import ...`. pyproject.toml + pip install -e . |
| 5 | Config centralization | ✅ Done | `src/config.py` — MemorySystemConfig frozen dataclass, env var overrides |
| 6 | F26+F31 summarization merge | ✅ Done | Unified MemorySummarizer with TopicSummary + connection leak fixes |
| 7 | F30→F28 search delegation | ✅ Done | MemoryAwareSearch.search() delegates to SearchOptimizer |
| 8 | Dream mode O(n²) fix | ✅ Done | MAX_MEMORIES=1000 cap |
| 9 | Rename to Total Recall | ✅ Done | Full rename from Mnemora |
| 10 | Dashboard | ✅ Done | Flask server + full-stack UI (overview, memories, sessions, knowledge map) |
| 11 | Memory detail modal | ✅ Done | Click card → full content overlay. /api/memory/<id> endpoint |
| 12 | Export JSON/CSV | ✅ Done | /api/export endpoint + buttons. Fixed YAML tags parsing |
| 13 | LaunchAgent | ✅ Done | com.lfi.total-recall-dashboard — RunAtLoad + KeepAlive on port 7860 |
| 14 | Backlog | ✅ Done | BACKLOG.md — 23 items across 5 priority tiers |
| 15 | Push to GitHub | ✅ Done | All commits on origin/main |
| 16 | Circuit breaker (TDD) | ✅ Done | 12 tests, 3 LLM call sites wired. Breakers: llm_extraction, llm_ask_claude, llm_contradiction |
| 17 | Fix consolidation hook | ✅ Done | Broken since Feb 12 — venv python + dashboard_export indentation fix |
| 18 | Pushover notifications | ✅ Done | Hook sends push when memories saved/reinforced |
| 19 | "Explain why" search | ✅ Done | Snippet extraction, match reasons, highlights |
| 20 | Dashboard freshness indicators | ✅ Done | Staleness visual (opacity + pips), stale filter |
| 21 | GitHub Actions CI | ✅ Done | pytest on push/PR, Python 3.11-3.13 matrix |
| 22 | Memory freshness review | ✅ Done | scan/refresh/archive CLI, Pushover, LaunchAgent |
| 23 | Session replay modal | ✅ Done | Click session → transcript + memories overlay |
| 24 | Vector migration (TDD) | ⬜ Queued | Backlog tier 2 |
| 25 | Search merge | ⬜ Queued | Depends on #24. Backlog tier 5 |

---

## What's next

**Tier 1 complete.** All 5 items shipped (v0.14.0–v0.16.0).

**Now building (from BACKLOG.md tier 2):**
1. Cluster-based morning briefing (#7)
2. Vector migration to ChromaDB (#10)
3. Intelligence orchestrator (#6)
4. Cross-client pattern transfer (#8)
5. Decision regret loop (#9)

**Full backlog:** `BACKLOG.md` (23 items, 5 tiers)

---

## Agent prompts (for remaining tasks)

### Circuit breaker (TDD)

**Goal:** Build and wire in a circuit breaker for LLM calls using test-driven development.

**Prompt for spawned agent:**
```
Build a circuit breaker for LLM calls in /Users/lee/CC/LFI/_ Operations/memory-system-v1/ using TDD.

Step 1 — Write tests first (tests/test_circuit_breaker.py):
- test_closed_state_passes_calls_through
- test_opens_after_3_consecutive_failures
- test_open_state_raises_CircuitBreakerOpenError_immediately
- test_transitions_to_half_open_after_recovery_timeout
- test_closes_again_after_success_in_half_open
- test_reset_returns_to_closed
Run pytest — all 6 must FAIL (not yet implemented). If any pass, the test is wrong.

Step 2 — Implement src/circuit_breaker.py:
- CircuitBreaker class: CLOSED / OPEN / HALF_OPEN states
- __init__(failure_threshold=3, recovery_timeout=60.0, name='default')
- call(fn, *args, **kwargs) — wraps a callable with circuit breaker logic
- reset() — manual reset to CLOSED
- Module-level: get_breaker(name) -> CircuitBreaker (singleton registry)
Run pytest — all 6 must now PASS.

Step 3 — Wire into exactly 3 LLM call sites:
Find the 3 highest-risk LLM calls: grep -rn "anthropic\|openai\|llm\|completion\|chat" src/ --include="*.py" | grep -v "__pycache__" | grep -v test
For each: wrap with get_breaker('name').call(fn, ...) and handle CircuitBreakerOpenError with a logged fallback
Run full pytest after each wire-in — 1085+ passing required before touching the next one.

Step 4 — Commit:
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 add src/circuit_breaker.py tests/test_circuit_breaker.py
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 commit -m "Add circuit breaker for LLM calls (TDD)"
```

### Vector migration (TDD)

**Goal:** Migrate embedding storage from SQLite blobs to ChromaDB with hybrid BM25+vector search.

**Prompt for spawned agent:**
```
Migrate memory-system-v1 embeddings to ChromaDB using TDD.
Working directory: /Users/lee/CC/LFI/_ Operations/memory-system-v1/

Step 1 — Define the interface with tests first (tests/test_vector_store.py):
Write tests for a VectorStore class that doesn't exist yet:
- test_store_and_retrieve_embedding (store np.ndarray, get same array back)
- test_find_similar_returns_ranked_results (store 3, query returns correct top-1)
- test_threshold_filters_low_scores (nothing below 0.65)
- test_graceful_import_error (if chromadb not installed, raises ImportError with message)
Run pytest on just this file — all must FAIL.

Step 2 — Implement src/vector_store.py:
pip install 'chromadb>=0.4.0'
Build VectorStore backed by ChromaDB PersistentClient at ./chroma_db/
Interface: get_embedding(hash) / store_embedding(hash, array, metadata) / find_similar(array, top_k, threshold)
Run test_vector_store.py — all must PASS before proceeding.

Step 3 — Update embedding_manager.py (dual-write):
- Try to import VectorStore; if unavailable, set to None
- In store_embedding(): write to BOTH SQLite (existing) AND VectorStore (new)
- In get_embedding(): check VectorStore first, fall back to SQLite
- Run full pytest — 1085+ passing required.

Step 4 — Update semantic_search.py:
- Use VectorStore.find_similar() instead of brute-force cosine
- Keep old cosine as _fallback if VectorStore is None
- Run full pytest — 1085+ passing required.

Step 5 — Create migration script: scripts/migrate_embeddings_to_chroma.py
- Reads existing SQLite embeddings, writes to ChromaDB
- Supports --dry-run flag
- Idempotent (skip if already migrated)

Step 6 — Commit everything:
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 add src/vector_store.py tests/test_vector_store.py scripts/migrate_embeddings_to_chroma.py
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 commit -m "Vector migration: ChromaDB with dual-write (TDD)"
```
