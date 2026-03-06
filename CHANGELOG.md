# Changelog

All notable changes to Memeta.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

---

## [0.26.0] - 2026-03-02

### Advanced intelligence (Phase 5)

The proactive release. Memeta stops waiting to be asked — it anticipates what you need, nudges you about forgotten commitments, surfaces past solutions when you hit a problem, and auto-generates CLAUDE.md rules from your own patterns.

**What you get from this:**
- Session start shows your overdue commitments ranked by urgency — "Don't let me forget" actually works now
- Hit an error you've solved before? Memeta surfaces the past solution automatically via BM25 search
- CLAUDE.md rules auto-generate from 5 signal sources: corrections, directives, frustrations, preferences, workflows
- Recurring frustration patterns (5+ occurrences, 3+ sessions) auto-propose new skills
- Full decision journal with file-based archaeology — "what decisions affected this file?"
- Confidence calibration tracks predicted vs actual to build future calibration curves

**Added**
- **Commitment nudger** (`src/commitment_nudger.py`) — extends ProspectiveTriggerManager with 4 new patterns ("I should", "need to", "let's make sure", "follow up on"); priority scoring (time overdue > topic match > event); deduplication by memory_id; formatted commitment blocks for session start. 20 tests
- **Pattern recall** (`src/pattern_recall.py`) — multi-signal problem detection (error messages, stack traces, frustration, help requests); meta-reference suppression prevents false positives on "implement error handling"; BM25-only past solution search within ~50ms hook budget; 5-exchange cooldown. 22 tests
- **CLAUDE.md synthesizer** (`src/claudemd_synthesizer.py`) — 5 pluggable RuleSource implementations (corrections, directives, frustrations, preferences, workflows); word-overlap deduplication (>0.7 threshold); category-grouped formatting; strip-and-regenerate with `<!-- AUTO-GENERATED: learnings -->` markers (distinct from correction_graduator's `corrections` markers). 22 tests
- **Frustration-to-skill pipeline** (`src/wild/skill_proposal_engine.py`) — frustration topic aggregation from sentiment_patterns table; threshold filtering (5+ occurrences AND 3+ sessions); dedup against existing proposals; SQLite schema migration for trigger_reason constraint. 13 tests
- **Decision store** (`src/decision_journal.py`) — full rewrite from 39-line stub to persistent SQLite store; Decision dataclass; CRUD with file-based archaeology (exact + prefix match); session queries; outcome tracking; backward-compatible legacy wrapper functions preserved. 16 tests
- **Confidence calibration** (`src/confidence_calibration.py`) — CalibrationEvent/CalibrationBin dataclasses; binned statistics (configurable bin size); implicit usage detection via word overlap heuristic (>0.3 after stopword removal). 11 tests

**Adversarial review findings:** All 10 checks passed with zero issues. Import correctness verified (both absolute and relative consistent with codebase convention). No circular imports, no marker collisions, no API drift, no false positives, no PTM coupling violations.

### Tests
- **Core suite:** 2,526 passing (+91 new, 0 regressions)
- **Wild suite:** 13 new frustration-to-skill tests
- **Total:** 2,539 passing (104 new tests across 6 features)

---

## [0.25.0] - 2026-03-01

### Setup + ecosystem (Phase 4)

The on-ramp release. Memeta can now be installed, configured, and populated without reading source code. Setup wizard validates your environment, importers bring in existing knowledge, search CLI gives instant terminal access, and the learnings generator writes curated CLAUDE.md sections from your best memories.

**What you get from this:**
- `memeta init` walks through environment validation, directory creation, and dependency checking — smooth first-run experience
- `memeta search "python tips" --domain engineering --tag dev` gives terminal search with relevance scoring, snippet highlighting, and multiple output formats (table, JSON, IDs-only)
- `memeta import markdown /path/to/notes` bulk-imports a directory of markdown files with frontmatter parsing, duplicate detection, and importance guessing
- `memeta import claude-md /path/to/CLAUDE.md` parses existing CLAUDE.md files into searchable memories
- `memeta generate claude-md` auto-generates a curated learnings section from your highest-quality memories using strip-and-regenerate (idempotent, safe to run repeatedly)

**Added**
- **CLI entry point** (`src/cli.py`) — argparse-based `memeta` command with subcommands: init, search, import, generate; dispatches to real handler classes; returns proper exit codes. 27 tests (parsing + integration)
- **Search CLI** (`src/search_cli.py`, `src/search_utils.py`) — `memeta search` with BM25 + importance-weighted ranking; filters by domain, tags, context type, min-importance; output modes: table (default), JSON, IDs-only, full content; shared search utilities for scoring and formatting. 44 tests
- **Setup wizard** (`src/setup_wizard.py`) — `memeta init` with 7 environment checks (Python version, memory dir, config, dependencies, search index, hook integration, dashboard); auto-creates directories; `--yes` flag for non-interactive mode; returns structured `InitResult` with checks, warnings, errors. 37 tests
- **Markdown importer** (`src/importers/markdown_importer.py`, `src/importers/base.py`) — recursive directory scanning; YAML frontmatter parsing (safe, no eval); importance guessing from content characteristics; filename-based tag extraction; cached duplicate detection; dry-run preview; progress callbacks. 28 tests
- **CLAUDE.md importer** (`src/importers/claude_md_importer.py`) — section-aware parsing; heading hierarchy extraction; rule and directive detection; section-based tagging; dry-run preview. 20 tests
- **Learnings generator** (`src/learnings_generator.py`) — selects memories by importance/confidence/status; deduplicates via content hash; groups by knowledge domain; formats as CLAUDE.md section with `<!-- AUTO-GENERATED: learnings -->` markers; strip-and-regenerate pattern for idempotent updates; dry-run mode. 12 tests

**Fixed (from adversarial review)**
- **Critical: CLI handler functions called non-existent wrappers** — rewrote `_cmd_init`, `_cmd_import`, `_cmd_generate` to instantiate actual classes (InitWizard, importers, LearningsGenerator)
- **Critical: O(n*m) duplicate detection** — `_is_duplicate()` called `list()` per file; added hash cache so `list()` is called exactly once
- **Critical: relative import in learnings_generator** — changed to absolute `from memory_system.X` matching all other Phase 4 modules
- **Critical: double select_memories() in apply_to_claude_md** — rewrote to call once, reuse result
- **Important: ast.literal_eval on untrusted frontmatter** — replaced with safe bracket/comma parsing; restricted numeric conversion to known fields only
- **Important: .title() violated sentence case** — domain headings now capitalize first letter only

**Architecture decisions (from adversarial debate)**
- Safe frontmatter parsing (no eval, no yaml dependency) — bracket splitting + known-field-only numeric conversion
- Cached dedup (hash set on first call) — O(n+m) instead of O(n*m) for large imports
- CLI dispatches to real classes — no wrapper functions, no import indirection
- Strip-and-regenerate for learnings — same proven pattern as correction_graduator
- BM25-only search in CLI — matches hook search for consistency and performance

### Tests
- **Core suite:** 2,435 passing (+168 new, 0 regressions)
- 27 CLI tests (argument parsing, dispatching, integration with real handlers)
- 44 search CLI tests (query building, output formatting, relevance scoring, edge cases)
- 37 setup wizard tests (environment checks, directory creation, error handling)
- 28 markdown importer tests (frontmatter, recursion, dedup, edge cases, cache performance, safe parsing)
- 20 CLAUDE.md importer tests (section parsing, heading hierarchy, directive detection)
- 12 learnings generator tests (selection, dedup, grouping, formatting, sentence case, performance)

---

## [0.24.0] - 2026-02-28

### Extraction evolution + system integration (Phase 3)

The system now improves its own extraction quality, responds to user frustration in real-time, provides rich structured session resumption, and wires memory awareness into agent delegations.

**What you get from this:**
- When you're frustrated ("I already told you this"), the system immediately surfaces relevant memories instead of waiting for the next 10-exchange cycle
- Session resumption cards now include LLM-generated summaries with decisions, open questions, and "Watch out for" warnings from past corrections
- The extraction pipeline self-improves: prompt variants compete via epsilon-greedy selection, and the best-performing prompts win
- Every agent delegation can now include relevant memories — the conductor pattern becomes memory-aware

**Added**
- **Frustration-triggered injection** (`src/hook_state.py`) — 13 regex patterns detect user frustration ("you should know this", "I already told you", "we've discussed this", etc.); bypasses 10-exchange interval gate for immediate memory surfacing; reduces injection interval from 10→5 for rest of session; uses top_k=5 instead of 3 when frustrated. 17 new tests
- **Consolidation worker LaunchAgent** (`launch-agents/com.lfi.consolidation-worker.plist`) — runs `async_consolidation.py` every 15 minutes; triggers `build_search_index()` after processing for fresh BM25 results
- **Search index auto-rebuild** (`launch-agents/com.lfi.search-index-rebuild.plist`) — dedicated LaunchAgent rebuilds BM25 search index every 30 minutes
- **LLM session summaries** (`src/session_summary.py`) — `StructuredSessionSummary` dataclass with 11 fields (session_id, summary, topic, decisions, open_questions, open_threads, files_touched, frustration_level, depends_on, generated_at, generator); `generate_llm_summary()` via Claude API; heuristic fallback with quality gate (<50 chars rejected); backward compatibility with old-format summaries. 22 new tests
- **"Watch out for" correction surfacing** (`src/session_summary.py`) — resumption cards now search correction memories and surface top 3 as warnings; helps prevent repeating past mistakes
- **Extraction evolution loop** (`src/wild/prompt_evolver.py`) — prompt template with `{CONVERSATION}` placeholder; epsilon-greedy `get_best_prompt()` (90% exploit best variant, 10% explore others); `test_prompt()` rewritten from simulation stub to real extraction + grading pipeline. 14 new tests
- **Agent context function** (`src/agent_context.py`) — `get_context_for_agent(agent_type, task_description, top_k=5)` returns formatted context string + source IDs; `AGENT_TAG_MAP` with 7 agent types (dev, brand, copywriter, seo, designer, researcher, relationship); hybrid search with tag boosting (not hard filtering); corrections always surface with ⚠️ markers, prioritized by importance. 17 new tests
- **Human feedback mechanism** (`src/memory_feedback.py`) — dashboard-based quality voting on random memory batches; `get_quality_check_batch()` samples 5 random memories; `save_feedback()` with thumbs up/down + optional notes; triggers every ~20 sessions; quality metrics tracking. 16 new tests
- **Dashboard quality check UI** (`dashboard/index.html`, `dashboard/server.py`) — quality check card with feedback voting interface; 4 new API endpoints (`/api/memory-quality-check`, `/api/human-feedback/stats`, `/api/memory-feedback`, `/api/memory-quality-metrics`)

**Fixed**
- **Critical: quality grader score overflow** (`src/wild/quality_grader.py`) — `_score_actionability()` could return >1.0 via unbounded sum of action_score + imperative_score + example_score; `_score_evidence()` could return up to 1.6. Both fixed with `min(1.0, ...)` clamp
- **quality_grader event type** (`src/wild/quality_grader.py`) — added `'injection'` to CHECK constraint event types for memory injection quality tracking

**Architecture decisions (from adversarial debate)**
- Frustration-triggered injection is a bypass gate, not a separate pipeline — reuses existing injection infrastructure
- LLM summaries with heuristic fallback — if Claude API is down, system degrades gracefully
- Epsilon-greedy over pure A/B testing — simpler, well-understood, no statistical significance issues
- Agent context uses tag boosting not filtering — ensures agents still see broadly relevant memories
- Human feedback as lightweight dashboard feature, not heavyweight UI — avoids survey fatigue

### Tests
- **Core suite:** 2,267 passing (+83 new, 0 regressions)
- 17 frustration detection tests (pattern matching, false positive prevention, gate bypass, interval reduction)
- 22 session summary tests (LLM summary, schema, backward compat, correction surfacing, quality gate)
- 14 extraction evolution tests (evolver integration, epsilon-greedy, prompt template, quality grading)
- 17 agent context tests (tag boosting, correction priority, hybrid search, formatting)
- 16 memory feedback tests (batch sampling, feedback saving, metrics, triggers)

---

## [0.23.0] - 2026-02-28

### Correction pipeline (Phase 2)

The feature that makes AI assistants stop being annoying. When Lee corrects Claude once, the system detects it, stores it as a high-importance correction memory, reinforces it across sessions, and graduates confirmed corrections to permanent CLAUDE.md rules.

**Added**
- **Correction detection** (`src/extraction_patterns.py`) — 3 new pattern categories: explicit corrections ("actually", "should be"), behavioral directives ("always/never do X"), frustration signals ("I told you", "stop doing"). New `detect_corrections()` seam returns typed dicts with pattern classification. Correction importance boost: 1.5x with 0.9 floor and 1.0 cap
- **Correction graduation** (`src/correction_graduator.py`) — full pipeline: find candidates (context_type=correction, confirmations >= 3, not already graduated), format as imperative rules, strip-and-regenerate CLAUDE.md within `<!-- AUTO-GENERATED: corrections -->` markers, mark graduated with `#graduated` tag. Preserves previously graduated rules across runs
- **Correction reinforcement** (`src/session_consolidator.py`) — `reinforce_corrections()` increments confirmations on existing corrections when same correction appears across different sessions; word overlap > 0.7 matching; same-session dedup via `source_session_id` prevents gaming
- **Correction injection** (`src/memory_injector.py`) — corrections surfaced first at session start in dedicated `=== ACTIVE CORRECTIONS ===` block; `context_type` added to BM25 search index; max 3 corrections, sorted by importance, filtered by project
- **Skill-aware memory tagging** (`src/session_consolidator.py`) — reads `active_skills` from hook_state at consolidation time; tags all memories with `#skill:{name}` for skill-specific surfacing
- **Temporal relevance on decay** (`src/importance_engine.py`) — `temporal_relevance="permanent"` parameter on `apply_decay()` exempts corrections from importance decay

**Architecture decisions (from adversarial debate)**
- Regular Memory with metadata (context_type, temporal_relevance, confirmations) — not a new CorrectionMemory subclass
- Detection-only seam (detect_corrections returns dicts, not objects) — clean separation from memory creation
- Flat list in CLAUDE.md, imperative rules, no categories — simpler and more extensible
- Same-session dedup prevents single verbose sessions from gaming graduation threshold
- BM25-only injection maintained — corrections at session start only, no mid-session injection
- Skill tags at memory level, not correction level — all memories benefit from skill context

**Fixed**
- **Critical: strip-and-regenerate data loss** — graduation would destroy previously graduated rules on second run. Fixed by combining previously graduated + new candidates before regenerating CLAUDE.md. Regression test added

### Tests
- **Core suite:** 2,184 passing (+59 new, 0 regressions)
- 12 extraction pattern tests (behavioral directives, frustration signals, boost values)
- 4 importance engine tests (permanent no-decay, backward compat)
- 11 session consolidator tests (correction metadata, skill tags, reinforcement, dedup)
- 21 correction graduator tests (full pipeline, edge cases, cross-run preservation)
- 11 memory injector tests (corrections block, sorting, filtering, project scoping)

---

## [0.22.0] - 2026-02-28

### Memory injection + hook infrastructure (Phase 1)

The biggest open loop in the system: memories went in at session end but nothing came out during sessions. This release makes Memeta read-write.

**Added**
- **Hook shared state** (`src/hook_state.py`) — session-scoped JSON coordination between hooks; stores exchange count, detected project, last injection timestamp; atomic writes with os.replace; probabilistic cleanup of stale sessions (1-in-10 chance); 29 tests
- **Memory injector** (`src/memory_injector.py`) — BM25-only search for hook-safe performance (~50ms); pre-built search index (`memory-search-index.json`); dual relevance gate (absolute BM25 floor of 1.0 + normalized threshold of 0.3); importance-weighted ranking; session start uses lower thresholds for broader context; 29 tests
- **Session summary** (`src/session_summary.py`) — heuristic-based "Where was I?" resumption cards; extracts topics, decisions, open questions, and file paths from last 5 messages; mtime-based cleanup of old summaries; 27 tests
- **Memory injection hook** (`hooks/memory-injection.py`) — UserPromptSubmit hook; exchange-gated (every 10 exchanges via hook_state.py); queries BM25 search with user prompt; injects top 3 memories above threshold; tracks injected memory IDs to prevent duplicates
- **Session start integration** — `session-context.py` extended to call `inject_at_session_start()` with detected project and format top relevant memories
- **Session resumption card** — `session-context.py` loads previous session summary (by session ID or latest) and formats as prose resumption block
- **Session summary generation** — consolidation hook generates and saves structured session summary alongside memory extraction

**Architecture decisions (from adversarial debate)**
- BM25-only search (no model loading) — hooks have 2-10s timeout budget
- Pre-built search index vs per-query file scan — index rebuilt periodically, loaded in ~50ms
- Single JSON state file with session ID keys — simpler than SQLite for hook use case
- Absolute + normalized threshold gating — prevents both weak matches and empty-corpus false positives
- Heuristic session summaries (regex + string matching) — no LLM dependency in hook path

### Tests
- **Core suite:** 2,125 passing (+88 new, no regressions)

---

## [0.21.0] - 2026-02-28

### Infrastructure stabilization (Phase 0)

The system audit revealed failing LaunchAgents, a meeting notes service retry storm, undocumented hooks, and documentation sprawl. This release fixes the foundation before building features.

**Fixed**
- **LaunchAgent: memory-maintenance** — interpreter changed from system Python to `~/.local/venvs/memory-system/bin/python3`; script path updated from `run_daily_maintenance.py` to `scripts/run_daily_maintenance.py`
- **LaunchAgent: memory-weekly-synthesis** — interpreter fixed; added missing `WorkingDirectory` key
- **`scripts/run_daily_maintenance.py`** — `sys.path.insert` pointed to `scripts/` instead of project root after file move; fixed to `parent.parent`
- **`scripts/weekly_synthesis_runner.py`** — `project_root` variable used but never defined; added `project_root = Path(__file__).parent.parent`
- **Meeting notes service retry storm** — 5 documents in infinite 404 retry loop (~240 failed API calls/day). Added circuit breaker: after 10 consecutive failures per document, marks as permanently failed and stops retrying

**Removed**
- **LaunchAgent: nightly-optimizer** — dead import (`nightly_maintenance_master.py`), literally could not run. Archived.
- **LaunchAgent: daily-episodic-summary** — redundant with session-end consolidation hook. Archived.

**Added**
- **Hook system documentation** — `_ Operations/hooks/README.md` v2.0.0 with WHY documentation for all 28 hooks across 6 events. Includes probation table, support files, known issues.
- **Python interpreter audit** — cataloged all 26 scripts using non-standard interpreters with migration plan

**Changed**
- **`_ System/` reduced from 87 to ~50 items** — 33 unreferenced files archived (one-time artifacts, redundant docs, dead references)
- **5 documentation clusters collapsed** — skill recommendation (8 files → 2), mistake docs (7 → 1), file organization (3 → 1), CLAUDE.md review ritual (3 → 0), quality system (8 → 3). Total: 22 files archived.
- Meeting notes service `failed_syncs.json` entries marked `permanently_failed: true`

### Tests
- **Core suite:** 2,037 passing (no regressions)

---

## [0.20.1] - 2026-02-27

### Changed
- **Project renamed to Memeta** — GitHub repo, pyproject.toml, all documentation, source code, tests, and dashboard updated from "Total Rekall" to "Memeta"

---

## [0.20.0] - 2026-02-27

### Added
- **Skill lifecycle management** (experimental/wild) — tracks action patterns, proposes new skills, flags stale skills for review
  - 5 new modules: action tracker, registry scanner, decay scorer, proposal engine, facade
  - 3 new DB tables: `skill_registry`, `skill_proposals`, `skill_usage_events`
  - Dashboard endpoints: `/api/skill-lifecycle/*` (overview, proposals, flagged, decay, patterns)
  - Intelligence orchestrator integration (signals for proposals + flagged skills)
  - Config: 2 new properties (`skill_lifecycle_state_path`, `skills_dir`)
  - Proposal triggers: daily burst (3+/day), sustained pattern (7+ distinct days)
  - Decay formula: `adjusted_half_life = 30 * (1 + log2(max(1, use_count)))`, flags at >= 0.8
  - Conservative v1: propose only (never auto-create), flag only (never auto-delete)
  - 135+ tests across 5 test files
- **Skill self-improvement** — captures invocation outcomes, accumulates learnings, proposes SKILL.md refinements
  - New module: `src/wild/skill_self_improver.py` (~730 lines)
  - 3 new DB tables: `skill_invocation_outcomes`, `skill_learnings`, `skill_refinement_proposals`
  - Outcome capture: heuristic assessment of skill invocations from session messages
  - Learning accumulation: Jaccard-based deduplication, evidence counting, confidence tracking
  - SKILL.md refinement: evidence-based proposals with conservative thresholds, unified diff preview
  - Health monitoring: per-skill success rates, trend detection, aggregated health dashboard
  - Dashboard: 5 new endpoints (`/api/skill-lifecycle/health`, `/health/<name>`, `/refinements`, `/refinements/<id>/preview`, `/learnings/<name>`)
  - Intelligence orchestrator: new signal collector for declining success rates + pending refinements
  - Async consolidation: automatic outcome assessment after session memory extraction
  - Lifecycle facade: integrated as 6th sub-module with daily maintenance pipeline
  - 34 tests in `tests/wild/test_skill_self_improver.py`

### Changed
- Documentation brought up to date: README badges, feature counts, ROADMAP shipped versions, FEATURES.md stats
- GitHub releases published for v0.19.0 and v0.19.1

### Tests
- **Core suite:** 2,037 passing
- **Wild suite:** 456 passing (34 new for skill self-improvement)

---

## [0.19.1] - 2026-02-19

### Fixed — code quality pass

**Critical fixes**
- **Schema conflict resolved** — `memory_access_log` table was defined with incompatible schemas in `intelligence_db.py` (TEXT PK) and `access_tracker.py` (INTEGER AUTOINCREMENT PK). Removed duplicate from `intelligence_db.py` and `temporal_predictor.py`. `access_tracker.py` is now the sole owner.
- **Connection leaks fixed** — `encoding_depth.py` (5 methods), `emotional_tagging.py` (every public method), `generational_gc.py` (init failure path), `retrieval_forgetting.py` (missing context manager). All now use proper try/finally or context manager patterns.
- **`memory_health.py` field mismatch** — `_compute_components` expected `created_at`, `source`, `title` but Memory dataclass uses `created`, `source_session_id`, has no `title`. Now accepts both field naming conventions with graceful fallbacks.

**Important fixes**
- **`api.py` TTL cache** — `search()`, `get_recent()`, `get_stats()` each scanned every .md file from disk. Added 5-second TTL cache on `_list_memories()` to prevent redundant disk I/O.
- **`api.py` exception logging** — Bare `except Exception: pass` on contradiction check replaced with `logger.debug()` for visibility.
- **`prospective_triggers.py` connection reuse** — `extract_triggers` opened a new SQLite connection per regex match inside a loop. Now opens once, closes once.
- **`memory_pagerank.py` batch inserts** — `store_results` changed from N individual INSERTs to `executemany`. Bare `except Exception` narrowed to specific exception types.
- **`reference_counter.py` validation** — Added `ref_type` validation in `increment`/`decrement`. Invalid types now raise `ValueError` instead of silently storing.
- **Dead code removed** — `directed_forgetting.py` unused `content` parameter, `retrieval_forgetting.py` unused `neglect_days`, `memory_pagerank.py` unused `total_real_edges`, `generational_gc.py` `mock_memories` table removed from production schema.

**Minor fixes**
- **False positive reduction** — `emotional_tagging.py` correction markers narrowed ("actually" → "actually no", "wait" → "wait no"). `prospective_triggers.py` "may" month disambiguation (only matches as month when preceded by preposition or followed by day number).
- **`schema_classifier.py` persist parameter** — `classify()` now accepts `persist=False` to skip DB write (pure classification without side effects).
- **`memory_interview.py` deduplication** — `generate_interview` was calling `client.list()` twice; now fetches once and passes to both helper methods.

### Tests
- 4 new tests (reference_counter validation, generational_gc schema)
- 1 test updated (intelligence_db_pool schema expectations)
- **Test suite:** 2,035 passing (from 2,031)

---

## [0.19.0] - 2026-02-19

### Added — Mega sprint (29 features)

**Batch 1 — system capabilities (19 features)**
- **Compaction triggers** — Time/size/quality/access-based triggers for memory compaction (40 tests)
- **Frustration archaeology** — Mines session history for recurring frustration patterns (23 tests)
- **Memory interview** — Interactive Q&A to deepen shallow memories via guided elicitation (21 tests)
- **Energy-aware loading** — Throttles memory loading based on system/user energy state (23 tests)
- **Cross-project sharing DB** — SQLite-backed cross-project memory sharing with permissions (14 tests)
- **Persona filter** — Filters memories by persona/context for role-appropriate recall (23 tests)
- **Memory compressor** — Lossless and lossy compression strategies preserving key insights (35 tests)
- **Memory health score** — Composite health metric across freshness, quality, connections, access (37 tests)
- **Event stream** — Pub/sub event system for memory lifecycle with persistence (25 tests)
- **Access tracker** — Tracks memory access patterns with frequency analytics (25 tests)
- **Entity extractor** — Extracts and links persons, tools, projects from memory text (33 tests)
- **Context budget optimizer** — Greedy token-budget optimizer for memory retrieval within limits (26 tests)
- **Temporal knowledge graph** — Tracks entities and relationships across time with evolution queries (30 tests)
- **Embedding maintenance** — Pre-computes and refreshes embeddings for fast search (15 tests)
- **Unified API** — Single `MemorySystem` class wrapping all features (22 tests)
- **Confidence persistence** — Persists confidence scores across sessions with SQLite backing (17 tests)
- **Relevance explanation** — Shows why each search result matched with highlighted snippets (45 tests)
- **Self-test diagnostics** — Validates system integrity: DB, files, config, search (24 tests)
- **Intelligence DB pool** — Connection pooling for intelligence.db with WAL mode (14 tests)

**Batch 2 — cognitive psychology + CS foundations (10 features)**
- **Generational GC** — Three-generation memory lifecycle (nursery/young/tenured) with graduated collection. Based on Ungar (1984). (30 tests)
- **Directed forgetting** — Detects "scratch that"/"remember this" intent markers, adjusts importance. Based on Bjork (1972). (25 tests)
- **Encoding depth** — Scores memory depth 1-3 (shallow/intermediate/deep) via levels of processing heuristics. Based on Craik & Lockhart (1972). (30 tests)
- **Prospective triggers** — Event/topic/time-based "remember when X" triggers from conversation. Based on Einstein & McDaniel (1990). (42 tests)
- **Content hash dedup** — Multi-level deduplication: exact SHA-256, normalized, and semantic hash. (50 tests)
- **Memory PageRank** — Iterative PageRank on relationship graph for structural importance scoring. (35 tests)
- **Retrieval-induced forgetting** — Detects retrieval blind spots via Gini coefficient analysis. Based on Anderson & Bjork (1994). (30 tests)
- **Emotional tagging** — Detects valence/arousal from session context for flashbulb memory prioritization. Based on Brown & Kulik (1977). (30 tests)
- **Schema classifier** — Classifies memories as assimilation/extension/accommodation. Based on Bartlett (1932). (35 tests)
- **Reference counter** — Tracks memory dependency counts, protects referenced memories from archival. (45 tests)

### Tests
- 952 new tests across 29 features
- **Test suite:** 2,031 passing
- **Features shipped:** 101

---

## [0.18.0] - 2026-02-18

### Added — Build sprint (5 features)
- **Provenance tracking** — `source_session_id` field traces every memory to its originating session. Conditionally written to YAML frontmatter (omitted when None), backward-compatible with legacy files.
- **Daily episodic summaries** — `src/daily_episodic_summary.py`: End-of-day summary generation from session history. `generate()` queries sessions, aggregates content (6000 char cap), calls Claude API. `load_recent()` for next-day context injection. LaunchAgent at 23:55.
- **Hybrid search unification** — `compute_idf()` with smoothed IDF formula replaces hardcoded 1.0. `normalize_scores()` scales BM25 to [0,1] before weighted combination. `embeddings` parameter for pre-computed vectors avoids per-doc model calls. Full backward compatibility.
- **Circuit breaker persistence** — SQLite persistence (WAL mode) so breaker state survives process restarts. Built-in `fallback` parameter on `call()`. `get_stats()` for dashboard. Thresholds adjusted to 5 failures / 600s recovery.
- **Memory decay archival** — Stale memories (importance < 0.2) moved to `archived/` directory during nightly maintenance. Manifest files document what was archived and why. `list(include_archived=True)` to include archived memories. DecayPredictor integration.

### Tests
- 10 new tests for provenance tracking
- 18 new tests for daily episodic summaries
- 27 new tests for hybrid search (IDF, normalization, embeddings, weights)
- 27 new tests for circuit breaker (persistence, fallback, stats, edge cases)
- 15 new tests for memory decay archival (6 classes: importance, access, manifest, decay predictor, idempotency, runner)

### Status
- **Test suite:** 1,079 passing (97 new tests)
- **Features shipped:** 72

---

## [0.17.0] - 2026-02-17

### Added — Intelligence layer (tier 2 complete)
- **Cluster-based morning briefing** — `src/cluster_briefing.py`: `ClusterBriefing` class reads memory clusters from intelligence.db, generates `MorningBriefing` with top clusters, content previews, divergence signals. `/api/briefing` dashboard endpoint.
- **FAISS vector store** — `src/vector_store.py`: `VectorStore` class backed by FAISS `IndexFlatIP` (L2-normalized inner product = cosine similarity). Persistent save/load, batch operations, SQLite migration. Dual-write in `embedding_manager.py` (FAISS primary, SQLite fallback). Chose over ChromaDB due to Python 3.14 pydantic incompatibility.
- **Intelligence orchestrator** — `src/intelligence_orchestrator.py`: Central "brain stem" collecting signals from 5 sources (dream synthesis, momentum tracking, energy scheduling, regret detection, frustration events). Synthesizes into prioritized `DailyBriefing`. `/api/intelligence` dashboard endpoint.
- **Cross-client pattern synthesizer** — `src/cross_client_synthesizer.py`: Reads global-scope and consent-tagged memories, groups by knowledge domain, generates `TransferHypothesis` with confidence boosted by prior transfer effectiveness. `/api/cross-client` dashboard endpoint.
- **Decision regret loop** — `src/decision_regret_loop.py`: Real-time warning before repeating regretted decisions. Fuzzy keyword matching against historical `decision_outcomes` table, decision categorization, formatted warnings with regret rate and alternatives. `/api/regret-check` dashboard endpoint.
- **Embeddings migration script** — `scripts/migrate_embeddings_to_faiss.py`: One-time migration from SQLite embeddings to FAISS index.

### Tests
- 20 new tests in `tests/test_cluster_briefing.py`
- 24 new tests in `tests/test_vector_store.py`
- 20 new tests in `tests/test_intelligence_orchestrator.py`
- 25 new tests in `tests/test_cross_client_synthesizer.py`
- 24 new tests in `tests/test_decision_regret_loop.py`

### Status
- **Test suite:** 1,256 passing (113 new tests)
- **Features shipped:** 58 + 10 dashboard/infra improvements
- **Backlog tier 2:** Complete (items #6-#10 shipped)

---

## [0.16.0] - 2026-02-17

### Added — Dashboard UX + freshness review
- **"Explain why" on search results** — `_extract_snippet()` centers ~120-char window on match, `_match_reasons()` identifies body/tag/domain matches. Search cards show highlighted snippet + match reason tags.
- **Memory freshness indicators** — `days_stale` field on `/api/memories`, CSS opacity classes (stale-1/2/3), colored freshness pips (green/amber/yellow/rose), stale toggle filter
- **Memory freshness review cycle** — `src/memory_freshness_reviewer.py`: `scan_stale_memories()`, `refresh_memory()`, `archive_memory()`, interactive CLI review, Pushover notification summary, weekly LaunchAgent (Sundays 9am)
- **Session replay modal** — click session row to view transcript turns + linked memories. `/api/session/<id>` endpoint with `_summarise_transcript()`. Shows user/assistant turns with 300-char previews, session stats, memory chips
- **GitHub Actions CI** — `.github/workflows/test.yml`: pytest on push/PR, Python 3.11/3.12/3.13 matrix, pip caching, ignores tests/wild

### Tests
- 16 new tests in `tests/test_dashboard_search.py` (snippet extraction, match reasons)
- 18 new tests in `tests/test_memory_freshness_reviewer.py` (scan, refresh, archive, summary, _days_since)

### Status
- **Test suite:** 1,145 passing (34 new tests)
- **Features shipped:** 58 + 5 dashboard/infra improvements

---

## [0.15.0] - 2026-02-17

### Fixed — Consolidation hook broken since Feb 12
- **`dashboard_export.py` IndentationError** — entire `with` block body was at wrong indent level, causing import-time crash
- **Hook using system python instead of venv** — `python3` couldn't resolve `from memory_system.config import cfg`; changed to `~/.local/venvs/memory-system/bin/python3`
- **5 days of sessions had zero memories captured** — all consolidation attempts failed silently since Feb 12

### Added — Pushover notification on consolidation
- Hook now sends push notification via Pushover when new memories are saved or reinforcements detected
- Notification includes: memories saved, deduplicated, reinforcements, promotions, high-value count
- Gracefully fails — doesn't break the hook if Pushover is unavailable

### Status
- **Test suite:** 1,111 passing (pre-existing flaky tests unchanged)
- **Features shipped:** 58

---

## [0.14.0] - 2026-02-17

### Added — Circuit breaker + Total Recall rename
- **Circuit breaker for LLM calls (TDD)** — `src/circuit_breaker.py` with CLOSED/OPEN/HALF_OPEN states, 3-failure threshold, 60s recovery timeout, thread-safe via `threading.Lock`, singleton registry via `get_breaker(name)`
- **12 circuit breaker tests** — state machine (6), registry (3), edge cases (3)
- **Wired into 3 LLM call sites:** `llm_extractor.extract_with_llm()` → breaker "llm_extraction", `llm_extractor.ask_claude()` → breaker "llm_ask_claude", `contradiction_detector.ask_claude_quick()` → breaker "llm_contradiction"

### Changed — Rename to Total Recall + charter
- **Project renamed from Engram to Total Recall** across all files (dashboard, pyproject.toml, CONTRIBUTING, SECURITY, all tracking docs)
- **README rewritten** with project charter framing: every methodology, all additive, predict what's next
- **SHOWCASE updated** with charter statement, current stats (1,111 tests), and condensed progress log

### Status
- **Test suite:** 1,111 passing, 2 skipped (99.8%)
- **Features shipped:** 58

---

## [0.13.0] - 2026-02-16

### Added — Dashboard enhancements
- **Memory detail modal** — click any memory card to see full content, metadata, tags, and grade info in an overlay
- **`/api/memory/<id>` endpoint** — returns full body, all metadata for a single memory
- **Export (JSON + CSV)** — `/api/export?format=json|csv` endpoint + export buttons in Memories tab
- **LaunchAgent** — `com.lfi.total-recall-dashboard.plist` auto-starts dashboard on login with KeepAlive
- **Prioritized backlog** — `BACKLOG.md` with 23 items across 5 tiers (compiled from ideas.md, UX analysis, ROADMAP)

### Fixed
- Wordmark in dashboard: Mnemora → Total Recall
- YAML frontmatter parser: single-quoted arrays (`['tag1', 'tag2']`) now parsed as lists instead of strings (was causing character-by-character iteration in export/display)
- `.gitignore` — added BACKLOG.md to excluded working docs

---

## [0.12.0] - 2026-02-16

### Added — Total Recall dashboard
- **`dashboard/server.py`** — Flask server with JSON API endpoints (`/api/stats`, `/api/memories`, `/api/sessions`, `/api/refresh`)
- **`dashboard/index.html`** — full-stack UI with Obsidian + amber design (Fraunces + IBM Plex Mono/Sans)
  - Overview: stat cards, grade distribution bar, domain bars, 26-week activity heatmap
  - Memories: searchable/filterable cards with grade indicators, pagination
  - Sessions: table with date, name, message/tool/memory counts
  - Knowledge map: tag cloud (frequency-scaled) + domain breakdown
  - Sidebar with domain quick-filters

### Fixed
- Memories tab race condition — eliminated with concurrent load guard
- Error handling for API failures in frontend

---

## [0.11.0] - 2026-02-16

### Changed — Rename to Total Recall
- Project renamed from Mnemora to Total Recall throughout (commit c8a7545)
- README, dashboard, CHANGELOG, package metadata all updated

### Fixed
- **F30→F28 search delegation** — `MemoryAwareSearch.search()` now delegates to `SearchOptimizer.search_with_cache()` + `rank_results()` instead of bare client call
- **IntelligenceDB connection leak** — replaced `pool.get_connection()` with `sqlite3.connect()` directly (pool connections were borrowed at init and never returned)
- **Dream Mode O(n²)** — `MAX_MEMORIES = 1000` cap confirmed in place

---

## [0.10.0] - 2026-02-15

### Added — Config centralization
- **`src/config.py`** — `MemorySystemConfig` frozen dataclass, module singleton `cfg`. All paths and constants overridable via `MEMORY_SYSTEM_*` env vars.
- Centralized: `memory_dir`, `session_dir`, `project_id`, `session_db_path`, `shared_db_path`, `fsrs_db_path`, `intelligence_db_path`, `cluster_db_path`, `max_pre_compaction_facts`, `cache_ttl_seconds`

### Changed
- `session_history_db.py` — `SESSION_DB_PATH` now reads from `cfg`
- `shared_knowledge.py` — `SHARED_DB_PATH` now reads from `cfg`
- `session_consolidator.py` — hardcoded `~/.claude/projects` → `cfg.session_dir`
- `fsrs_scheduler.py` — relative `Path(__file__)` → `cfg.fsrs_db_path`
- `intelligence/search_optimizer.py` — relative `Path(__file__)` → `cfg.intelligence_db_path`

### Fixed
- `test_search_optimizer.py` — `sys.modules` mock patched wrong key (`memory_ts_client` → `memory_system.memory_ts_client`) after import migration

### Status
- **Test suite:** 1085 passing, 2 flaky (LLM timeout — pre-existing), 2 skipped (99.6%)

---

## [0.9.0] - 2026-02-15

### Changed — Package infrastructure + import cleanup
- **`pyproject.toml`** — package now installable via `pip install -e .`. Maps `memory_system` → `src/` via `[tool.setuptools.package-dir]`.
- **`conftest.py`** — minimal root conftest enables pytest discovery without sys.path tricks
- **Venv** — at `~/.local/venvs/memory-system/` (project is in Google Drive, can't create venv inside)
- **All imports standardized** — `from memory_system.X import ...` everywhere. Removed 71 sys.path hacks across tests, src, hooks, and scripts.

### Fixed
- Pre-existing ordering bug in `scripts/nightly_maintenance_master.py` — `SCRIPTS_DIR` used before definition

### Status
- **sys.path hacks remaining:** 2 (intentional — `decision_journal.py` optional commitment tracker integration, `update_fsrs_manual.py` code generator)
- **Test suite:** 1085 passing (was 1086 before fix noted above)

---

## [0.8.1] - 2026-02-15

### Added — Critical infrastructure tests
- **db_pool.py** — 50 new tests (connection pooling, thread safety, context managers)
- **embedding_manager.py** — 62 new tests (storage, SHA-256 deduplication, batch ops)
- **semantic_search.py** — 72 new tests (vector similarity, ranking, filters)
- **hybrid_search.py** — 73 new tests (combined scoring, query parsing, project scoping)
- **session_history_db.py** — 65 new tests (transcript storage, search, stats)
- **Total added:** 322 tests

### Fixed
- 3 bugs in `session_history_db.py` found during test writing: docstring syntax error, indentation error, FTS5 bad column reference

### Status
- **Test suite:** 1086 passing, 2 skipped (was 765 before this release)

---

## [0.8.0] - 2026-02-13

### Changed
- **F63 (Prompt Evolution)** — discovered already built and shipped; updated all docs to correctly reflect 58 features
- SHOWCASE.md, HANDOFF.md, PLAN.md updated to v0.7.0 final state

### Status
- **Features shipped:** 58 | **Test suite:** 765 passing, 2 skipped

---

## [0.7.0] - 2026-02-13

### Fixed - Test Suite Cleanup
- **All failures resolved** - 8 failing tests → 0 failing (765 passing, 2 skipped)
- **F29 Smart Alerts test API mismatch** - Tests used `priority` parameter but implementation uses `severity`. Fixed `get_pending_alerts()` → `get_unread_alerts()`, `mark_delivered()` → `dismiss_alert()`.
- **F31 TopicSummary dataclass** - Tests omitted required fields `summary_id`, `created_at`, `memory_ids`.
- **F51 Temporal Predictor hook import contamination** - Fixed with `_load_hook_module()` helper that forces clean reload.

### Added - Test Coverage Expansion
- **F61 A/B Testing** - 4 → 14 tests (experiment lifecycle, variant assignment, statistical significance, auto-adoption, history)
- **F75 Dream Synthesis** - 4 → 16 tests (connection discovery, synthesis generation, queue priority, morning briefing)

### Status
- **Features shipped:** 57 | **Deferred:** 17 (F36-43, F66-74 integrations)
- **Test suite:** 765 passing, 0 failing, 2 skipped (99.7%)

---

## [0.6.0] - 2026-02-13

### Added - Wild Features Batch (F52-F65)
- **F52: Conversation Momentum Tracking** - Tracks momentum score 0-100 to detect "on a roll" vs "stuck" states. Calculates momentum from new insights (+20 each), decisions (+15 each), repeated questions (-10 each), topic cycles (-15 each). Provides state-specific intervention suggestions. 18 tests covering momentum calculation, state detection (on_roll/steady/stuck/spinning), interventions, statistics, and trend analysis.
- **F53: Energy-Aware Scheduling** - Learns energy patterns by hour/day and suggests optimal task timing. Tracks high/medium/low energy with confidence scores. Maps 6 default task types (deep_work, writing, meetings, code_review, admin, learning) to cognitive load. Suggests tasks matching current predicted energy level. 18 tests covering energy recording, pattern learning, prediction, task suggestion, and confidence building.
- **F54: Context Pre-Loading (Dream Mode v2)** - Pre-loads context before work sessions. Schedule preloads by time + context_type (client_meeting, coding_session, writing). Queue system with pending/loaded/expired states. Retrieves preloaded memories by type and optional target. Auto-cleanup of old tasks. 11 tests covering scheduling, pending detection, mark loaded/expired, retrieval, cleanup, and statistics.
- **F56: Client Pattern Transfer** - Identifies and transfers patterns across projects. Records pattern transfers with effectiveness ratings. Finds transferable patterns based on successful transfers (rating >= 0.7). Tracks transfer history per project. Privacy-aware cross-project learning. 11 tests covering pattern transfer, rating, history, successful transfers, and pattern discovery.
- **F58: Decision Regret Detection** - Tracks decisions and warns before repeating regretted choices. Records decision content, alternatives, and outcomes (good/bad/neutral). Detects regret patterns (50%+ regret rate, min 2 occurrences). Generates warnings with regret statistics. Supports decision history and regret-only filtering. 14 tests covering decision recording, regret marking, pattern detection, warnings, history, and statistics.
- **F59: Expertise Mapping** - Maps agent expertise by domain for optimal routing. Records memory_count × avg_quality scores per agent/domain. Updates existing expertise with weighted averages. Routes to best expert by score. Returns full expertise map and per-agent breakdowns. 11 tests covering expertise recording, updates, expert lookup, mapping, per-agent queries, and statistics.
- **F60: Context Decay Prediction** - Predicts staleness before it happens. Records predicted_stale_at with confidence by reason (project_inactive 0.7, superseded 0.9, outdated_source 0.8). Surfaces memories becoming stale within N days. Tracks refresh/review status. Provides statistics by reason. 11 tests covering prediction, updates, stale detection, refresh tracking, and statistics.
- **F64: Learning Intervention System** - Detects repeated questions and suggests learning resources. Tracks question occurrence counts. Detects high-frequency questions (3+ occurrences). Generates tutorials and reference docs (template-based MVP). Marks intervention effectiveness. 12 tests covering question recording, increment logic, detection, tutorial/reference generation, intervention saving, effectiveness tracking, and statistics.
- **F65: Mistake Compounding Detector** - Tracks mistake cascades to prevent compound errors. Records root_mistake_id → downstream_error_ids chains. Detects cascades by root or downstream error. Analyzes root causes. Generates prevention strategies by cascade depth. Provides cascade statistics and depth distribution. 13 tests covering cascade recording, detection (by root/downstream), root cause analysis, prevention suggestions, filtering, and statistics.

### Test Coverage
- **Total tests:** 735 passing, 2 skipped, 8 failing (98.9% pass rate)
- **New tests this release:** 109 tests across 9 wild features (F52-F65)
- **Wild features implemented:** F52, F53, F54, F56, F58, F59, F60, F64, F65 (9 features, 109 tests)

---

## [0.5.0] - 2026-02-13

### Added
- **F29: Smart Alerts** - Proactive notification system for memory events with 5 alert types (expiring_memory, contradiction, pattern_detected, stale_memory, quality_issue) and 4 severity levels (low, medium, high, critical). Features daily digest generation, alert dismissal/action tracking, statistics, and automatic cleanup of old dismissed alerts. 16 comprehensive tests covering initialization, alert creation, filtering, dismissal, action tracking, daily digest, statistics, and cleanup.
- **F30: Memory-Aware Search** - Multi-dimensional search with semantic content matching, temporal filtering (absolute and relative dates), project/tag filtering, and natural language query parsing. Extracts temporal references (last week, yesterday, January), importance indicators, project mentions, and tags from queries. Includes search history tracking and relevance scoring with three ordering modes (importance, recency, relevance). 16 tests covering initialization, content search, natural language parsing (temporal, importance, project, tags), history tracking, and relevance calculation.
- **F31: Auto-Summarization** - LLM-powered topic summarization with narrative generation, timeline building, key insights extraction, and database persistence. Generates 2-3 paragraph summaries via Sonnet 4.5 with fallback to structured summaries on timeout. Supports topic-based summarization, summary retrieval/filtering, and regeneration from saved memory IDs. 14 tests covering initialization, empty/populated summarization, timeline generation, database persistence, retrieval, filtering, regeneration, and metadata tracking.
- **F32: Quality Scoring** - Automated quality assessment for memories checking 5 dimensions: length (min 10, optimal 30-200, max 500 chars), vague language detection (12 vague word triggers), actionability (verb presence), sentence completion, and capitalization. Provides scored assessments (0.0-1.0) with specific issues and improvement suggestions. Supports batch assessment and low-quality filtering with custom thresholds. 13 tests covering high-quality detection, length checks, vague language, verbs, sentence structure, capitalization, batch processing, filtering, and suggestion provision.

---

## [0.4.0] - 2026-02-13

### Added
- **F26: Memory Summarization** - LLM-powered summarization of memories with three types: cluster summaries (theme + key points), project summaries (30-day progress reports), and period summaries (weekly/monthly digests). Generates 2-3 paragraph summaries via Sonnet 4.5 with fallback to generic summaries on timeout. 17 comprehensive tests covering initialization, cluster/project/period summarization, filtering, regeneration, statistics, and LLM fallback.

---

## [0.3.1] - 2026-02-13

### Fixed
- **F28 cache bug (CRITICAL)** - Fixed cache hit hydration that was still calling `search_fn()` on cache hit, making cache non-functional. Cache now properly hydrates Memory objects from cached IDs using MemoryTSClient.get() with FileNotFoundError handling for deleted memories.
- **F28 cache key mismatch** - Fixed `invalidate_cache()` to use same composite key format as storage: `{query}|{project_id or 'global'}` instead of just query hash.
- **F28 test coverage** - Updated `test_cache_hit_second_search()` to verify search_fn NOT called on cache hit. Fixed `test_cache_invalidation()` to use correct composite key format. Added `test_cache_efficiency()` to verify cache prevents redundant search calls across 10 consecutive hits.

---

## [0.3.0] - 2026-02-13

### Added
- **F24: Memory Relationship Mapping** - Graph-based relationship system with 5 types (causal, contradicts, supports, requires, related), BFS causal chain discovery, bidirectional queries, contradiction detection, and global/per-memory statistics. 28 comprehensive tests covering initialization, link creation, retrieval, causal chains, contradictions, updates/deletions, and statistics.
- **F27: Memory Reinforcement Scheduler** - FSRS-6 based review scheduling with due review surfacing, review history tracking, and automatic rescheduling. Progressive interval doubling for non-FSRS memories. 24 tests covering initialization, scheduling, due reviews, recording, rescheduling, statistics, and FSRS integration.
- **F28: Memory Search Optimization** - Query result caching with 24h TTL and project-scoped cache keys. Improved ranking algorithm: semantic (0.5) + keyword (0.2) + recency (0.2) + importance (0.1) with clamped recency scores. Search analytics tracking for future CTR learning. 14 tests covering initialization, caching (miss/hit/expiry/invalidation), ranking, selection recording, and analytics.
- **F51: Temporal Pattern Prediction** - Learns temporal patterns from memory access behavior and predicts needs proactively. Passive learning logs every memory access (time/day/context). Pattern detection identifies daily/weekly/monthly patterns (min 3 occurrences). Feedback loop (confirm/dismiss) adjusts confidence. Topic resumption detector hook auto-surfaces memories when user references past discussions. 25 tests covering access logging, pattern detection, prediction, feedback loop, hook integration, and MemoryTSClient instrumentation.
- **Test files for F61 and F75** - Created `tests/wild/test_ab_tester.py` (4 tests) and `tests/wild/test_dream_synthesizer.py` (4 tests) for basic module initialization and data structure validation
- **Progressive timeout increases in ask_claude** - LLM retry logic now increases timeout on each attempt: initial → +10s → +20s (e.g., 30s → 40s → 50s). Gives Claude more time on retries.
- **Planning documentation** - Created comprehensive implementation plans for F24 (relationship mapping), F27 (reinforcement scheduler), F28 (search optimization), plus feature specs for F24-32 (intelligence enhancement), F36-43 (integrations - deferred), and F51-75 (wild features with tier prioritization).

### Fixed
- **IntelligenceDB initialization bug** (src/intelligence_db.py:45) - Fixed AttributeError where `self.conn.row_factory` was accessed before `self.conn` was initialized. Now properly initializes connection from pool before setting row_factory.
- **PooledConnection attribute proxy** (src/db_pool.py) - Added `__setattr__` method to properly proxy attribute writes (like `row_factory`) to the underlying sqlite3.Connection object.
- **MemoryTSClient API mismatch** (src/session_consolidator.py:564) - Fixed incorrect `search()` call using non-existent `query=` and `limit=` parameters. Now correctly uses `content=` parameter as defined in MemoryTSClient API.
- **Deduplication LLM timeout** (src/session_consolidator.py:421) - Fixed timeout in `_smart_dedup_decision` by increasing from 10s to 30s, reducing retries from 3 to 2, and adding fallback to similarity-based decision (>0.75 = duplicate) when LLM times out.
- **SQL WHERE clause precedence** (src/intelligence/relationship_mapper.py) - Fixed operator precedence issue when combining OR and AND conditions by wrapping OR conditions in parentheses: `(from_memory_id = ? OR to_memory_id = ?) AND relationship_type = ?`
- **Test coverage improvement** - Fixed 12 intelligence_db tests (0/12 → 12/12), 12 session_consolidator tests (14/26 → 26/26), added 8 new wild feature tests, and added 28 relationship mapping tests

### Changed
- Repository cleanup: Archived obsolete documentation (PHASE-*.md, old QA passes, _working/) to _archive/
- **SHOWCASE.md rewrite** - Restructured using VBF framework (Values → Benefits → Features). Leads with problem/pain, shows how world improves, grounds all features in benefits.

---

## [0.2.0] - 2026-02-12

### Added
- embedding_manager.py: Persistent embedding storage with SHA-256 content hashing
- async_consolidation.py: Queue-based async consolidation system
- nightly_maintenance_master.py: Orchestrates all nightly jobs
- scripts/consolidation_worker.py: Background worker for async processing
- scripts/nightly_embedding_precompute.py: Pre-computes embeddings nightly
- hooks/session-memory-consolidation-async.py: Fast SessionEnd hook (<1s)
- PERFORMANCE-ANALYSIS.md: Comprehensive scaling analysis by Performance Architect
- RELIABILITY-ANALYSIS.md: Failure modes and recovery by Reliability Engineer
- UX-ANALYSIS.md: Usability assessment by UX Reviewer
- tests/wild/test_writing_analyzer.py: 18 tests for F57 Writing Style Analyzer

### Changed
- Semantic search now uses pre-computed embeddings from intelligence.db (500s → <1s)
- Session consolidation moved to async queue (60-120s hook → <1s)
- Database optimization (VACUUM + ANALYZE) now runs nightly
- SQLite backups automated with 7-day retention

### Fixed
- Semantic search O(n) embedding bottleneck
- SessionEnd hook timeout risk from blocking consolidation
- Unbounded in-memory embedding cache (memory leak)

### Performance Impact
- Semantic search: 500s → <1s per search at 10K memories
- Hook execution: 60-120s → <1s (queue only)
- API costs at 10K scale: $1,000/day → $4/day (with optimizations)

---

## [0.1.0] - 2026-02-12

### Added
- 35 features shipped (F1-22 + F23, F33-35, F44-50, F55, F62-63)
- 5 features coded (F57, F61, F75 - awaiting tests)
- ~6,000 lines of production Python
- 358/369 tests passing (97%)
- intelligence.db: Shared database for features 23-75
- Session history DB: 779 sessions, 177K messages indexed

### Features Implemented
- F1-22: Core memory intelligence features
- F23: Memory Versioning
- F33-35: Wild features (Sentiment, Velocity, Personality Drift)
- F44-50: Multimodal + Meta-learning
- F55: Frustration Early Warning
- F62: Quality Auto-Grading
- F63: Prompt Evolution

### Infrastructure
- memory-ts integration
- FSRS-6 spaced repetition
- Pattern detection and mining
- Cross-project memory sharing
- Session consolidation pipeline
