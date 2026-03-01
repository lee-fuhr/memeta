# Roadmap

Where Memeta has been, where it is, and where it's going.

---

## Shipped

### v0.23.0 — Correction pipeline (Feb 2026)
Phase 2: When Lee corrects Claude once, the system detects it, stores it as a high-importance correction memory, reinforces it across sessions, and graduates confirmed corrections to permanent CLAUDE.md rules.
- **Correction detection** (`src/extraction_patterns.py`) — 3 pattern categories: explicit corrections, behavioral directives, frustration signals; `detect_corrections()` seam with typed classification; 1.5x importance boost (0.9 floor, 1.0 cap)
- **Correction graduation** (`src/correction_graduator.py`) — find candidates → format imperative rules → strip-and-regenerate CLAUDE.md → mark graduated; preserves previously graduated rules across runs
- **Correction reinforcement** (`src/session_consolidator.py`) — cross-session confirmation tracking; word-overlap > 0.7 matching; same-session dedup via source_session_id
- **Correction injection** (`src/memory_injector.py`) — corrections surfaced first at session start; context_type in BM25 index; max 3, sorted by importance
- **Skill-aware memory tagging** — active skills tagged on all memories as `#skill:{name}`
- **Temporal relevance on decay** — permanent memories exempt from importance decay
- **59 new tests** — 2,184 total passing

### v0.22.0 — Memory injection + hook infrastructure (Feb 2026)
Phase 1: Close the biggest open loop — memories go in at session end but nothing comes out during sessions. This release makes Memeta read-write.
- **Hook shared state** (`src/hook_state.py`) — session-scoped JSON coordination between hooks; atomic writes; probabilistic stale cleanup
- **Memory injector** (`src/memory_injector.py`) — BM25-only search for hook-safe performance; pre-built index; dual relevance gating; importance-weighted ranking
- **Session summary** (`src/session_summary.py`) — heuristic "Where was I?" resumption cards; topic/decision/question extraction
- **Memory injection hook** (`hooks/memory-injection.py`) — exchange-gated (every 10); injects top 3 relevant memories during sessions
- **Session start integration** — memories + resumption card injected via session-context.py
- **85 new tests** — 2,125 total passing

### v0.21.0 — Infrastructure stabilization (Feb 2026)
Phase 0: Fix what's broken before building features. System audit found 41 LaunchAgents (16 documented), 5 failing services, Granola retry storm, and documentation sprawl.
- **4 LaunchAgents fixed** — memory-maintenance (interpreter + path), memory-weekly-synthesis (interpreter + WorkingDirectory), nightly-optimizer (killed — dead import), daily-episodic-summary (killed — redundant)
- **Granola circuit breaker** — 10-failure threshold stops retry storms, permanently failed documents excluded
- **Hook system documented** — 28 hooks across 6 events, each with WHY rationale, probation table for behavioral hooks
- **System files pruned** — 87 items → ~50 (33 archived), 5 doc clusters collapsed (22 files archived)
- **Python interpreter audit** — 26 scripts cataloged with migration plan to 2 standard interpreters
- **3 script bugs fixed** — run_daily_maintenance.py sys.path, weekly_synthesis_runner.py undefined variable, plist missing WorkingDirectory

### v0.20.1 — Rename to Memeta (Feb 2026)
Project renamed from Total Rekall to Memeta across GitHub repo, source code, docs, tests, and dashboard.

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
- Renamed project to Memeta

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

## Phase 0: Infrastructure stabilization — SHIPPED (v0.21.0)

Completed Feb 28, 2026. See v0.21.0 in Shipped section above.

## Phase 1: Memory injection + hook infrastructure — SHIPPED (v0.22.0)

Completed Feb 28, 2026. See v0.22.0 in Shipped section above.

## Phase 2: Correction pipeline — SHIPPED (v0.23.0)

Completed Feb 28, 2026. See v0.23.0 in Shipped section above.

## Phase 3: Extraction evolution + system integration (~3-4 weeks)

Make the extraction pipeline self-improving and wire memory awareness into the conductor pattern.

- **Extraction-quality evolution loop** — quality tracking table in intelligence.db (prompt_variant, quality_grade, timestamp); 3-5 extraction prompt variants compete via epsilon-greedy selection; consolidation hook uses the winning variant; dashboard visualizes quality trends
- **Session-context v2 (richer context card)** — replace garbage _state.md captures with structured session summaries; consolidation hook writes topic, decisions, open questions; session-context formats as rich resumption experience
- **Conductor memory context for agent delegations** — new function `get_context_for_agent(agent_type, task_description)` in `src/agent_context.py`; calls hybrid_search filtered by agent-relevant tags; conductor injects relevant memories into Task prompts; one change in one place, benefits all agents
- **LaunchAgent health monitoring upgrade** — add auto-discovery (enumerate all com.lfi.*.plist files); add exit code checking (not just "is it running?" but "did it succeed?"); surface critical failures in session-context output

## Phase 4: Setup + ecosystem (~3-4 weeks)

On-ramp features and developer tools. The system can't grow if nobody can install it.

- **Setup wizard** (`memeta init`) — smooth first-run experience; detect environment, create directories, configure hooks, verify dependencies
- **Memory import from other systems** — eliminate switching costs; import from existing memory files, session histories, or structured notes
- **Memory search CLI** (`memeta search`) — standalone terminal search; table stakes for developer tools
- **CLAUDE.md generator from accumulated learnings** — auto-generate curated CLAUDE.md sections from top memories; low-infrastructure alternative to injection hooks for users who don't want hooks

## Phase 5: Advanced intelligence (backlog)

Features that require the earlier phases to be working before they synthesize well.

- **"I've solved this before" — real-time pattern recall** — proactive pattern matching against problem descriptions during work; requires memory injection (Phase 1) to be working
- **"Don't let me forget" — proactive commitment nudging** — detect intent markers ("I should", "need to", "TODO") and surface them next session; lightweight, high daily value
- **Frustration-to-skill pipeline** — recurring frustration patterns trigger skill proposals; the system learns to eliminate its own friction; require 5+ occurrences before proposing
- **Confidence-calibration loop** — track whether confidence predictions are accurate; build calibration curves; slow but durable improvement
- **Decision archaeology** — retrieve decision journal entries by code file/function; connects decisions to artifacts
- **CLAUDE.md generator (auto-generated sections from corrections)** — mature version of Phase 4 generator; informed by correction pipeline data and accumulated usage patterns

---

## Ecosystem changes

These are not features — they are the system-level pruning and restructuring decisions from the system audit debate. The infrastructure the features run on.

### Restructure targets

- **From 62 agents to ~55** — keep seniority spread (Director/Senior/Junior maps to Opus/Sonnet/Haiku cost tiers); only archive true duplicates (project-manager ≈ pm, clarify ≈ questioning protocol, stats-viewer unused, client-success unused) and move 3 target-client persona docs to Resources; wait for usage tracking data before any further pruning
- **From 2,000+ CLAUDE.md lines to ~1,200** — extract skills table from LFI/CLAUDE.md (replace with pointer to skills directory), extract LinkedIn/CRM/lead-gen/folder-structure from Operations CLAUDE.md to reference files, remove duplicate response format from global
- **From 87 System files to ~50** — ~~archive 25+ one-time artifacts and redundant docs~~ DONE (v0.21.0: 33 archived + 22 from doc clusters)
- **28 hooks documented with WHY rationale** — all kept; 3 behavioral hooks (delegation-check, questioning-nudge, response-summary-check) on 4-week probation with usage tracking (v0.21.0)
- **From 5 Python interpreters to 2** — Operations venv and memory-system venv only; 26 scripts audited with migration plan (v0.21.0); migration deferred to Phase 1
- **From 16 documented LaunchAgents to actual ~41 inventory** — 4 fixed/killed in v0.21.0; remaining need documentation pass

### What's kept

- Penny's dossier system (dossier_generator.py + ea_brain/ + meeting-intelligence/)
- Session-memory-consolidation hook (the write side of the read-write loop)
- Session indexing (2,900+ sessions, works independently of hook session ID problem)
- The conductor pattern (right architecture, enhance with memory context)
- lfi_integrations.py (one file, four APIs — the integration model)
- Core agent roster (~18 specialty agents + dev juniors)
- Core skill set (~25 skills, wait for usage tracking data before further pruning)
- Core hooks (7 surviving scripts)
- Core plugins (hookify, code-review, vercel)
- Unified health monitor (enhance with exit code checking and auto-discovery)

---

## Probation

Existing features the debate recommended killing, but which haven't had enough time to prove or disprove their value. Keep the code, evaluate with real usage data over 4+ weeks before deciding.

- **Emotional tagging** (src/wild/) — debate said "no meaningful signal in dev-AI transcripts" but never tested empirically
- **Schema classifier** (src/wild/) — debate said "metadata for metadata's sake" but may prove useful for memory organization
- **Encoding depth scoring** (src/wild/) — debate said "fifth quality metric, redundant" but could differentiate shallow vs. deep memories

---

## Graveyard

Features and components killed across both debates. Never-built proposals that lost the argument, plus provably broken/redundant infrastructure.

### Never-built features (rejected proposals)
- Temporal context resurrection (philosophy of mind problem, not engineering)
- Energy-aware attention allocation (no ground truth signal)
- Project narrative timeline (quarterly-use luxury)
- PyPI packaging (one user, no community)
- Memory relationship graph visualization (unreadable hairball past 50 nodes)
- Memory-as-training-data export (SQL query covers it)
- External integrations — Slack, Notion, email, calendar (scope creep into mature tools)
- Cognitive digital twin (AGI with a personality filter)
- Predictive project failure detection (2+ years of data needed)
- Memory-powered pair programming (multi-tenancy by another name)
- Intent-aware ambient capture (surveillance infrastructure)
- Memory-native code generation (decision archaeology achieves 60% at 10% cost)
- Webhook/notification integrations (deferred — fix alert quality first)
- Memory merge and consolidation UI (garbage collection + dedup covers 80%)

### Broken/redundant infrastructure (provably dead)
- nightly-optimizer LaunchAgent (dead import, literally can't run)
- daily-episodic-summary LaunchAgent (redundant with session-end hook)
- Skill recommendation documentation (5 of 7 files — 2,368 lines for a system that never triggered)
- Mistake documentation proliferation (6 of 7 files — six satellites orbiting one protocol)
- CLAUDE.md review ritual (3 files, 799 lines — if CLAUDE.md needs a 565-line review guide, it's too complex)
- 3 persona agent files (target-client docs masquerading as agents — move to Resources)
- ~4 duplicate agent files (project-manager ≈ pm, clarify ≈ questioning protocol, stats-viewer, client-success)
- Noisy hooks (delegation-strike-tracker standalone — folded into delegation-check.py)
- System documentation debris (20+ files — one-time artifacts, changelog entries posing as standing docs)
- System directory debris (empty directories, aspirational subdirectories)

### Under evaluation (need usage data before deciding)
- PromptBase skills (4 skills for a currently dormant side project — may reactivate)
- Behavioral enforcement hooks (delegation-check, questioning-nudge, response-summary-check — 2-week evaluation)
- Orchestration plugin + dx plugin (conflicts with conductor pattern, but may have niche value)
- Aspirational skills (browser-automation, build-production-grade, writing-guidelines, github-standards, codex, gepetto, perplexity — wait for usage tracking)

---

## Design principles

1. **Fix before building** — infrastructure health is a prerequisite for features
2. **One file per subsystem** — no documentation proliferation
3. **Noise kills signal** — reduce before adding new output channels
4. **Absorb every technique that works** — if it improves memory quality, it goes in
5. **Make them compound** — features feed each other in a loop, not a list
6. **Coexist additively** — new features layer on top, nothing gets replaced
7. **Predict and preempt** — build what the community will need before they ask
