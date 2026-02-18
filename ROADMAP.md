# Roadmap

Where Total Recall has been, where it is, and where it's going.

---

## Shipped

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
- Renamed project to Total Recall

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

## In progress

Nothing actively in progress — looking for contributors.

---

## Planned

See [GitHub Issues](https://github.com/lee-fuhr/total-recall/issues) for the full list. Highlights:

**Next up:**
- Energy-aware memory loading — morning sessions get strategic memories, afternoon gets operational
- Frustration archaeology — 90-day pattern analysis, not just 20-minute detection
- Memory interview — structured 10-minute weekly review that doesn't feel like chores
- Memory relationship graph — force-directed visualization of the knowledge structure
- PyPI packaging

**On the horizon:**
- Persona-aware filtering (business vs health vs personal context)
- Memory-as-training-data export (fine-tuning dataset from graded memories)
- Search backend consolidation
- External integrations (Slack, Notion, email, calendar)

---

## Design principles

1. **Absorb every technique that works** — if it improves memory quality, it goes in
2. **Make them compound** — features feed each other in a loop, not a list
3. **Coexist additively** — new features layer on top, nothing gets replaced
4. **Predict and preempt** — build what the community will need before they ask
