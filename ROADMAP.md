# Roadmap

Where Memeta has been, where it is, and where it's going.

---

## Shipped

### v0.26.0 — Advanced intelligence (Mar 2026)
Phase 5: Proactive intelligence. The system anticipates what you need instead of waiting to be asked.
- **Commitment nudger** (`src/commitment_nudger.py`) — "Don't let me forget" triggers surface at session start, ranked by urgency (time overdue > topic match > event)
- **Pattern recall** (`src/pattern_recall.py`) — detects problem-solving context, surfaces past solutions via BM25; multi-signal gating prevents false positives
- **CLAUDE.md synthesizer** (`src/claudemd_synthesizer.py`) — auto-generates rules from 5 signal sources (corrections, directives, frustrations, preferences, workflows)
- **Frustration-to-skill pipeline** (`src/wild/skill_proposal_engine.py`) — recurring frustration patterns (5+/3+) auto-propose new skills
- **Decision store** (`src/decision_journal.py`) — persistent journal with file-based archaeology and outcome tracking
- **Confidence calibration** (`src/confidence_calibration.py`) — predicted vs actual tracking with binned statistics
- **0 adversarial review issues** — all 10 checks passed clean
- **104 new tests** — 2,539 total passing

### v0.25.0 — Setup + ecosystem (Mar 2026)
Phase 4: On-ramp features and developer tools. The system can't grow if nobody can install it.
- **CLI entry point** (`src/cli.py`) — `memeta` command with argparse subcommands: init, search, import, generate; proper exit codes; dispatches to real handler classes
- **Search CLI** (`src/search_cli.py`) — `memeta search` with BM25 + importance-weighted ranking; domain/tag/context-type filters; table, JSON, IDs-only, full output modes
- **Setup wizard** (`src/setup_wizard.py`) — `memeta init` with 7 environment checks; auto-creates directories; `--yes` for non-interactive; structured InitResult
- **Markdown importer** (`src/importers/`) — recursive directory scan; YAML frontmatter (safe parsing, no eval); cached dedup; importance guessing; progress callbacks
- **CLAUDE.md importer** (`src/importers/claude_md_importer.py`) — section-aware parsing; heading hierarchy; rule/directive detection
- **Learnings generator** (`src/learnings_generator.py`) — auto-generates CLAUDE.md learnings section from top memories; strip-and-regenerate pattern; dry-run mode
- **6 adversarial review fixes** — CLI handler rewrites, O(n*m)→O(n+m) dedup cache, safe frontmatter parsing, sentence case headings
- **168 new tests** — 2,435 total passing

### v0.24.0 — Extraction evolution + system integration (Feb 2026)
Phase 3: Make the extraction pipeline self-improving, wire memory awareness into the conductor pattern, and make the system responsive to user frustration.
- **Frustration-triggered injection** (`src/hook_state.py`) — 13 regex patterns detect user frustration ("you should know this", "I already told you", etc.); bypasses 10-exchange interval gate; reduces interval to 5 for rest of session; surfaces 5 memories instead of 3
- **Consolidation worker LaunchAgent** — background worker runs every 15 minutes; triggers search index rebuild after processing
- **Search index auto-rebuild** — dedicated LaunchAgent rebuilds BM25 index every 30 minutes for fresh search results
- **LLM session summaries** (`src/session_summary.py`) — `StructuredSessionSummary` dataclass (11 fields); `generate_llm_summary()` via Claude API; "Watch out for" correction surfacing; heuristic fallback with quality gate
- **Extraction evolution loop** (`src/wild/prompt_evolver.py`) — prompt template with `{CONVERSATION}` placeholder; epsilon-greedy selection (90/10 exploit/explore); real `test_prompt()` with extraction + grading; quality tracking in intelligence.db
- **Agent context function** (`src/agent_context.py`) — `get_context_for_agent(agent_type, task_description)` with hybrid search; tag boosting for 7 agent types; corrections always surface with priority
- **Human feedback mechanism** (`src/memory_feedback.py`) — dashboard-based quality voting on random memory batches; quality metrics tracking; triggers every ~20 sessions
- **Score clamping fix** (`src/wild/quality_grader.py`) — `_score_actionability()` and `_score_evidence()` could return >1.0; fixed with `min(1.0, ...)` clamp
- **83 new tests** — 2,267 total passing

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

## Phase 3: Extraction evolution + system integration — SHIPPED (v0.24.0)

Completed Feb 28, 2026. See v0.24.0 in Shipped section above.

## Phase 4: Setup + ecosystem — SHIPPED (v0.25.0)

Completed Mar 1, 2026. See v0.25.0 in Shipped section above.

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
- **From 2,000+ CLAUDE.md lines to ~1,200** — extract skills table from project CLAUDE.md (replace with pointer to skills directory), extract CRM/lead-gen/folder-structure from Operations CLAUDE.md to reference files, remove duplicate response format from global
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
