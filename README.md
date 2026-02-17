# Total Recall

**Every memory technique that works. Every approach from the meta. All coexisting additively. And then predicting the next features and building those too.**

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-1111%20passing-brightgreen) ![Version](https://img.shields.io/badge/version-0.14.0-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What this is

The Claude Code memory ecosystem is exploding. Reddit posts, Ben Fox's ZeroBot, OpenClaw's hybrid search, FSRS spaced repetition, dream synthesis, frustration detection — every week someone discovers a new technique that genuinely works.

The problem: they're all separate projects. You can use Ben's quality grading OR OpenClaw's search weighting OR FSRS scheduling, but nobody's combined them. Each approach solves a real problem, but you have to pick and choose, and they don't talk to each other.

**Total Recall is the kitchen sink.** Every methodology and approach that has come through the meta, through Reddit, through the community — as long as they can coexist additively, they're in. Not "pick one approach" but "use all of them simultaneously, and let them reinforce each other."

And then: **predict what's next and build it before anyone asks.** The backlog isn't a wish list — it's a forecast. What will the community discover in 3 months? Build it now.

---

## The charter

1. **Absorb every technique that works** — quality grading, spaced repetition, semantic search, contradiction detection, dream synthesis, frustration tracking, decision journaling, energy-aware scheduling, pattern transfer. If it improves memory quality, it goes in.

2. **Make them compound** — These techniques aren't independent. Quality grades feed spaced repetition. Spaced repetition feeds search ranking. Search ranking feeds context loading. Context loading feeds extraction quality. The system is a loop, not a list.

3. **Coexist additively** — New features layer on top. Nothing gets replaced. The contradiction detector doesn't disable the quality grader — it feeds it. The circuit breaker doesn't remove LLM calls — it protects them. Adding feature N+1 makes features 1 through N better.

4. **Predict and preempt** — What will the community need next? Build it before the Reddit post. The backlog is organized by "what insight is 3 months away from being obvious?"

---

## Total Recall vs. Claude Code's built-in auto memory

Claude Code ships with a native "auto memory" feature. It's a black box: Claude decides what to remember, stores it somewhere on Anthropic's infrastructure, and surfaces it opaquely. You can't see what's stored, can't search it, can't grade it, and can't understand why certain things are remembered and others aren't.

**Total Recall is the version you can see, own, and extend.**

| | Claude Code auto memory | Total Recall |
|--|------------------------|--------------|
| Storage | Anthropic servers (opaque) | Local `.md` files you own |
| Visibility | None — black box | Full — every memory inspectable |
| Search | Not available | Semantic + BM25 hybrid, cached |
| Quality grading | None | A/B/C/D by importance weight |
| Spaced repetition | None | FSRS-6 — science-backed retention |
| Pattern detection | None | 58 features including dream synthesis |
| Self-improvement | None | Overnight consolidation, prompt evolution |
| Methodology count | 1 (proprietary) | All of them (open, additive) |
| Control | None | Full — you decide what persists |
| Circuit breaker | None | LLM call protection with auto-recovery |

---

## What's inside (58 features, all additive)

### Foundation — the basics done right
- **Contradiction detection** — spots conflicting preferences automatically
- **Provenance tracking** — every memory tagged with session ID + resume link
- **Memory versioning** — full audit trail with rollback
- **Decision journal** — captures decisions + rationale + outcomes
- **Quality auto-grading** — A/B/C/D grades that improve extraction prompts over time

### Intelligence — the compounding layer
- **FSRS-6 spaced repetition** — science-backed retention scheduling
- **Hybrid search** — 70% semantic + 30% BM25 keyword (OpenClaw pattern)
- **Cache-aware search** — 24h TTL cache + multi-factor ranking
- **Memory clustering** — semantic grouping with divergence detection
- **Summarization** — cluster, project, period, and topic summaries

### Autonomous — the system that works while you sleep
- **Dream mode synthesis** — overnight consolidation finds hidden cross-domain connections
- **Frustration early warning** — detects repeated corrections before you spiral
- **Momentum tracking** — knows when you're "on a roll" vs "spinning"
- **Energy-aware scheduling** — learns your best thinking hours
- **Decision regret detection** — warns before you repeat a mistake for the 4th time
- **Pattern transfer** — solutions from one project surface for similar problems elsewhere
- **Prompt evolution** — genetic algorithm optimizes extraction prompts using quality grades
- **Writing style tracking** — catches unintentional drift vs intentional compression
- **Context pre-loading** — checks calendar, pre-loads relevant context before meetings

### Infrastructure — the things that keep it all running
- **Circuit breaker** — LLM calls protected with 3-failure threshold, auto-recovery
- **Connection pooling** — prevents SQLite contention under concurrent operations
- **Centralized config** — all paths/constants overridable via environment variables
- **Automated maintenance** — nightly VACUUM, ANALYZE, backups with 7-day retention

### Dashboard — see what your memory knows
- **Overview** — stat cards, grade distribution, domain breakdown, 26-week activity heatmap
- **Memory library** — searchable, filterable, click-to-detail with full content modal
- **Session history** — every session indexed with message/tool/memory counts
- **Knowledge map** — tag cloud + domain breakdown
- **Export** — JSON and CSV, one click

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
- Solution from one context could solve the other
```

### During work (real-time intelligence)

```
⚠️  Frustration detected: You've corrected "webhook" 3 times in 20 minutes.
Suggestion: Add a hook to prevent webhook errors permanently.
```

```
🤔 Pattern noticed: You chose approach X over Y in 3 similar situations.
All 3 times you later corrected to approach Y. Consider starting with Y?
```

### Query (before vs after)

**Before (traditional memory):**
```
User:      "What did we decide about the authentication approach?"
Assistant: "I don't have specific details. Can you remind me?"
```

**After (Total Recall):**
```
User:      "What did we decide about the authentication approach?"
Assistant: On March 12, you decided to use JWT with refresh tokens.
           Reasoning: Stateless, works across multiple services.
           Related: This mirrors your decision for the API project.
           [View full decision] [See session transcript]
```

---

## Architecture

**Single database strategy** — All features share `intelligence.db` with schema namespacing. Enables cross-feature queries like "show A-grade memories that triggered frustration warnings."

**Local semantic search** — sentence-transformers (`all-MiniLM-L6-v2`) for embeddings. No API costs per query. 384-dim vectors, ~50ms per memory. 90MB model, runs offline.

**Hybrid search** — 70% semantic + 30% BM25 keyword. Best of both worlds: semantic understanding + exact-match precision.

**FSRS-6 spaced repetition** — Tracks memory stability, difficulty, intervals. FAIL/HARD/GOOD/EASY grading on reinforcements. Science-backed retention.

**Connection pooling** — Prevents `SQLITE_BUSY` errors under concurrent operations. 5-connection pool with exponential backoff.

**Circuit breaker** — LLM calls protected with CLOSED/OPEN/HALF_OPEN states. 3-failure threshold, 60s recovery timeout. Separate breakers per call pathway so one failure doesn't cascade.

**Cache-aware search** — `SearchOptimizer` wraps all search with 24h TTL cache + multi-factor ranking (semantic × 0.5 + keyword × 0.2 + recency × 0.2 + importance × 0.1).

---

## Installation

**Prerequisites:** Python 3.9+, Claude API access, [memory-ts](https://github.com/nicholasgasior/memory-ts) CLI

```bash
git clone https://github.com/lee-fuhr/memory-system-v1
cd memory-system-v1

# Create venv outside cloud-synced folders
python3 -m venv ~/.local/venvs/memory-system
source ~/.local/venvs/memory-system/bin/activate

# Install as package
pip install -e .

# Run tests
pytest tests/ --ignore=tests/wild -q
```

### Configuration

Via environment variables:

```bash
export MEMORY_SYSTEM_PROJECT_ID="MyProject"
export MEMORY_SYSTEM_SESSION_DB="~/.local/share/memory/MyProject/session-history.db"
export MEMORY_SYSTEM_FSRS_DB="~/.local/share/memory/fsrs.db"
export MEMORY_SYSTEM_INTELLIGENCE_DB="~/.local/share/memory/intelligence.db"
```

Or in code:

```python
from memory_system.config import cfg
print(cfg.project_id)       # "MyProject"
print(cfg.session_db_path)  # ~/.local/share/memory/MyProject/session-history.db
```

### Dashboard

```bash
python3 dashboard/server.py --port 7860 --project MyProject
# Opens at http://localhost:7860
```

### Hook setup

Add to `~/.claude/settings.json` under `hooks.SessionEnd`:

```json
{
  "type": "command",
  "command": "~/.local/venvs/memory-system/bin/python3 /path/to/memory-system-v1/hooks/session-memory-consolidation.py",
  "timeout": 180000
}
```

---

## Usage

```python
from memory_system.automation.search import MemoryAwareSearch
from memory_system.intelligence.summarization import MemorySummarizer

# Search memories (cache-aware, multi-factor ranked)
search = MemoryAwareSearch()

results = search.search("authentication decisions")

results = search.search_natural("What did I learn about API design last month?")

results = search.search_advanced(
    text_query="deadline",
    min_importance=0.7,
    tags=["urgent"],
    order_by="relevance"
)

# Summarization
summarizer = MemorySummarizer()
summary = summarizer.get_summary("cluster-id")  # cluster summary
summary = summarizer.get_summary(42)             # topic summary
```

---

## Features (58 shipped)

| Category | Features |
|----------|----------|
| Foundation (F1–22) | Daily summaries, contradiction detection, provenance tracking, FSRS-6, session consolidation, pattern mining, conflict resolution |
| Intelligence (F23–35, F44–50) | Versioning, relationship mapping, clustering, search optimization, quality scoring, sentiment tracking, learning velocity, drift detection, voice/image/code capture, dream synthesis |
| Autonomous (F51–65, F75) | Temporal prediction, momentum tracking, energy scheduling, context pre-loading, frustration early warning, pattern transfer, writing style analysis, decision regret detection, expertise mapping, context decay prediction, prompt evolution, cascade detection |

**17 features deferred** — External integrations (F36–43, F66–74) requiring third-party APIs. Core system is complete without them.

Full feature list with test counts: [SHOWCASE.md](SHOWCASE.md)

---

## What's next (from BACKLOG.md)

The backlog predicts what the community will need next and builds it preemptively:

- **Session end hook** — automatic memory extraction on every session close
- **Memory freshness review** — weekly pruning cycle, Pushover-powered
- **Intelligence orchestrator** — the "brain stem" that wires all 58 features into a coherent system
- **Cluster-based morning briefing** — cluster summaries instead of raw memory dumps
- **Cross-client pattern transfer** — solutions from one project surface for similar problems elsewhere
- **Vector migration to ChromaDB** — scale past 5K memories
- **Memory interview** — 10-minute weekly structured review that doesn't feel like chores

Full prioritized backlog: [BACKLOG.md](BACKLOG.md)

---

## Performance

| Metric | Before | After |
|--------|--------|-------|
| Semantic search | 500s (real-time API calls) | <1s (pre-computed embeddings) |
| Session consolidation | 60s | <1s (async queue) |
| API costs at 10K scale | ~$1,000/day | ~$4/day |
| Test suite | — | 1,111 passing (99.8%) |

---

## Tech stack

**Core:** Python 3.9+ with type hints · SQLite 3.35+ with FTS5 full-text search · pytest

**AI/ML:** sentence-transformers (`all-MiniLM-L6-v2`) for local embeddings · Claude API for extraction and contradiction detection · FSRS-6 spaced repetition

**Automation:** macOS LaunchAgents for scheduled jobs · Connection pooling (queue.Queue) · Circuit breaker for LLM call protection · Exponential backoff for retry logic

---

## Credits

This system builds on the work and ideas of several people and projects:

- **[Ben Fox](https://benfox.dev/) / ZeroBot** — Reinforcement learning approach to memory quality, grading system design. The quality grading and behavioral reinforcement concepts here were directly inspired by Ben's work.
- **[FSRS-6](https://github.com/open-spaced-repetition/fsrs4anki)** — Free Spaced Repetition Scheduler algorithm for memory stability and difficulty tracking.
- **[OpenClaw](https://github.com/openclaw/openclaw)** — 70% semantic + 30% BM25 keyword hybrid search weighting pattern (145K+ stars).
- **[memory-ts](https://github.com/nicholasgasior/memory-ts)** — YAML frontmatter file-based memory storage format that this system extends.
- **r/ClaudeAI, r/ClaudeCode** — The community meta that surfaces new techniques weekly. This project exists to absorb all of them.

---

## License

MIT — see [LICENSE](LICENSE)

---

*58 features · 1,111 tests · Every methodology · All additive*
