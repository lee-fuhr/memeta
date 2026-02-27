# Roadmap

Where Total Rekall has been, where it is, and where it's going.

---

## Shipped

### v0.19.1 — Code quality pass (Feb 2026)
Schema conflict resolution, connection leak fixes, TTL cache for API, false positive reduction.

### v0.19.0 — Mega sprint (Feb 2026)
29 features in two batches. 952 new tests.
- **Batch 1** (19 system features) — compaction triggers, frustration archaeology, memory interview, energy-aware loading, cross-project sharing, persona filter, memory compressor, health scoring, event stream, access tracker, entity extractor, context budget optimizer, temporal knowledge graph, embedding maintenance, unified API, confidence persistence, relevance explanation, self-test diagnostics, intelligence DB pool
- **Batch 2** (10 cognitive psychology) — generational GC, directed forgetting, encoding depth, prospective triggers, content hash dedup, memory PageRank, retrieval-induced forgetting, emotional tagging, schema classifier, reference counter

### v0.18.0 — Build sprint (Feb 2026)
5 features bridging intelligence and automation layers.

### v0.17.0 — Intelligence layer (Feb 2026)
The "brain stem" that wires all features into a coherent system.
- **FAISS vector store** — indexed similarity search replacing brute-force cosine
- **Intelligence orchestrator** — synthesizes signals from dream synthesis, momentum, energy, regret, and frustration into a prioritized daily briefing
- **Cluster-based morning briefing** — surfaces cluster summaries and divergence signals
- **Cross-client pattern transfer** — consent-tagged memories generate transfer hypotheses across projects
- **Decision regret loop** — real-time warning before repeating regretted decisions

### v0.16.0 — Dashboard UX + freshness (Feb 2026)
Making the dashboard actually useful.
- **Search with explanation** — match reasons + highlighted snippets
- **Memory freshness indicators** — staleness visuals with filtering
- **Session replay** — click session → view transcript + linked memories
- **Memory freshness review cycle** — weekly scan/refresh/archive with notifications
- **GitHub Actions CI** — pytest on push/PR, Python 3.11–3.13 matrix

### v0.15.0 — Stability (Feb 2026)
- Fixed consolidation hook (broken since Feb 12)
- Added Pushover notifications on memory saves

### v0.14.0 — Circuit breaker + rename (Feb 2026)
- **Circuit breaker** for LLM calls — 3-failure threshold, auto-recovery
- Renamed project to Total Rekall

### v0.13.0 — Dashboard (Feb 2026)
- Full Flask dashboard: overview, memories, sessions, knowledge map
- Memory detail modals, JSON/CSV export
- LaunchAgent auto-start

### v0.8.0–v0.12.0 — Foundation (Feb 2026)
- sys.path cleanup (71 files)
- Config centralization
- Search delegation and optimization
- Dream mode O(n²) fix
- 1,085 tests baseline

### v0.1.0–v0.7.0 — Initial build (Feb 2026)
- 58 features across foundation, intelligence, autonomous, and wild layers
- Hybrid search (70% semantic + 30% BM25)
- FSRS-6 spaced repetition
- Dream mode synthesis
- Frustration detection
- Full test suite

---

## Phase 4: Self-improving skills + deeper lifecycle (next)

[View milestone →](https://github.com/lee-fuhr/total-rekall/milestone/4)

- Skill self-improvement — outcome tracking, learning extraction, SKILL.md refinement proposals
- Skill lifecycle maturation — decay, discovery, health monitoring
- Memory consolidation quality tracking — which extractions are actually useful
- Automated SKILL.md updates from accumulated learnings

## Phase 5: Community + packaging

[View milestone →](https://github.com/lee-fuhr/total-rekall/milestone/5)

- PyPI packaging
- Memory relationship graph visualization
- Memory-as-training-data export
- Search backend consolidation
- External integrations (Slack, Notion, email, calendar)

---

## Design principles

1. **Absorb every technique that works** — if it improves memory quality, it goes in
2. **Make them compound** — features feed each other in a loop, not a list
3. **Coexist additively** — new features layer on top, nothing gets replaced
4. **Predict and preempt** — build what the community will need before they ask
