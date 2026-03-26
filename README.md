# Memeta

Every session, Claude starts over. Memeta gives it memory that actually compounds.

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-3%2C168%20passing-brightgreen) ![Version](https://img.shields.io/badge/version-0.32.0-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## The problem

Claude's built-in memory is a black box. Anthropic decides what to store, stores it somewhere opaque, and surfaces it without explanation. You can't see what's in it, can't search it, can't grade it, and can't understand why some things stick and others don't.

The real cost is the compounding. Claude repeats mistakes you've already corrected. Rebuilds solutions you've already solved. Makes different architectural decisions in different sessions with no awareness of what was already decided. Your system accumulates sessions without accumulating intelligence.

Meanwhile, the memory community keeps producing new techniques -- FSRS spaced repetition, hybrid search, dream synthesis, frustration detection -- but they're all separate projects that don't talk to each other. You have to pick one approach. Nobody's combined them.

The meta moves fast. Reddit posts, GitHub repos, community experiments -- every few weeks someone figures out something that genuinely works. But the discovery stays siloed. It doesn't get integrated with everything else that also works.

## What changes

**What you learn stays learned.** FSRS-6 schedules memories for review at the mathematically optimal interval. Important context stays available without flooding every session. Mistakes you've corrected don't come back three sessions later.

**Claude finds relevant context automatically.** Hybrid search (70% semantic + 30% BM25) surfaces memories that match what you're working on, without you having to remember to ask. Query "What did we decide about authentication?" and get the specific decision, the reasoning, and related past decisions.

**The system improves while you sleep.** Overnight consolidation synthesizes cross-session patterns, surfaces forgotten commitments, and runs dream synthesis -- mapping how solutions from one project might apply to another.

**You get the current state of the art, not a frozen snapshot.** Memeta is the synthesis layer for the Claude Code memory community. When a new technique proves out -- in Reddit posts, GitHub repos, community experiments -- it gets integrated here, additively. You don't have to track the meta. You just update the repo.

## What's in it

149 features across 6 layers, all additive:

### Foundation -- the basics done right
Contradiction detection · provenance tracking · memory versioning · decision store · quality auto-grading · FSRS-6 spaced repetition · importance scoring with auto-tuning · confidence persistence · directed forgetting · encoding depth · entity extraction · emotional tagging

### Intelligence -- the compounding layer
Hybrid search (70% semantic + 30% BM25) · cache-aware search with multi-factor ranking · semantic clustering · relationship mapping · smart alerts · quality scoring · temporal knowledge graph · memory PageRank · schema classifier · retrieval-induced forgetting

### Autonomous -- the system that works while you sleep
Dream mode synthesis · frustration early warning · momentum tracking · energy-aware scheduling · decision regret warnings · pattern transfer across projects · prompt evolution via genetic algorithm · context pre-loading before meetings · compaction triggers · frustration archaeology · memory interview · persona filter · memory compressor · memory health scoring · commitment nudger · pattern recall · CLAUDE.md synthesizer · frustration-to-skill pipeline · confidence calibration

### Dashboard -- see what your memory knows
Overview with heatmap · searchable memory library · session replay · knowledge map · export (JSON/CSV) · freshness indicators · intelligence briefing · cross-client patterns

### Ecosystem -- install, import, search, generate
`memeta init` setup wizard · `memeta search` terminal search · markdown directory importer · CLAUDE.md importer · learnings generator for CLAUDE.md

### Infrastructure
Circuit breaker for LLM calls · FAISS vector store with dual-write · centralized config · async consolidation · GitHub Actions CI · intelligence DB pool · content hash dedup · access tracker · event stream · unified API · self-test diagnostics

**Full feature list:** [`FEATURES.md`](FEATURES.md)

---

## How it works in practice

### Morning (wake up to insights)

```
Daily synthesis (auto-generated overnight):

Key insights extracted:
- Learned: New preference for async communication on long projects
- Pattern: 3rd time fixing same issue → hook needed
- Decision: Chose SQLite over Postgres for local storage

Dream synthesis (3am run):
- Approach for Project A maps to Project B's problem
- Both struggle with the same underlying constraint
```

### During work (real-time intelligence)

```
⚠️  Frustration detected: You've corrected "webhook" 3 times in 20 minutes.
Suggestion: Add a hook to prevent webhook errors permanently.
```

```
🤔 You've made this call 4 times. Three times you regretted it.
Consider instead: Write tests first.
```

### Query (before vs after)

**Without Memeta:**
```
User:      "What did we decide about the authentication approach?"
Assistant: "I don't have specific details. Can you remind me?"
```

**With Memeta:**
```
User:      "What did we decide about the authentication approach?"
Assistant: On March 12, you decided to use JWT with refresh tokens.
           Reasoning: Stateless, works across multiple services.
           Related: This mirrors your decision for the API project.
```

---

## Memeta vs. Claude Code's built-in auto memory

| | Claude Code auto memory | Memeta |
|--|------------------------|--------------|
| Storage | Anthropic servers (opaque) | Local `.md` files you own |
| Visibility | None -- black box | Full -- every memory inspectable |
| Search | Not available | Semantic + BM25 hybrid, cached |
| Quality grading | None | A/B/C/D by importance weight |
| Spaced repetition | None | FSRS-6 -- science-backed retention |
| Pattern detection | None | 149 features including dream synthesis, session-start briefing |
| Self-improvement | None | Overnight consolidation, prompt evolution |
| Methodology count | 1 (proprietary) | All of them (open, additive) |
| Control | None | Full -- you decide what persists |
| Circuit breaker | None | LLM call protection with auto-recovery |

---

## Installation

**Quick setup:** Paste this into Claude Code:

> "Set up Memeta for me: https://github.com/lee-fuhr/memeta"

Claude will clone the repo, create a venv, install dependencies, configure paths, and set up the session end hook.

**Manual setup:**

```bash
git clone https://github.com/lee-fuhr/memeta.git
cd memeta
python3 -m venv ~/.local/venvs/memory-system
source ~/.local/venvs/memory-system/bin/activate
pip install -e .
pytest tests/ --ignore=tests/wild -q
```

**Configuration** (all paths via env vars):

```bash
export MEMORY_SYSTEM_PROJECT_ID="MyProject"
export MEMORY_SYSTEM_SESSION_DB="~/.local/share/memory/MyProject/session-history.db"
export MEMORY_SYSTEM_INTELLIGENCE_DB="~/.local/share/memory/intelligence.db"
```

**Dashboard:** `http://localhost:8766` after `python3 dashboard/server.py`

---

## Contributing

The Claude Code memory community is active and constantly finding new things that work. If you've discovered a memory technique, pattern, or integration that Memeta doesn't cover -- open an issue or a PR. Specifically:

- A new memory technique from the community that should be integrated
- A pattern you've found that doesn't fit any existing layer
- A failure mode in an existing feature
- A new additive approach that would play well with what's already here

That's how this stays current. The field is moving too fast for any single person to track. Memeta is the aggregation point.

## Part of the stack

| Repo | Role |
|------|------|
| [Build Bible](https://github.com/lee-fuhr/build-bible) | Methodology -- principles and patterns for building with agents |
| [Atlas](https://github.com/lee-fuhr/atlas) | Framework -- where every component in your system lives and why |
| [ai-ops-starter](https://github.com/lee-fuhr/ai-ops-starter) | Scaffolding -- folder structure and templates to stand up a system |

---

MIT -- see [LICENSE](LICENSE)
