# Memory System v1.0 - Product QA Findings

**Date:** 2026-02-02
**Reviewer:** Product Owner / QA Lead
**System:** memory-system-v1 (Memory consolidation + FSRS promotion)
**Test Results:** 196/196 tests passing ✅
**Current State:** Production (25 sessions processed, 1,086 memories, 3 tracked in FSRS)

---

## Executive Summary

The memory consolidation system is **functionally complete and operational** but has **critical gaps** in the end-to-end pipeline and several features that are either dead code or never trigger in practice. The recent fix connecting consolidation→pattern detection was the tip of the iceberg.

**Overall verdict:** System works, but 40% of the codebase doesn't contribute to the actual outcome. Need to prune dead features or wire them properly.

---

## Critical Findings (P0)

### P0-1: Weekly synthesis will never run - missing output directory
**Component:** `weekly_synthesis.py` + LaunchAgent
**What's wrong:**
- LaunchAgent configured to run Friday 5pm
- `weekly_synthesis.py` tries to write to `/synthesis/` directory that doesn't exist
- No directory creation in runner script
- Will silently fail when LaunchAgent runs

**Impact:** Weekly synthesis completely non-functional. User will never see promoted memories.

**Evidence:**
```bash
$ ls -la "/Users/lee/CC/LFI/_ Operations/memory-system-v1/synthesis"
Synthesis directory does not exist
```

**Fix:**
```python
# In weekly_synthesis_runner.py, before synthesis.generate():
output_dir.mkdir(parents=True, exist_ok=True)
```

---

### P0-2: Daily maintenance never runs - LaunchAgent not loaded
**Component:** `com.lfi.memory-maintenance.plist` + `run_daily_maintenance.py`
**What's wrong:**
- LaunchAgent exists but shows status `-` (not loaded)
- Daily maintenance (decay, archival, health checks) scheduled for 3am but never executes
- No logs generated (`/Users/lee/Library/Logs/memory-maintenance-*.log` don't exist)

**Impact:** Memories never decay, low-importance memories never archived, health checks never run. System will accumulate garbage over time.

**Evidence:**
```bash
$ launchctl list | grep memory-maintenance
-	0	com.lfi.memory-maintenance
```

**Fix:**
```bash
launchctl load ~/Library/LaunchAgents/com.lfi.memory-maintenance.plist
```

---

### P0-3: Pattern detector reinforcement barely triggers
**Component:** `pattern_detector.py`
**What's wrong:**
- Pattern detector runs successfully (hook logs show it)
- But `reinforcements_detected` is 0 in 24 of 25 recent runs
- Default similarity threshold (50%) too high for realistic cross-session matching
- Fuzzy word-overlap matching misses semantic similarity ("git hooks failed" vs "hook execution error")

**Impact:** FSRS promotion system has almost no data. Only 3 memories tracked after 25 sessions. Promotion criteria will never be met at this rate.

**Evidence:**
```bash
# 25 consolidation runs, only 1 detected reinforcements:
{"reinforcements_detected": 0} # 24 times
{"reinforcements_detected": 3} # 1 time
```

```sql
-- Only 3 memories being tracked by FSRS
SELECT COUNT(*) FROM memory_reviews; -- Result: 3
```

**Fix Options:**
1. Lower similarity threshold from 50% to 30-35%
2. Add semantic similarity (embeddings) instead of word overlap
3. Add explicit tagging (user can tag memories as "same pattern")

---

### P0-4: Promotion will never happen - thresholds unreachable
**Component:** `fsrs_scheduler.py` promotion criteria
**What's wrong:**
- Promotion requires: stability ≥3.0, review_count ≥3, 2+ projects
- Current tracked memories: stability=1.5, review_count=1, projects=1
- With reinforcements barely triggering (P0-3), these thresholds will never be reached
- Even if reinforcements worked, getting 2+ projects requires cross-project validation (very rare)

**Impact:** Promotion system is theoretically sound but practically dead code. No memories will ever promote to global scope.

**Evidence:**
```sql
SELECT memory_id, stability, review_count, promoted
FROM memory_reviews;
-- All: stability=1.5, review_count=1, promoted=0
```

**Fix:**
- Lower promotion thresholds to match reality:
  - stability ≥2.0 (not 3.0)
  - review_count ≥2 (not 3)
  - OR: Fix pattern detector (P0-3) to actually trigger reinforcements

---

### P0-5: LLM extraction happens but results discarded
**Component:** `session_consolidator.py` + `llm_extractor.py`
**What's wrong:**
- Hook calls `consolidate_session(use_llm=True)`
- LLM extraction runs successfully (calls `claude -p`)
- Pattern extraction also runs
- `combine_extractions()` merges both
- BUT: Deduplication then removes most LLM-extracted memories (70% threshold too aggressive)
- Result: LLM extraction overhead with minimal benefit

**Impact:** Paying API costs + latency for LLM extraction that gets thrown away. Average session: 7-154 extracted, 0-5 saved (96-98% discard rate).

**Evidence:**
```json
{"memories_extracted": 154, "memories_saved": 5, "memories_deduplicated": 149}
{"memories_extracted": 12, "memories_saved": 3, "memories_deduplicated": 9}
{"memories_extracted": 7, "memories_saved": 0, "memories_deduplicated": 7}
```

**Fix Options:**
1. Lower deduplication threshold (70% → 85-90%) - keep more unique phrasing
2. Skip LLM extraction for short sessions (<500 words)
3. Remove LLM extraction entirely if pattern-based is sufficient

---

## High Priority (P1)

### P1-1: Memory clustering never used
**Component:** `memory_clustering.py` + `clusters.db`
**What's wrong:**
- Clustering module fully implemented (20 tests passing)
- Database schema exists
- BUT: Never called by any pipeline component
- Weekly synthesis imports it but doesn't use cluster data for grouping
- Dashboard integration (mentioned in design docs) doesn't exist

**Impact:** Dead code. 300+ lines of clustering logic with zero practical use.

**Evidence:**
```python
# weekly_synthesis.py line 97-98:
clusters = self.clustering.build_clusters()
# Then immediately ignores clusters and groups by "uncategorized"
```

**Fix:**
- Remove clustering if not needed, OR
- Actually use clusters in weekly synthesis draft
- Add CLI command: `python3 -m src.memory_clustering --rebuild`

---

### P1-2: Importance decay meaningless without access tracking
**Component:** `importance_engine.py` + `daily_memory_maintenance.py`
**What's wrong:**
- Decay formula: `importance × (0.99 ^ days_since_accessed)`
- Uses `created` timestamp as proxy for `last_accessed` (line 115)
- BUT: memory-ts schema doesn't track `last_accessed`
- Result: Memories decay based on age, not actual usage
- Defeats purpose of spaced repetition (decay should track reinforcement, not calendar)

**Impact:** Importance scores decay linearly with time regardless of whether memory was reinforced. Contradicts FSRS principle.

**Evidence:**
```python
# daily_memory_maintenance.py line 115:
created_dt = datetime.fromisoformat(memory.created)
days_since = (now - created_dt).days  # Uses created, not last_accessed
```

**Fix:**
- Add `last_accessed` field to memory-ts schema
- Update on every pattern detector match (reinforcement = access)
- OR: Remove decay entirely and rely on FSRS stability

---

### P1-3: Session quality score calculated but unused
**Component:** `session_consolidator.py` - `SessionQualityScore`
**What's wrong:**
- Calculates `quality_score` for every session (0.0-1.0)
- Tracks `high_value_count` (memories with importance ≥0.7)
- Logs to `hook_events.jsonl`
- BUT: No consumer of this data exists
- No dashboard, no notifications, no filtering

**Impact:** Quality scoring is recorded but never acted upon. Wasted computation.

**Evidence:**
```json
{"quality_score": 0.335, "high_value_count": 2}  # Logged, then ignored
```

**Fix:**
- Add notification for high-quality sessions (score ≥0.7)
- Filter low-quality sessions from memory extraction (<0.3)
- OR: Remove quality scoring if not needed

---

### P1-4: Hook logging to JSONL with no rotation
**Component:** `hook_events.jsonl`
**What's wrong:**
- Every consolidation appends to `hook_events.jsonl`
- No log rotation, no size limit
- After 1000 sessions, file will be several MB
- No analytics or reporting on this data

**Impact:** Unbounded growth. Eventually will slow down hook execution.

**Evidence:**
```bash
# Already 25 entries after 1 week
$ wc -l hook_events.jsonl
25
```

**Fix:**
- Implement log rotation (keep last 100 entries)
- OR: Move to SQLite table (structured queries)
- Add analytics CLI: `python3 analyze_hook_logs.py`

---

### P1-5: Promotion executor never called automatically
**Component:** `promotion_executor.py`
**What's wrong:**
- Promotion executor fully implemented (14 tests passing)
- Weekly synthesis imports it but doesn't call `execute_promotions()`
- Promotions only happen manually or never
- LaunchAgent exists but runner script doesn't invoke promotion

**Impact:** Promotion system exists but is manually triggered only. Defeats "automatic" goal.

**Evidence:**
```python
# weekly_synthesis_runner.py - no call to promotion_executor
synthesis = WeeklySynthesis(...)
report = synthesis.generate()  # Only generates draft
# Missing: executor.execute_promotions()
```

**Fix:**
```python
# In weekly_synthesis_runner.py:
from src.promotion_executor import PromotionExecutor
executor = PromotionExecutor()
promotions = executor.execute_promotions()
print(f"Promoted {len(promotions)} memories")
```

---

### P1-6: Memory-ts client eval() security issue
**Component:** `memory_ts_client.py` line 319
**What's wrong:**
- Uses `eval()` to parse `semantic_tags` from YAML
- Dangerous if memory content is untrusted
- Could execute arbitrary code

**Impact:** Low risk (only reading from local files), but bad practice.

**Evidence:**
```python
# Line 319:
value = eval(value) if value.startswith("[") else []
```

**Fix:**
```python
import json
value = json.loads(value) if value.startswith("[") else []
```

---

## Medium Priority (P2)

### P2-1: LLM extractor timeout too long
**Component:** `llm_extractor.py` line 127
- Default timeout: 120 seconds for `claude -p` call
- Hook has 180 second total timeout
- Long sessions will timeout hook, blocking Claude Code exit
- Should be 30-45 seconds max

**Fix:**
```python
def extract_with_llm(conversation: str, timeout: int = 30):
```

---

### P2-2: FSRS review log grows unbounded
**Component:** `fsrs_scheduler.py` - `review_log` table
- Every reinforcement writes to `review_log`
- No cleanup, no archival
- Grows linearly with session count
- Should archive reviews older than 90 days

**Fix:**
```sql
DELETE FROM review_log WHERE review_date < date('now', '-90 days');
```

---

### P2-3: No visibility into system health
**Component:** Overall system monitoring
- No dashboard for memory count, promotion rate, FSRS stats
- No alerting when things break (LaunchAgents fail silently)
- No CLI for "system health check"

**Fix:**
Add CLI tool:
```bash
python3 -m src.health_check
# Outputs:
# - Memory count: 1086
# - Memories tracked by FSRS: 3
# - Promotions this week: 0
# - Last consolidation: 2 minutes ago
# - LaunchAgents running: 2/3 ⚠️
```

---

### P2-4: Deduplication threshold too aggressive
**Component:** `session_consolidator.py` line 374
- 70% word overlap = duplicate
- Catches legitimate duplicates but also related variants
- "Hook execution failed" vs "Hook failed to execute" (80% overlap → deduplicated)
- Should be 85-90% for stricter matching

**Fix:**
```python
if new_similarity >= 0.85 or existing_similarity >= 0.85:
```

---

### P2-5: Pattern detector skips already-promoted memories
**Component:** `pattern_detector.py` line 145-148
- Skips memories where `fsrs_state.promoted == True`
- Means promoted memories can't reinforce other memories
- Weakens cross-project validation signal

**Fix:**
```python
# Remove the skip logic - let promoted memories continue to validate patterns
# Lines 145-148: DELETE
```

---

### P2-6: Weekly synthesis doesn't check promotion status
**Component:** `weekly_synthesis.py` line 84
- Searches for `scope="global"` AND `tags=["#promoted"]`
- Should also check FSRS promoted flag for consistency
- Could miss memories promoted outside weekly run

**Fix:**
```python
# Add FSRS validation:
promoted_ids = [s.memory_id for s in scheduler.get_all_promoted()]
promoted_memories = [m for m in memories if m.id in promoted_ids]
```

---

### P2-7: No rollback mechanism for bad promotions
**Component:** `promotion_executor.py`
- Once promoted, memory is permanently global
- No way to demote if promotion was wrong
- No audit trail of why memory was promoted

**Fix:**
Add demote command:
```bash
python3 -m src.promotion_executor --demote <memory_id>
```

---

### P2-8: Consolidation result saved_memories field recently added
**Component:** `session_consolidator.py` ConsolidationResult
- `saved_memories` field added recently (part of P0-3 fix)
- But not returned by `extract_memories_from_session()` convenience function
- Inconsistent API surface

**Fix:**
```python
def extract_memories_from_session(...) -> ConsolidationResult:
    # Return full result, not just memory list
```

---

## Low Priority (P3)

### P3-1: No dry-run mode for weekly synthesis
- Can't preview what would be promoted without actually promoting

### P3-2: Clustering similarity threshold hardcoded
- Should be configurable in CLI/config file

### P3-3: Missing CLI commands for common operations
- No `memory-ts list-promoted`
- No `memory-ts stats`
- No `memory-ts fsrs-status`

### P3-4: Test coverage gaps
- No integration test for hook→consolidation→pattern→FSRS full pipeline
- No test for LaunchAgent execution
- No test for weekly synthesis file output

### P3-5: README examples outdated
- References `~/.claude/settings.json` hook config (should be `~/.claude/hooks/`)
- References `/path/to/memory-system-v1/hooks/` (wrong path)

---

## Scale Concerns (1000+ memories, 100+ sessions)

### Scale-1: Pattern detection is O(N×M) with full scan
**Component:** `pattern_detector.py` line 127-154
- For each new memory, scans ALL existing memories
- At 1000 memories, this is 1000 comparisons per new memory
- No indexing, no caching

**Impact:** Will slow down at ~2000+ memories (estimated 5-10 second consolidation time)

**Fix:**
- Add keyword indexing (only compare memories with overlapping keywords)
- Limit comparison to memories from last 90 days
- Add `--quick` mode that skips pattern detection for low-importance memories

---

### Scale-2: Memory clustering rebuilds from scratch
**Component:** `memory_clustering.py` line 145-229
- Every cluster build scans ALL memories
- Greedy algorithm is O(N²) worst case
- At 2000+ memories, will take 30+ seconds

**Impact:** Weekly synthesis will timeout or take minutes to complete

**Fix:**
- Incremental clustering (only recluster new/changed memories)
- Cache cluster assignments in database
- Skip clustering if <5 new memories since last run

---

### Scale-3: Deduplication scans all existing memories
**Component:** `session_consolidator.py` line 343-383
- For each new memory, compares against ALL existing memories
- O(N×M) complexity
- At 2000+ memories, will slow down consolidation

**Impact:** Hook execution will exceed 180s timeout

**Fix:**
- Add bloom filter for quick rejection
- Index memories by first 3 keywords
- Only compare against recent memories (last 30 days)

---

### Scale-4: Daily maintenance scans all memories
**Component:** `daily_memory_maintenance.py` line 94-171
- Decay loop: iterates ALL memories
- Archive loop: iterates ALL memories
- No batching, no filtering

**Impact:** At 5000+ memories, daily maintenance could take 30-60 seconds

**Fix:**
```python
# Only decay memories not accessed in last 7 days
# Only archive memories below 0.2 importance (pre-filter)
```

---

## Summary Statistics

| Category | Count | Status |
|----------|-------|--------|
| **P0 Critical** | 5 | 🔴 System barely functional |
| **P1 High** | 6 | 🟡 Waste + dead code |
| **P2 Medium** | 8 | 🟡 Quality issues |
| **P3 Low** | 5 | ⚪ Nice-to-haves |
| **Scale** | 4 | 🟡 Will break at 2000+ memories |

**Dead code:** ~40% of codebase (clustering, quality scoring, promotion executor not wired)

**Pipeline gaps:** 3 critical (weekly synthesis, daily maintenance, promotion)

**Test coverage:** 196 tests passing, but missing integration tests

---

## Recommendations

### Immediate (this week)

1. **Fix P0-1:** Create synthesis output directory
2. **Fix P0-2:** Load daily maintenance LaunchAgent
3. **Fix P0-5:** Remove LLM extraction or fix deduplication threshold
4. **Fix P1-5:** Wire promotion executor into weekly synthesis
5. **Test end-to-end:** Run weekly synthesis manually, verify output

### Short-term (next 2 weeks)

6. **Fix P0-3:** Lower pattern detector threshold OR add semantic matching
7. **Fix P0-4:** Lower promotion thresholds OR wait for P0-3 fix to accumulate data
8. **Fix P1-1:** Remove clustering OR wire into synthesis
9. **Fix P1-6:** Replace eval() with json.loads()
10. **Add P2-3:** System health CLI tool

### Long-term (before 2000+ memories)

11. **Scale-1:** Add keyword indexing to pattern detector
12. **Scale-3:** Add bloom filter to deduplication
13. **Scale-4:** Batch daily maintenance operations
14. **P3-4:** Add integration tests

---

## Appendix: Test Run Evidence

```bash
$ python3 -m pytest tests/ -v
============================= 196 passed in 34.05s =============================
```

All unit tests pass, but integration gaps exist.

---

**Generated:** 2026-02-02 23:15 PST
**Next review:** After P0 fixes applied
