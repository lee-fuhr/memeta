# Build specs — top 5 gaps

**Created:** 2026-02-14
**Priority order:** (1) provenance, (2) daily episodic summaries, (3) hybrid search unification, (4) circuit breakers, (5) memory decay

These are fully prescriptive Ralph-ready specs. Each is complete enough for a junior agent to execute without additional context.

---

## Spec 1: Provenance tracking

**Goal:** Tag every memory with the session ID that produced it so "when did I say that?" queries are answerable.

**Constraints:**
- Branch: `feature/provenance-tracking` (from `main`)
- Protected files: Do not modify test files that are currently passing. Do not change `intelligence.db` schema in a breaking way.
- Max iterations: 8

**Success criteria:**
1. `MemoryTSClient.add(content, session_id="abc123")` writes a memory with `source_session_id: abc123` in its YAML frontmatter.
2. `MemoryTSClient.get(memory_id).source_session_id` returns the correct session ID.
3. `MemoryTSClient.add(content)` (no session_id) still works — field is optional.
4. `session_consolidator.py` passes the current session ID to every `add()` call (grep and update all call sites).
5. All existing tests still pass (baseline: 765/767).
6. At least 8 new tests for the provenance feature (happy path, missing session_id, legacy memories, round-trip).

**Verification commands:**
```bash
cd "/Users/lee/CC/LFI/_ Operations/memory-system-v1"
pytest tests/ -v --tb=short 2>&1 | tail -20
python -c "
from src.memory_ts_client import MemoryTSClient
import tempfile, os
with tempfile.TemporaryDirectory() as d:
    client = MemoryTSClient(memory_dir=d)
    mid = client.add('prefers dark mode', session_id='test-session-123')
    mem = client.get(mid)
    assert mem.source_session_id == 'test-session-123', f'Got: {mem.source_session_id}'
    mid2 = client.add('another memory')
    mem2 = client.get(mid2)
    assert mem2.source_session_id is None
    print('PROVENANCE OK')
"
grep -r "session_id" src/session_consolidator.py | head -5
```

**Full prompt:**

You are implementing provenance tracking for a Python memory system. The codebase is at `/Users/lee/CC/LFI/_ Operations/memory-system-v1/`.

Read these files first:
- `src/memory_ts_client.py` — the memory client you'll modify
- `src/session_consolidator.py` — the main call site for memory saves
- `tests/test_memory_ts_client.py` — the test file to extend

**What to implement:**

1. Add `source_session_id: Optional[str] = None` to the memory dataclass/dict structure in `memory_ts_client.py`.

2. Modify the `add()` method signature to accept `session_id: Optional[str] = None`. When writing the YAML frontmatter, include `source_session_id: <value>` if provided. If not provided, omit the field (don't write `source_session_id: null` — just skip it).

3. Modify the `get()` method (and any list/search methods) to read `source_session_id` from YAML frontmatter if present. Return `None` if absent (backward-compatible).

4. Find all call sites in `session_consolidator.py` that call `client.add()` or equivalent. Pass the current session ID to each call. The session ID is available from the session context — look for how the session consolidator gets called and trace the session ID parameter.

5. Write at least 8 new tests in `tests/test_memory_ts_client.py`:
   - Save with session_id, verify it round-trips
   - Save without session_id, verify field is None (not error)
   - Load a legacy memory (no source_session_id in YAML), verify no crash
   - Update a memory, verify source_session_id is preserved
   - Multiple memories from same session, verify all have same source_session_id
   - source_session_id survives a full save/load/list cycle
   - Two more edge cases of your choice

6. Run `pytest tests/ -v --tb=short` to verify all tests pass. Fix any failures before finishing.

**Do not:**
- Change the intelligence.db schema
- Add new dependencies
- Modify files in `src/wild/` or `src/multimodal/`
- Break existing test assertions

When done, output the count of passing tests and a summary of changes made.

---

## Spec 2: Daily episodic summaries

**Goal:** Generate a daily `YYYY-MM-DD.md` summary file at 23:55 each night so the next session starts with yesterday's context already loaded.

**Constraints:**
- Branch: `feature/daily-episodic-summaries` (from `main`)
- Protected files: Do not modify `nightly_maintenance_master.py` in a way that changes its existing behavior. Do not change `session_history_db.py` schema.
- Max iterations: 10

**Success criteria:**
1. `python -m src.daily_episodic_summary` runs without error and produces `~/memory/YYYY-MM-DD.md`.
2. The summary file is non-empty and contains at least 50 words of AI-generated content.
3. `launch-agents/com.memory.daily-summary.plist` exists and passes `plutil -lint` validation.
4. `session_consolidator.py` has a function `load_daily_context(days=2)` that reads the last 2 summary files and returns their content as a string.
5. At least 10 tests (mocked Claude API, file creation, error handling when no sessions exist, multiple sessions aggregation).
6. All existing tests still pass.

**Verification commands:**
```bash
cd "/Users/lee/CC/LFI/_ Operations/memory-system-v1"
pytest tests/test_daily_episodic_summary.py -v 2>&1 | tail -20
plutil -lint "launch-agents/com.memory.daily-summary.plist" && echo "PLIST OK"
python -c "
import tempfile, os, sys
from unittest.mock import patch, MagicMock
from src.daily_episodic_summary import DailyEpisodicSummary
with tempfile.TemporaryDirectory() as d:
    with patch('src.daily_episodic_summary.call_claude_api') as mock_claude:
        mock_claude.return_value = 'Today we discussed Connection Lab messaging and decided on the transformation angle.'
        summarizer = DailyEpisodicSummary(output_dir=d)
        result = summarizer.generate(sessions=[{'content': 'test session content', 'id': 'sess1'}])
        assert os.path.exists(result), f'File not created: {result}'
        assert os.path.getsize(result) > 0, 'File is empty'
        print('DAILY SUMMARY OK:', result)
"
```

**Full prompt:**

You are adding daily episodic summaries to a Python memory system. The codebase is at `/Users/lee/CC/LFI/_ Operations/memory-system-v1/`.

Read these files first:
- `src/session_history_db.py` — how to query session history
- `src/session_consolidator.py` — where to add context loading
- `launch-agents/` — look at existing plists for format reference
- `src/llm_extractor.py` — how Claude API is called in this codebase

**What to implement:**

1. Create `src/daily_episodic_summary.py` with a `DailyEpisodicSummary` class:
   - `__init__(self, output_dir: Optional[Path] = None, db_path: Optional[str] = None)`
   - `generate(date: Optional[date] = None) -> Path` — generates summary for the given date (defaults to today). Queries `session_history_db` for all sessions from that date, aggregates content (cap at 6000 chars), calls Claude API with the summary prompt below, writes to `{output_dir}/YYYY-MM-DD.md`, returns the Path.
   - `load_recent(days: int = 2) -> str` — loads the last N daily summaries and returns their content concatenated with date headers. Returns empty string if no files exist.
   - Handle gracefully: no sessions today (write "No sessions today."), API failure (write "Summary unavailable: {error}"), output_dir doesn't exist (create it).

2. Summary prompt to use with Claude API:
   ```
   Summarize today's work sessions. Focus on:
   - Key decisions made
   - Topics discussed
   - Open questions or next steps
   - Anything unusual or notable

   Be concise — max 200 words. Write in past tense. Start with the most important item.

   Sessions:
   {content}
   ```

3. Create `launch-agents/com.memory.daily-summary.plist` that runs `python -m src.daily_episodic_summary` at 23:55 daily. Follow the same format as other plists in the `launch-agents/` directory.

4. Add `load_daily_context()` to `session_consolidator.py` that calls `DailyEpisodicSummary().load_recent(days=2)`.

5. Create `tests/test_daily_episodic_summary.py` with at least 10 tests:
   - Generate summary with mocked API and verify file is created
   - Generate summary with no sessions (verify graceful handling)
   - Generate summary with API failure (verify fallback)
   - load_recent() with no files returns empty string
   - load_recent() with 2 existing files returns both
   - Date parameter works correctly
   - Output directory auto-created if missing
   - Multiple sessions are aggregated, not just one
   - Content is capped at 6000 chars
   - At least one more edge case

6. Run `pytest tests/test_daily_episodic_summary.py -v` and fix all failures.

**Do not:**
- Modify existing test files
- Add non-standard dependencies (Claude API is already used in this codebase)
- Store summaries in intelligence.db (flat files in ~/memory/ only)

---

## Spec 3: Hybrid search unification

**Goal:** Fix hybrid_search.py so BM25 IDF is computed from actual corpus frequency and semantic scoring uses pre-computed embeddings (not per-document model calls).

**Constraints:**
- Branch: `feature/hybrid-search-fix` (from `main`)
- Protected files: Do not change the public API signature of `hybrid_search()`. Existing callers must continue to work.
- Max iterations: 8

**Success criteria:**
1. `bm25_score(query="the the the", doc, avg_length)` scores lower than `bm25_score(query="morning standup preference", doc_containing_those_words, avg_length)` on a realistic corpus.
2. `hybrid_search(query, memories, embeddings=precomputed_dict)` accepts a pre-computed embeddings dict and completes in < 500ms for 500 memories.
3. Without `embeddings` parameter, fallback to on-demand embedding still works (no regression).
4. Score normalization: both semantic and BM25 scores are normalized to [0, 1] before the 70/30 weighting is applied.
5. At least 10 new tests in `tests/test_hybrid_search.py` covering: IDF calculation, normalization, pre-computed embeddings path, fallback path, empty corpus, single document, top_k > len(memories).
6. All existing tests pass.

**Verification commands:**
```bash
cd "/Users/lee/CC/LFI/_ Operations/memory-system-v1"
pytest tests/test_hybrid_search.py -v 2>&1 | tail -30
python -c "
from src.hybrid_search import bm25_score, compute_idf, hybrid_search
# Test IDF matters
docs = ['the the the quick brown fox', 'morning standup meeting preference', 'standup preference noted']
idf = compute_idf(docs)
score_common = bm25_score('the the the', docs[0], avg_doc_length=5, idf=idf)
score_rare = bm25_score('standup preference', docs[1], avg_doc_length=5, idf=idf)
assert score_rare > score_common, f'IDF not working: common={score_common:.3f} rare={score_rare:.3f}'
print(f'IDF OK: common={score_common:.3f} rare={score_rare:.3f}')
"
```

**Full prompt:**

You are fixing the hybrid search implementation in a Python memory system. The codebase is at `/Users/lee/CC/LFI/_ Operations/memory-system-v1/`.

Read these files first:
- `src/hybrid_search.py` — the file you'll fix
- `src/semantic_search.py` — how semantic search works
- `src/embedding_manager.py` — pre-computed embedding infrastructure
- `tests/test_hybrid_search.py` (if it exists) — existing tests to extend

**Problems to fix:**

**Problem 1: IDF = 1.0 (line ~64)** — the hardcoded `idf = 1.0` means all terms are weighted equally. Common words like "the" score the same as rare meaningful terms like "standup."

Fix: Add a `compute_idf(documents: List[str]) -> Dict[str, float]` function:
```python
def compute_idf(documents: List[str]) -> Dict[str, float]:
    """Compute IDF for all terms across corpus."""
    N = len(documents)
    df = Counter()
    for doc in documents:
        terms = set(doc.lower().split())
        df.update(terms)
    return {term: math.log((N + 1) / (count + 1)) + 1 for term, count in df.items()}
```
Update `bm25_score()` to accept an `idf: Optional[Dict[str, float]] = None` parameter. Use the dict if provided, fall back to 1.0 if None (backward-compatible).

**Problem 2: Per-document embedding calls** — `hybrid_search()` calls `semantic_search(query, [single_memory])` inside a loop. This causes N model calls per search query.

Fix: Add an `embeddings: Optional[Dict[str, list]] = None` parameter to `hybrid_search()`. If provided, use the pre-computed embeddings dict (`memory_id -> embedding vector`) for cosine similarity instead of calling the model. Update the scoring loop to check `embeddings.get(memory.get('id'))` before falling back to on-demand embedding.

**Problem 3: No score normalization** — semantic scores are [0, 1] but BM25 scores can be any positive float. The 70/30 weighting only makes sense if both are on the same scale.

Fix: After computing all scores, normalize BM25 scores to [0, 1] by dividing by max BM25 score in the batch (min-max normalization). Add a `normalize_scores(scores: List[float]) -> List[float]` helper.

**What to change:**
1. Add `compute_idf()` function
2. Update `bm25_score()` to use IDF dict parameter
3. Update `hybrid_search()` to pre-compute IDF from the corpus before scoring
4. Add `embeddings` parameter to `hybrid_search()`
5. Add `normalize_scores()` helper
6. Apply normalization before weighted combination

**Tests to add** (create `tests/test_hybrid_search.py` if it doesn't exist):
- IDF: common word scores lower than rare word
- IDF: term not in corpus gets handled gracefully (not KeyError)
- Score normalization: all normalized scores in [0, 1]
- Pre-computed embeddings path: passes embeddings dict, no model calls made (mock semantic_search)
- Fallback path: no embeddings dict provided, falls back gracefully
- Empty corpus: returns []
- Single document: returns it
- top_k > len(memories): returns all memories
- Weights sum to 1.0: semantic_weight + bm25_weight = 1.0 assertion
- End-to-end: hybrid_search returns results sorted by score descending

Run `pytest tests/ -v --tb=short` and fix all failures.

---

## Spec 4: Circuit breaker for LLM calls

**Goal:** Prevent cascading failures when Claude API is down by implementing a circuit breaker that opens after 5 failures and recovers automatically.

**Constraints:**
- Branch: `feature/circuit-breaker` (from `main`)
- Protected files: Do not modify test files. Circuit breaker state must persist in intelligence.db, not in-memory only.
- Max iterations: 10

**Success criteria:**
1. After 5 consecutive simulated API failures, `CircuitBreaker.call(fn)` returns the fallback value without calling `fn`.
2. Circuit state persists across process restarts (stored in intelligence.db).
3. After 10 minutes (or configurable timeout), circuit transitions to half-open and allows one test call.
4. On test call success, circuit closes (resets). On test call failure, circuit stays open.
5. `get_circuit_state()` returns `{"state": "closed"|"open"|"half-open", "failures": N, "last_failure_at": timestamp}`.
6. At least 3 LLM call sites in the codebase are wrapped with circuit breaker: `contradiction_detector.py`, `llm_extractor.py`, and `session_consolidator.py`.
7. At least 12 tests covering all state transitions and persistence.

**Verification commands:**
```bash
cd "/Users/lee/CC/LFI/_ Operations/memory-system-v1"
pytest tests/test_circuit_breaker.py -v 2>&1 | tail -30
python -c "
import tempfile
from src.circuit_breaker import CircuitBreaker
with tempfile.TemporaryDirectory() as d:
    db = f'{d}/test.db'
    cb = CircuitBreaker(db_path=db, failure_threshold=3, recovery_timeout=600)
    assert cb.get_state() == 'closed'
    def failing_fn(): raise Exception('API down')
    fallback = lambda: 'fallback_value'
    for i in range(3):
        result = cb.call(failing_fn, fallback=fallback)
    assert cb.get_state() == 'open', f'Expected open, got {cb.get_state()}'
    result = cb.call(failing_fn, fallback=fallback)
    assert result == 'fallback_value', f'Expected fallback, got {result}'
    print('CIRCUIT BREAKER OK')
"
```

**Full prompt:**

You are adding a circuit breaker to a Python memory system. The codebase is at `/Users/lee/CC/LFI/_ Operations/memory-system-v1/`.

Read these files first:
- `src/intelligence_db.py` — how to add tables and store state
- `src/contradiction_detector.py` — first LLM call site to wrap
- `src/llm_extractor.py` — second LLM call site to wrap
- `src/session_consolidator.py` — third LLM call site to wrap

**What to implement:**

1. Create `src/circuit_breaker.py` with a `CircuitBreaker` class:

```python
class CircuitBreaker:
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery

    def __init__(
        self,
        name: str = "default",
        db_path: Optional[str] = None,
        failure_threshold: int = 5,
        recovery_timeout: int = 600  # 10 minutes in seconds
    ): ...

    def call(self, fn: Callable, fallback: Callable = None, *args, **kwargs) -> Any:
        """
        Call fn() through the circuit breaker.
        - If CLOSED: call fn(), record result
        - If OPEN: check if recovery_timeout elapsed; if yes, transition to HALF_OPEN
        - If HALF_OPEN: attempt one call; close on success, reopen on failure
        - If circuit is OPEN and timeout not elapsed: return fallback() or None
        """
        ...

    def get_state(self) -> str: ...
    def get_stats(self) -> Dict: ...
    def reset(self): ...  # Force close (for testing/admin)
```

2. Circuit state storage in intelligence.db: Add a `circuit_breaker_state` table:
```sql
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    name TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'closed',
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_at INTEGER,
    opened_at INTEGER,
    updated_at INTEGER NOT NULL
);
```
Use `intelligence_db.py`'s `get_db()` or `IntelligenceDB` pattern for the connection. State must persist across process restarts.

3. Wrap LLM calls in these files (add a module-level `_circuit_breaker = CircuitBreaker(name="{module}")` and wrap each API call):
   - `contradiction_detector.py`: wrap the Claude/LLM call; fallback returns `None` (no contradiction detected)
   - `llm_extractor.py`: wrap the extraction call; fallback returns `[]` (no memories extracted)
   - `session_consolidator.py`: wrap any Claude API calls; fallback returns `None` (skip consolidation)

4. Create `tests/test_circuit_breaker.py` with at least 12 tests:
   - Initial state is closed
   - Successful calls don't increment failure count
   - Failure increments count
   - After threshold failures, state becomes open
   - Open state returns fallback without calling fn
   - Open state does NOT return fallback if recovery_timeout elapsed (transitions to half-open)
   - Half-open: success closes circuit
   - Half-open: failure reopens circuit
   - State persists across CircuitBreaker instance restarts (same db_path)
   - reset() forces closed state
   - get_stats() returns correct counts
   - Fallback=None returns None when circuit is open

5. Run `pytest tests/ -v --tb=short` and fix all failures.

---

## Spec 5: Memory decay with archival action

**Goal:** Move stale memories to an archive directory during nightly maintenance so they stop polluting active search results.

**Constraints:**
- Branch: `feature/memory-decay-archival` (from `main`)
- Protected files: Do not delete any memories — only move them to `archived/`. Do not change the decay math in `importance_engine.py`.
- Max iterations: 8

**Success criteria:**
1. After `MaintenanceRunner.run()`, memories with `importance < 0.2` are moved from active memory to `{memory_dir}/archived/`.
2. Archived memories are not returned by `MemoryTSClient.list()` by default.
3. `MemoryTSClient.list(include_archived=True)` returns both active and archived memories.
4. An archive manifest file is written to `{memory_dir}/archived/YYYY-MM-DD-archive.md` listing what was archived and why.
5. `DecayPredictor.get_memories_becoming_stale()` results with `predicted_stale_at < now` trigger archival in the maintenance run.
6. At least 10 tests covering: archival threshold, manifest creation, `list()` exclusion, `list(include_archived=True)`, decay predictor integration, nothing archived when all above threshold, idempotent (archived file already in archived/ doesn't get re-archived).

**Verification commands:**
```bash
cd "/Users/lee/CC/LFI/_ Operations/memory-system-v1"
pytest tests/test_memory_decay_archival.py -v 2>&1 | tail -20
python -c "
import tempfile, os
from src.memory_ts_client import MemoryTSClient
from src.daily_memory_maintenance import MaintenanceRunner
with tempfile.TemporaryDirectory() as d:
    client = MemoryTSClient(memory_dir=d)
    # Add a memory and force low importance
    mid = client.add('stale old memory')
    client.update(mid, {'importance': 0.1})
    # Run maintenance
    runner = MaintenanceRunner(memory_dir=d)
    result = runner.run()
    # Verify archived
    active = client.list()
    assert mid not in [m.id for m in active], 'Stale memory still in active list'
    archived = client.list(include_archived=True)
    assert mid in [m.id for m in archived], 'Stale memory not in archived list'
    assert os.path.exists(os.path.join(d, 'archived')), 'archived/ dir not created'
    print('DECAY ARCHIVAL OK')
"
```

**Full prompt:**

You are implementing memory decay archival for a Python memory system. The codebase is at `/Users/lee/CC/LFI/_ Operations/memory-system-v1/`.

Read these files first:
- `src/daily_memory_maintenance.py` — the maintenance runner to extend
- `src/memory_ts_client.py` — the memory client to extend
- `src/importance_engine.py` — how importance scores work (do not modify this)
- `src/wild/decay_predictor.py` — the decay prediction module to integrate

**What to implement:**

1. Extend `MemoryTSClient`:
   - Add `archived: bool = False` to the memory data model. When a memory is archived, it's moved from `{memory_dir}/{id}.md` to `{memory_dir}/archived/{id}.md` and its YAML gets `archived: true`.
   - Add `archive(memory_id: str, reason: str) -> bool` method that moves the file and updates YAML.
   - Update `list()` to accept `include_archived: bool = False` parameter. By default, skip files in `archived/` subdirectory. With `include_archived=True`, include them.
   - `get(memory_id)` should still work for archived memories (check both locations).

2. Extend `MaintenanceRunner.run()`:
   - After applying decay scores, query all memories where `importance < 0.2`.
   - Also query `DecayPredictor.get_memories_becoming_stale(days_ahead=0)` — memories already past predicted stale date.
   - Union the two lists (dedup by memory_id).
   - For each memory to archive: call `client.archive(memory_id, reason="low_importance" or "predicted_stale")`.
   - Create a manifest file at `{memory_dir}/archived/YYYY-MM-DD-archive.md` listing: archived_at, each archived memory ID, reason, and original importance score.
   - Return updated `MaintenanceResult` with `archived_count` field.

3. Create `tests/test_memory_decay_archival.py` with at least 10 tests:
   - Memory with importance=0.1 gets archived
   - Memory with importance=0.3 does NOT get archived (above threshold)
   - Archived memory excluded from `list()` default
   - Archived memory included in `list(include_archived=True)`
   - `get(archived_id)` still works
   - Manifest file created after archival
   - Manifest contains correct content (IDs, reasons)
   - Memory past predicted stale date gets archived
   - Idempotent: calling archive() on already-archived memory doesn't error
   - No memories below threshold = no archived/ dir created (or empty manifest)

4. Run `pytest tests/ -v --tb=short` and fix all failures.

**Constraints:**
- Do NOT delete any memory files. Only move them.
- Do NOT change `importance_engine.py`.
- The `archived/` subdirectory is created lazily (only when first archival happens).
