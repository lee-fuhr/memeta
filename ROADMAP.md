# Memory system v1 — build roadmap

**Status:** Active — serial execution, managed from main session
**Last updated:** 2026-02-14

## Progress log

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Gap analysis | ✅ Done | 1,368 lines across 4 files. Key finds: IDF=1.0 bug, cross_project_sharing.py is a stub |
| 2 | Test critical modules | ✅ Done | 318 new tests, 1085 total passing. Fixed 4 mock issues in hybrid_search |
| 3 | Connection leak fix | 🔄 Next | |
| 4 | sys.path cleanup | ⬜ Queued | |
| 5 | Circuit breaker (TDD) | ⬜ Queued | |
| 6 | Vector migration (TDD) | ⬜ Queued | Heaviest — may need fresh quota window |
| 7 | Search merge | ⬜ Queued | Depends on #6 |

---

## Phases

### Phase 1 — parallel (safe to start simultaneously)

| Task | Approach | Why parallel-safe |
|------|----------|-------------------|
| Gap analysis | Ralph (Sonnet, 25 iter) | Docs only — `docs/gap-analysis/` |
| Test critical modules | Ralph (Haiku, 20 iter) | New test files only — `tests/` |
| Connection leak fix | Spawned agent | Touches one module only — `src/wild/intelligence_db.py` |

**Launch:** `ralph-run spec-memory-gap-analysis` + `ralph-run spec-test-critical-modules` + spawn connection leak agent

---

### Phase 2 — after Phase 1 complete

| Task | Approach | Depends on |
|------|----------|------------|
| sys.path cleanup | Spawned agent (TDD) | Tests from Phase 1 provide safety net |
| Circuit breaker | Spawned agent (TDD) | Clean src/ from sys.path pass |

**Circuit breaker approach:** Write tests first (behavior spec), then implement `src/circuit_breaker.py`, then wire into exactly 3 LLM call sites. Test gates each step.

---

### Phase 3 — after Phase 2 stable

| Task | Approach | Depends on |
|------|----------|------------|
| Vector migration | Spawned agent (TDD) | Stable test suite, clean imports |

**Vector migration approach:** Define `VectorStore` interface with tests first. Implement ChromaDB behind that interface. Dual-write (SQLite + ChromaDB) for safety. Existing code untouched until tests prove the new layer works.

---

### Phase 4 — after Phase 3

| Task | Approach | Depends on |
|------|----------|------------|
| Search merge | Spawned agent | Clean vector backend to merge into |

---

## What NOT to Ralph

- Vector migration (architectural, too risky)
- Search merge (needs judgment about what's truly duplicate)
- sys.path cleanup (cascades too easily — needs test safety net first)

---

## Files

| Spec | Location |
|------|----------|
| Gap analysis | `_ Operations/autonomous/spec-memory-gap-analysis.md` |
| Test critical modules | `_ Operations/autonomous/spec-test-critical-modules.md` |
| Connection leak | Prompt in this doc (see below) |

---

## Agent prompts (non-Ralph tasks)

### Connection leak fix

**Goal:** Fix IntelligenceDB/WildFeaturesDB connection leak — every `.get_connection()` call must use a context manager.

**Prompt for spawned agent:**
```
Fix the IntelligenceDB connection leak in /Users/lee/CC/LFI/_ Operations/memory-system-v1/src/wild/intelligence_db.py

Steps:
1. Read the file fully
2. Run baseline: python -m pytest tests/ -q --tb=short 2>&1 | tail -5 (must show 765 passing)
3. Find every method that calls get_connection() without a with statement
4. Replace bare conn = self.get_connection() patterns with with self.get_connection() as conn: blocks
5. If get_connection() doesn't support context manager (__enter__/__exit__), add it
6. Run pytest after each method change — stop and document if anything breaks
7. Commit: git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 commit -m 'Fix IntelligenceDB connection leak'
8. Final pytest must show 765+ passing, 0 failing

Do not touch any other files. If get_connection() is defined elsewhere, read that file too but only modify what's needed for context manager support.
```

### sys.path cleanup

**Goal:** Remove sys.path.insert/append from src/ files where the installed package makes them unnecessary.

**Prompt for spawned agent:**
```
Remove sys.path hacks from src/ files in /Users/lee/CC/LFI/_ Operations/memory-system-v1/

Steps:
1. Run baseline pytest (765 passing required)
2. Run: pip install -e . --quiet (installs package so imports work without sys.path)
3. Find all sys.path occurrences: grep -rn "sys\.path\." src/ --include="*.py"
4. For each file (process ONE at a time):
   a. Remove the sys.path line(s)
   b. Run: python -c "import [module_name]" to verify import still works
   c. Run full pytest — if any test fails, REVERT this file and move on
   d. If clean, commit this file: git commit -m "Remove sys.path hack from [filename]"
5. Skip any file in scripts/ — leave those alone
6. Final report: X files cleaned, Y files skipped (reason)

One file at a time. Commit after each successful file. Revert immediately on failure.
```

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
Run full pytest after each wire-in — 765+ passing required before touching the next one.

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
- Run full pytest — 765+ passing required.

Step 4 — Update semantic_search.py:
- Use VectorStore.find_similar() instead of brute-force cosine
- Keep old cosine as _fallback if VectorStore is None
- Run full pytest — 765+ passing required.

Step 5 — Create migration script: scripts/migrate_embeddings_to_chroma.py
- Reads existing SQLite embeddings, writes to ChromaDB
- Supports --dry-run flag
- Idempotent (skip if already migrated)

Step 6 — Commit everything:
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 add src/vector_store.py tests/test_vector_store.py scripts/migrate_embeddings_to_chroma.py
git -C /Users/lee/CC/LFI/_ Operations/memory-system-v1 commit -m "Vector migration: ChromaDB with dual-write (TDD)"
```
