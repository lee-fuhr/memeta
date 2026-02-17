# Engram

**A Claude Code memory framework that learns from your behavior, finds hidden patterns, and gets smarter while you sleep.**

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-1085%20passing-brightgreen) ![Version](https://img.shields.io/badge/version-0.12.0-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Engram vs. Claude Code's built-in Auto Memory

Claude Code ships with a native "Auto Memory" feature. It's a black box: Claude decides what to remember, stores it somewhere on Anthropic's infrastructure, and surfaces it opaquely. You can't see what's stored, can't search it, can't grade it, and can't understand why certain things are remembered and others aren't.

**Engram is the version you can see.**

| | Claude Code Auto Memory | Engram |
|--|------------------------|---------|
| Storage | Anthropic servers (opaque) | Local `.md` files you own |
| Visibility | None — black box | Full — every memory inspectable |
| Search | Not available | Semantic + BM25 hybrid, instant |
| Quality grading | None | A/B/C/D by importance weight |
| Spaced repetition | None | FSRS-6 — science-backed retention |
| Pattern detection | None | 58 features including dream synthesis |
| Self-improvement | None | Overnight consolidation, prompt evolution |
| Control | None | Full — you decide what persists |

If the built-in feature works for you, great. Engram is for people who want to understand, inspect, and actively improve their AI's memory rather than just hoping it learned the right things.

---

## The problem with memory systems

Traditional memory systems are glorified search engines. You tell them what to remember. They store it. You search for it later. That's it.

**The real problem:** You don't know what you don't know. You can't search for insights you haven't discovered yet. You can't predict which details will matter three months from now. And you definitely can't spot patterns across thousands of memories at 3am while you're sleeping.

**What breaks:**
- You repeat the same mistake three times before noticing the pattern
- Important context gets buried under noise
- Contradicting information sits side-by-side with no warning
- Your AI partner keeps making the same errors despite corrections
- Insights that should emerge from your work... don't

**The gap:** The difference between "search engine with markdown files" and "thinking partner that learns from your behavior" is the difference between a filing cabinet and a second brain.

---

## What this system does differently

**Instead of asking you to remember everything, it remembers for you. Instead of waiting for you to search, it finds patterns proactively. Instead of staying static, it learns from your corrections and gets smarter while you sleep.**

### You get a memory system that:

**Learns from your behavior** — Not what you say, what you *do*. It tracks which memories you reinforce, which you contradict, which you never recall. It learns what makes a good memory by watching which ones actually help you.

**Works while you sleep** — Overnight consolidation finds hidden connections across all your memories. You wake up to insights like "these 5 problems share the same root cause" or "your best outputs follow this pattern."

**Catches mistakes before they compound** — Detects frustration patterns *before* you spiral. "You've corrected this same thing 3 times in 20 minutes — should we add a hook to prevent it permanently?"

**Predicts what you'll need** — It's Monday morning. You have a meeting at 2pm. The system pre-loads relevant context, recent decisions, and open questions before you even ask.

**Improves extraction quality** — Grades every memory A/B/C/D based on whether it actually helped you later. Learns what makes good memories. Updates prompts automatically. Gets better at capturing what matters.

**Never loses context** — Every session, every message indexed and searchable. "What did we decide about authentication three months ago?" becomes instant, not impossible.

---

## Core capabilities

### Intelligence you don't have to maintain

**Contradiction detection** — Spots conflicting preferences automatically. "You said X on Tuesday, Y on Friday — which is current?" Resolves ambiguity before it causes problems.

**Provenance tracking** — Every memory tagged with session ID. "When did I say that?" shows you the exact conversation, with resume link. Context never gets lost.

**Memory versioning** — Track changes over time. Rollback to previous versions. Full audit trail. "Why did this change?" becomes answerable.

**Decision journal** — Captures decisions + rationale + outcomes. Learns from regret patterns. "You chose X over Y three times and regretted it each time — consider Y this time?"

**Quality auto-grading** — Grades every memory A/B/C/D. Learns what traits your best memories share. Updates extraction prompts based on patterns. Self-improving quality.

### Learning that compounds over time

**Sentiment tracking** — Detects frustration vs satisfaction trends. Triggers optimizations when mood drops. Emotional intelligence about your work state.

**Learning velocity** — Measures how fast you're learning topics. Correction rate by domain. Acceleration detection. "You're getting better at X, plateauing on Y."

**Personality drift detection** — Tracks communication style evolution. "Your headlines compressed 20% over 3 months — intentional?" Catches unintentional changes.

**Frustration early warning** — Detects repeated corrections, topic cycling, negative sentiment patterns. Intervenes *before* you spiral.

**Writing style evolution** — Tracks style changes over time with metrics (directness, verbosity, formality). Distinguishes intentional compression from drift.

### Multimodal memory capture

**Voice memory capture** — Audio transcription → structured memories. Capture ideas while moving. "Find that idea I recorded on the way home."

**Image context extraction** — OCR + vision analysis on screenshots. Searchable visual memories. "Find that mockup screenshot from last week."

**Code pattern library** — Personal Stack Overflow. Save solutions with context. Semantic search. "How did I solve async rate limiting before?"

**Session history** — All sessions fully indexed. Never lose context. "What approaches did we try for authentication?" with instant answers.

### Self-improvement that runs overnight

**A/B testing strategies** — System experiments on itself. Tests semantic vs keyword search, dedup thresholds, prompt variations. Auto-adopts winners at 95% confidence.

**Dream mode synthesis** — Overnight consolidation finds hidden connections across *all* memories. Cross-domain insights. Morning briefing with synthesis.

**Prompt evolution** — Genetic algorithm optimizes extraction prompts. Population of 10 variants, evolve based on quality grades. Self-improving extraction.

**Pattern mining** — Detects temporal patterns, frequency spikes, sequential patterns ("After discussing X, you usually need Y").

**Conversation momentum tracking** — Detects when you're "on a roll" vs "stuck spinning." Tracks insights, decisions, repeated questions, topic cycling.

**Energy-aware scheduling** — Learns your best thinking hours. Maps task cognitive load. Suggests "Write that proposal at 9am, do email triage at 3pm."

**Context pre-loading** — Checks calendar 60min ahead. Pre-loads relevant context for upcoming work. Zero wait time when you start.

**Decision regret detection** — "You've made this decision 3 times and regretted it twice (67%)." Warns before repeating mistakes.

**Expertise mapping** — Tracks which agents know what. Automatic routing to best agent per domain. Self-organizing knowledge graph.

**Context decay prediction** — Predicts staleness before it happens. Proactive maintenance, not reactive cleanup.

**Mistake cascade detector** — Root cause cascade analysis. "Root error spawned 3 downstream failures." Suggests prevention by cascade depth.

---

## How it works in practice

### Morning (Wake up to insights)

```
Daily summary (auto-generated overnight):

Key insights extracted:
- Learned: New preference for async communication on long projects
- Pattern: 3rd time fixing same issue → hook needed
- Decision: Chose SQLite over Postgres for local storage

Sentiment: Satisfied (7/10)
Frustration spike: 3-4pm during debugging session
Resolution: Found solution in code memory library

Learning velocity:
- Client work: +15% (accelerating)
- Dev infrastructure: +5% (steady)
- Marketing: -10% (needs attention)

Dream synthesis (3am run):
- Approach for Project A maps to Project B's problem
- Both struggle with the same underlying constraint
- Solution from one context could solve the other
```

### During work (Real-time intelligence)

```
⚠️  Frustration detected: You've corrected "webhook" 3 times in 20 minutes.
Suggestion: Add a hook or verification step to prevent webhook errors permanently.
[ Create Hook ] [ Ignore ]
```

```
📊 Style shift detected: Headlines compressed from 8 words → 5 words over last month.
This appears intentional (consistent trend). Documenting as preference.
```

```
🤔 Pattern noticed: You chose approach X over Y in 3 similar situations.
All 3 times you later corrected to approach Y.
Consider starting with Y this time?
```

### Query (Before vs after)

**Before (traditional memory):**
```
User:      "What did we decide about the authentication approach?"
Assistant: "I don't have specific details. Can you remind me?"
```

**After (this system):**
```
User:      "What did we decide about the authentication approach?"
Assistant: On March 12, you decided to use JWT with refresh tokens.
           Reasoning: Stateless, works across multiple services.

           Related: This mirrors your decision for the API project.

           Status: Implementation complete, tests passing.
           Next: Documentation update pending.

           [View full decision] [See session transcript]
```

---

## Architecture

**Single database strategy** — All features share `intelligence.db` with schema namespacing. Enables cross-feature queries like "Show A-grade memories that triggered frustration warnings."

**Local semantic search** — sentence-transformers (`all-MiniLM-L6-v2`) for embeddings. No API costs per query. 384-dim vectors, ~50ms per memory. 90MB model, runs offline.

**Hybrid search** — 70% semantic + 30% BM25 keyword. Best of both worlds: semantic understanding + exact-match precision.

**FSRS-6 spaced repetition** — Tracks memory stability, difficulty, intervals. FAIL/HARD/GOOD/EASY grading on reinforcements. Science-backed retention.

**Connection pooling** — Prevents `SQLITE_BUSY` errors under concurrent operations. 5-connection pool with exponential backoff.

**Cache-aware search** — `SearchOptimizer` wraps all search with 24h TTL cache + multi-factor ranking (semantic × 0.5 + keyword × 0.2 + recency × 0.2 + importance × 0.1).

**Automated maintenance** — Nightly VACUUM, ANALYZE, backups with 7-day retention. Pre-computed embeddings eliminate real-time API calls.

---

## Installation

**Prerequisites:** Python 3.9+, Claude API access, [memory-ts](https://github.com/nicholasgasior/memory-ts) CLI

```bash
git clone https://github.com/your-username/memory-system-v1
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

## Performance

| Metric | Before | After |
|--------|--------|-------|
| Semantic search | 500s (real-time API calls) | <1s (pre-computed embeddings) |
| Session consolidation | 60s | <1s (async queue) |
| API costs at 10K scale | ~$1,000/day | ~$4/day |
| Test suite | — | 1,085 passing (99.6%) |

---

## Tech stack

**Core:** Python 3.9+ with type hints · SQLite 3.35+ with FTS5 full-text search · pytest

**AI/ML:** sentence-transformers (`all-MiniLM-L6-v2`) for local embeddings · Claude API for extraction and contradiction detection · FSRS-6 spaced repetition

**Automation:** macOS LaunchAgents for scheduled jobs · Connection pooling (queue.Queue) · Exponential backoff for retry logic

---

## Credits

This system builds on the work and ideas of several people and projects:

- **[Ben Fox](https://benfox.dev/) / ZeroBot** — Reinforcement learning approach to memory quality, grading system design. The quality grading and behavioral reinforcement concepts here were directly inspired by Ben's work.
- **[FSRS-6](https://github.com/open-spaced-repetition/fsrs4anki)** — Free Spaced Repetition Scheduler algorithm for memory stability and difficulty tracking.
- **[OpenClaw](https://github.com/openclaw/openclaw)** — 70% semantic + 30% BM25 keyword hybrid search weighting pattern (145K+ stars).
- **[memory-ts](https://github.com/nicholasgasior/memory-ts)** — YAML frontmatter file-based memory storage format that this system extends.

---

## License

MIT — see [LICENSE](LICENSE)

---

*58 features · 1,085 tests · Production-ready*
