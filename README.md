# Memory system v1.0

**Project:** Unified AI memory system with background consolidation + FSRS-6 promotion
**Status:** Phase 1 Complete → Ready for Phase 2
**Started:** 2026-02-01 19:50 PST
**Phase 1 completed:** 2026-02-02 13:00 PST
**Timeline:** 15 hours total (deferred capability evolution to v1.5)

---

## What this is

Three integrated systems that work together:

1. **Background consolidation** - Auto-extract memories from Claude Code sessions
2. **FSRS-6 learnings promotion** - Cross-project validation before promoting to master docs
3. **Memory clustering** - Theme detection to accelerate pattern recognition

**Key innovation:** Eliminates vestigial functionality by using memory-ts as single source of truth.

---

## How it all works together

Each piece makes the others more valuable. Here's the virtuous cycle:

**The core loop:**
```
Session work generates memories
    ↓
Background consolidation auto-extracts to memory-ts
    ↓
Memory clustering groups similar learnings across projects
    ↓
FSRS-6 detects cross-project patterns (2+ validations)
    ↓
Auto-promotes to master docs (universal-learnings, emma-stratton, etc.)
    ↓
Master docs inform future sessions (via SessionStart hook)
    ↓
Cycle repeats, system gets smarter
```

**Compound benefits over time:**
- **Week 1:** Better memory capture (no manual work)
- **Week 4:** Clusters start forming (theme detection)
- **Week 12:** First patterns promoted (validated learnings)
- **Week 24:** Master docs significantly improved (compound learning)

### Enhancement synergies

**Session quality score ↔ Background consolidation:**
- Consolidation counts high-importance memories (≥0.7)
- Quality score creates feedback: "This session generated 3 learnings"
- Result: Learn what activities produce valuable insights

**Memory clustering ↔ FSRS-6 promotion:**
- Clustering groups similar memories across projects
- Cluster membership = strong promotion signal
- Result: Patterns promoted 3x faster with less manual review

**Background consolidation ↔ Memory clustering:**
- More memories = better clustering accuracy
- Better clusters = better importance scoring context
- Result: System intelligence compounds

**FSRS-6 ↔ Memory-ts scope promotion:**
- Promotes proven patterns within memory-ts (scope: project → scope: global)
- Adds #promoted tag for human review
- Result: Validated learnings surface for manual synthesis into master docs

**Master docs ↔ Sessions:**
- MESSAGING-FRAMEWORK.md, VOICE-BANK.md feed SessionStart hook
- **Automated weekly synthesis:**
  - Friday 5pm: Query #promoted learnings
  - Auto-generate draft updates for each master doc
  - Lee reviews/approves/edits (5-10 min)
- Result: Compound improvement via automated prompting + human curation

### No vestigial functionality

Every component is load-bearing:
- **Background consolidation:** Capture (no manual work)
- **Importance scoring:** Filter (surface what matters)
- **Memory clustering:** Connect (find themes)
- **Session quality:** Feedback (understand what works)
- **FSRS-6:** Validate (2+ projects before promoting)
- **Master docs:** Apply (learnings inform future work)

Remove any one piece and the system breaks. This is tight design.

---

## Project structure

```
memory-system-v1/
├── README.md                           # This file
├── STATUS.md                           # Real-time progress tracking
├── memory-product-design.md            # Product vision (QA validated)
├── memory-extensions-architecture.md   # Technical architecture v2.1
├── clawhub-skills-patterns.md          # Extracted patterns from ClawHub
├── implementation-roadmap.md           # Original implementation plan
├── EXECUTIVE-SUMMARY.md                # One-page overview
├── architecture-revision-summary.md    # Architecture evolution notes
│
└── QA/                                 # QA swarm results
    └── product-design/
        ├── QUICK-REFERENCE.md          # One-page summary
        ├── QA-SUMMARY.md               # Executive findings
        ├── memory-product-design-FIXES.md
        └── product/
            ├── iteration-1.md          # 40 agents, 10 issues found
            └── iteration-2.md          # 40 agents, CLEAN status
```

---

## Product vision

**Before (manual):**
1. Notice pattern in session
2. Manually add to learnings-queue.md
3. Wait weeks/months
4. Manually review queue
5. Manually promote to universal-learnings.md
6. Manually update Emma Stratton / master docs

**After (automatic):**
1. Pattern happens in session → Auto-captured to memory-ts (scope: project)
2. Pattern reconfirmed in another project → FSRS-6 tracks
3. Pattern validated 2+ projects → Auto-promoted within memory-ts (scope: global, #promoted)
4. Lee sees: "Promoted 3 learnings this week" notification
5. Periodic review: Synthesize #promoted learnings into master docs (MESSAGING-FRAMEWORK.md, VOICE-BANK.md)

---

## Architecture (simplified)

```
┌─────────────────────────────────────────────────────────────────┐
│                         MEMORY-TS                                │
│                    (Single Source of Truth)                      │
└─────────────────────────────────────────────────────────────────┘
         ▲                      ▲                      ▲
         │                      │                      │
    ┌────┴────┐           ┌─────┴─────┐          ┌────┴─────┐
    │ CAPTURE │           │  PROMOTE  │          │ CLUSTER  │
    │ System 1│           │  System 2 │          │ Enhancement│
    └─────────┘           └───────────┘          └──────────┘
         │                      │                      │
    Auto-extract          FSRS-6 scheduler      Theme detection
    from sessions         promotes learnings    accelerates validation
```

---

## Shared infrastructure

**No duplication - one implementation used by all:**

- `importance_engine.py` - Scoring (0.0-1.0), decay, reinforcement
- `memory_ts_client.py` - Unified API wrapper
- `daily_memory_maintenance.py` - 3 AM cron job

**Tag taxonomy:**
- `#learning` - Pattern worth tracking
- `#important` - High importance (0.8+)
- `#promoted` - Validated across 2+ projects (ready for master doc synthesis)

**Scope values:**
- `scope: project` - Project-specific learning
- `scope: global` - Cross-project validated (FSRS-6 promoted)

---

## Roadmap

### ✅ Phase 0: Foundation audit (1 day)
- Validated memory-ts operational (2,319 memories, v0.3.8)
- Validated universal-learnings.md actively maintained
- Installed TDD, verification, QA skills

### ✅ Phase 0.1: Product design (2 hours)
- Created product design document
- QA swarm iteration 1: 10 issues found
- Applied all fixes (error handling, data schemas)
- QA swarm iteration 2: CLEAN status achieved

### ✅ Phase 0.5: Legacy migration (15 minutes!)
- Migrated 103 learnings from 17 source files to memory-ts
- Memory count: 590 → 678 (+88 net)
- Archived all legacy files (learnings-queue.md project staging files)
- 100% success rate, zero errors
- **Status:** Complete (6x faster than estimated)

### ⚪ Phase 1: Background consolidation (2-3 days)
- Session analyzer with LLM extraction
- Importance scoring + trigger word detection
- Deduplication against existing memories
- SessionEnd hook + daily cron
- **Enhancement:** Session quality score (4-6 hours)

### ⚪ Phase 2: FSRS-6 promotion (3-4 days)
- Pattern detector (cross-project reconfirmation)
- FSRS-6 scheduler (review intervals, promotion scoring)
- Promotion executor (updates memory-ts: scope → global, adds #promoted tag)
- **Weekly synthesis automation:**
  - LaunchAgent: Friday 5pm notification
  - Script queries `scope:global AND #promoted`
  - Auto-generates draft synthesis for each master doc
  - Prompts Lee to review/approve/edit
- **Enhancement:** Memory clustering/themes (6-8 hours)

### ⚪ Phase 3: Polish + packaging (1-2 days)
- Documentation (README, setup guide, architecture doc)
- Package for memory-ts ecosystem
- Submit to GitHub
- CLI tools for manual operations

**Total:** 15 hours (was 20, deferred capability evolution to v1.5)

---

## Deferred to v1.5

- Capability evolution (A/B testing agent prompts)
- Dashboard (web UI for memory browsing)

---

## Success metrics

**Memory capture:**
- 80%+ session memory extraction rate
- <50ms capture time (p95 latency)
- <5% false positives (irrelevant memories)

**Learnings promotion:**
- 90%+ promotion accuracy (no bad patterns)
- 2+ cross-project validation
- <10% manual overrides needed

**Session quality (enhancement):**
- Quality scores visible for all sessions
- High-value sessions (3+ learnings) generate notifications

**Memory clustering (enhancement):**
- Clusters auto-detect themes
- Cross-project validation accelerated by cluster membership

---

## Key decisions (finalized)

**Q1: Defer Phase 3 to v1.5?**
✅ YES - Systems 1+2 deliver 80% of value, lower risk

**Q2: Promotion approval workflow?**
✅ Automatic - Trust 0.75+ threshold

**Q3: Dashboard in v1.0 or v1.1?**
✅ v1.1 - Defer to focus on core systems

**Q4: Master docs targets correct?**
✅ Yes - universal-learnings.md, emma-stratton.md, smart-writing-guidelines.md

**Q5: Performance targets?**
✅ Keep specific - <20ms search, <50ms capture (p95 latency)

---

## QA validation

**Iteration 1:**
- 40 agents (2 Directors, 10 Seniors, 28 Juniors)
- 10 issues found (2 HIGH, 5 MEDIUM, 3 LOW)
- Quality score: 81%
- Verdict: NOT READY (2 blockers)

**Iteration 2:**
- Applied all fixes (error handling, data schemas, scope decisions)
- 40 agents re-review
- 0 issues found
- Quality score: 100%
- Verdict: CLEAN - Ready for implementation

---

## Files to track

**Real-time progress:** `STATUS.md` (updated hourly during autonomous work)
**Product design:** `memory-product-design.md` (QA validated)
**Technical architecture:** `memory-extensions-architecture.md` (v2.1)
**QA results:** `QA/product-design/QA-SUMMARY.md`

---

## Next steps

1. ✅ Product design QA validated (CLEAN)
2. ✅ Phase 0.5: Legacy migration complete
3. ⚪ Phase 1: Background consolidation (TDD approach)
4. ⚪ Phase 2: FSRS-6 promotion
5. ⚪ Phase 3: Polish + packaging
6. ⚪ Submit to memory-ts ecosystem

**Estimated completion:** 15 hours remaining

---

**Created:** 2026-02-01 19:50 PST
**QA validated:** 2026-02-02 01:15 PST (CLEAN status)
**Implementation start:** 2026-02-02 09:35 PST
