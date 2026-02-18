# Total Recall

**Every memory technique that works. Every approach from the meta. All coexisting additively. And then predicting the next features and building those too.**

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-1256%20passing-brightgreen) ![Version](https://img.shields.io/badge/version-0.17.0-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What this is

The Claude Code memory ecosystem is exploding. Reddit posts, Ben Fox's ZeroBot, OpenClaw's hybrid search, FSRS spaced repetition, dream synthesis, frustration detection — every week someone discovers a new technique that genuinely works.

The problem: they're all separate projects. You can use Ben's quality grading OR OpenClaw's search weighting OR FSRS scheduling, but nobody's combined them. Each approach solves a real problem, but you have to pick and choose, and they don't talk to each other.

**Total Recall is the kitchen sink.** Every methodology and approach that has come through the meta, through Reddit, through the community — as long as they can coexist additively, they're in. Not "pick one approach" but "use all of them simultaneously, and let them reinforce each other."

And then: **predict what's next and build it before anyone asks.** The backlog isn't a wish list — it's a forecast.

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
| Pattern detection | None | 68 features including dream synthesis |
| Self-improvement | None | Overnight consolidation, prompt evolution |
| Methodology count | 1 (proprietary) | All of them (open, additive) |
| Control | None | Full — you decide what persists |
| Circuit breaker | None | LLM call protection with auto-recovery |

---

## What's inside

68 features across 6 layers, all additive:

### Foundation — the basics done right
Contradiction detection · provenance tracking · memory versioning · decision journal · quality auto-grading · FSRS-6 spaced repetition · importance scoring with auto-tuning

### Intelligence — the compounding layer
Hybrid search (70% semantic + 30% BM25) · cache-aware search with multi-factor ranking · semantic clustering · relationship mapping · smart alerts · quality scoring

### Autonomous — the system that works while you sleep
Dream mode synthesis · frustration early warning · momentum tracking · energy-aware scheduling · decision regret warnings · pattern transfer across projects · prompt evolution via genetic algorithm · context pre-loading before meetings

### Dashboard — see what your memory knows
Overview with heatmap · searchable memory library · session replay · knowledge map · export (JSON/CSV) · freshness indicators · intelligence briefing · cross-client patterns

### Infrastructure
Circuit breaker for LLM calls · FAISS vector store with dual-write · centralized config · async consolidation · GitHub Actions CI

**Full feature list with implementation details:** [`FEATURES.md`](FEATURES.md)

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
```

---

## Installation

### Quick setup (recommended)

Clone this repo, point Claude Code at it, and ask it to set it up:

```bash
git clone https://github.com/lee-fuhr/total-recall.git
```

Then in Claude Code:
> "Set up Total Recall from the repo I just cloned. Walk me through the configuration."

Claude will create the venv, install dependencies, configure paths, and set up the session end hook.

### Manual setup

```bash
git clone https://github.com/lee-fuhr/total-recall.git
cd total-recall

# Create venv outside cloud-synced folders
python3 -m venv ~/.local/venvs/memory-system
source ~/.local/venvs/memory-system/bin/activate

# Install
pip install -e .

# Verify
pytest tests/ --ignore=tests/wild -q
```

### Configuration

All paths configurable via environment variables:

```bash
export MEMORY_SYSTEM_PROJECT_ID="MyProject"
export MEMORY_SYSTEM_SESSION_DB="~/.local/share/memory/MyProject/session-history.db"
export MEMORY_SYSTEM_INTELLIGENCE_DB="~/.local/share/memory/intelligence.db"
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
  "command": "~/.local/venvs/memory-system/bin/python3 /path/to/total-recall/hooks/session-memory-consolidation-async.py",
  "timeout": 180000
}
```

---

## Architecture

**Single database strategy** — All features share `intelligence.db` with schema namespacing. Enables cross-feature queries like "show A-grade memories that triggered frustration warnings."

**Local semantic search** — sentence-transformers (`all-MiniLM-L6-v2`) for embeddings. No API costs per query. 384-dim vectors. Runs fully offline.

**Hybrid search** — 70% semantic + 30% BM25 keyword. Semantic understanding meets exact-match precision.

**FAISS vector store** — `IndexFlatIP` with L2-normalized inner product for cosine similarity. Dual-write architecture: FAISS for fast indexed search, SQLite fallback for compatibility.

**FSRS-6 spaced repetition** — Tracks memory stability, difficulty, and intervals. Science-backed retention scheduling.

**Circuit breaker** — LLM calls protected with CLOSED/OPEN/HALF_OPEN states. 3-failure threshold, 60s recovery timeout. Separate breakers per call pathway.

---

## Tech stack

**Core:** Python 3.11+ · SQLite 3.35+ with FTS5 full-text search · pytest

**AI/ML:** sentence-transformers (`all-MiniLM-L6-v2`) for local embeddings · FAISS for indexed vector search · Claude API for extraction and contradiction detection · FSRS-6 spaced repetition

**Automation:** macOS LaunchAgents for scheduled jobs · Circuit breaker for LLM call protection

---

## Documentation

| Doc | What it is |
|-----|-----------|
| [`FEATURES.md`](FEATURES.md) | Full feature list with implementation details |
| [`ROADMAP.md`](ROADMAP.md) | Development timeline — shipped, in progress, planned |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed and when |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to contribute |
| [Issues](https://github.com/lee-fuhr/total-recall/issues) | Feature backlog — request features here |

---

## Credits

This system builds on the work and ideas of several people and projects:

- **[Ben Fox](https://benfox.dev/) / ZeroBot** — Reinforcement learning approach to memory quality, grading system design
- **[FSRS-6](https://github.com/open-spaced-repetition/fsrs4anki)** — Free Spaced Repetition Scheduler algorithm
- **[OpenClaw](https://github.com/openclaw/openclaw)** — 70/30 semantic + BM25 hybrid search weighting pattern
- **[memory-ts](https://github.com/nicholasgasior/memory-ts)** — YAML frontmatter file-based storage format that inspired the memory file structure
- **r/ClaudeAI, r/ClaudeCode** — The community meta that surfaces new techniques weekly

---

## License

MIT — see [LICENSE](LICENSE)

---

*68 features · 1,256 tests · every methodology · all additive*
