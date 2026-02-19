# Ralph loop status

**Last updated:** 2026-02-19
**Status:** v0.19.0 complete — 29 features merged, 2,031 tests

---

## Previous sprint (v0.18.0) — complete

| Feature | Merged | Tests | CI |
|---------|--------|-------|-----|
| Provenance tracking | 3ce5ba3 | 992 pass (+10 new) | Pass |
| Daily episodic summaries | 5b322a7 | 1010 pass (+18 new) | Pass |
| Hybrid search unification | 972101e | 1037 pass (+27 new) | Pass |
| Circuit breaker for LLM calls | 473f219 | 1064 pass (+27 new) | Pass |
| Memory decay archival | c67fc67 | 1079 pass (+15 new) | Pass |

---

## Batch 1 merge (v0.19.0 prep) — 19 features merged to main

All branches from the previous session merged, tested, worktrees cleaned.

| Feature | Branch | Tests added | Status |
|---------|--------|-------------|--------|
| Compaction triggers | feature/compaction-triggers | 40 | Merged |
| Frustration archaeology | feature/frustration-archaeology | 23 | Merged |
| Memory interview | feature/memory-interview | 21 | Merged |
| Energy-aware loading | feature/energy-aware-loading | 23 | Merged |
| Cross-project sharing DB | feature/cross-project-sharing | 14 | Merged |
| Persona filter | feature/persona-filter | 23 | Merged |
| Memory compressor | feature/memory-compressor | 35 | Merged |
| Memory health score | feature/memory-health | 37 | Merged |
| Event stream | feature/event-stream | 25 | Merged |
| Access tracker | feature/access-tracker | 25 | Merged |
| Entity extractor | feature/entity-extractor | 33 | Merged |
| Context budget optimizer | feature/context-budget | 26 | Merged |
| Temporal knowledge graph | feature/temporal-knowledge-graph | 30 | Merged |
| Pre-computed embeddings | feature/precompute-embeddings | 15 | Merged |
| Unified MemorySystem API | feature/unified-api | 22 | Merged |
| Confidence persistence | feature/confidence-persistence | 17 | Merged |
| Relevance explanation | feature/relevance-explanation | 45 | Merged |
| Self-test diagnostics | feature/self-test | 24 | Merged |
| IntelligenceDB pool refactor | feature/intelligence-db-pool | 14 | Merged |

**Totals:** 19 features merged, 492 new tests, 1,573 total tests on main

---

## Batch 2 — cognitive psych + CS features (10 Ralphs running)

Prioritized from brainstorm of 24 features (12 cognitive psych, 12 CS).

### Tier 1 — Independent, pure Python

| # | Feature | Branch | Concept | Status |
|---|---------|--------|---------|--------|
| 1 | Generational GC | feature/generational-gc | CS: generational garbage collection | Running |
| 2 | Directed forgetting | feature/directed-forgetting | Psych: Bjork directed forgetting | Running |
| 3 | Encoding depth | feature/encoding-depth | Psych: Craik & Lockhart levels of processing | Running |
| 4 | Prospective triggers | feature/prospective-triggers | Psych: Einstein & McDaniel prospective memory | Running |
| 5 | Content dedup | feature/content-dedup | CS: content-addressable hashing | Running |

### Tier 2 — Builds on existing features

| # | Feature | Branch | Concept | Status |
|---|---------|--------|---------|--------|
| 6 | Memory PageRank | feature/memory-pagerank | CS: PageRank on relationship graph | Running |
| 7 | Retrieval forgetting | feature/retrieval-forgetting | Psych: Anderson/Bjork RIF detector | Running |
| 8 | Emotional tagging | feature/emotional-tagging | Psych: flashbulb memory, amygdala consolidation | Running |
| 9 | Schema classifier | feature/schema-classifier | Psych: Bartlett schema assimilation/accommodation | Running |
| 10 | Reference counter | feature/reference-counter | CS: reference counting for GC protection | Running |

### Merge order

**Independent (merge first, any order):**
All 10 features create new files only — no conflicts expected.

### Merge checklist per feature

- [ ] Tests pass in worktree
- [ ] Merge to main: `git merge feature/[name]`
- [ ] Run full suite from main
- [ ] Fix any regressions
- [ ] Remove worktree: `git worktree remove ../memory-system-v1-[name]`
- [ ] Delete branch: `git branch -d feature/[name]`

---

## Deferred features (future sprints)

From brainstorm, 14 features for later:

**Cognitive psychology:**
- Reconsolidation windows (Nader 2000)
- Context-dependent retrieval cues (Tulving 1973)
- Source monitoring / provenance confidence (Johnson 1993)
- Testing effect / retrieval practice (Roediger & Karpicke 2006)
- Spacing effect optimizer (Cepeda 2006)
- Chunking and memory compression (Miller 1956) — overlaps memory_compressor

**Computer science:**
- Write-ahead log for memory mutations
- Delta encoding for memory versions
- ARC (adaptive replacement) cache for search
- Community detection / Louvain algorithm
- Eventual consistency with conflict resolution
- Query expansion / pseudo-relevance feedback (Rocchio 1971)
- Memory-mapped tiered storage
- Gossip protocol for cross-project propagation
