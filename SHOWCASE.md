# Memory Intelligence System

**Status:** v0.10.0 | 1085/1089 tests passing (99.6%) | 58 features shipped
**Updated:** 2026-02-15

---

## The problem with memory systems

Traditional memory systems are glorified search engines. You tell them what to remember. They store it. You search for it later. That's it.

**The real problem:** You don't know what you don't know. You can't search for insights you haven't discovered yet. You can't predict which details will matter three months from now. And you definitely can't spot patterns across 2,300 memories at 3am while you're sleeping.

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

**Learns from your behavior** - Not what you say, what you *do*. It tracks which memories you reinforce, which you contradict, which you never recall. It learns what makes a good memory by watching which ones actually help you.

**Works while you sleep** - Overnight consolidation finds hidden connections across all your memories. You wake up to insights like "these 5 client problems share the same root cause" or "your best headlines follow this pattern."

**Catches mistakes before they compound** - Detects frustration patterns *before* you spiral. "You've corrected this same thing 3 times in 20 minutes - should we add a hook to prevent it permanently?"

**Predicts what you'll need** - It's Monday morning. You have a Connection Lab call at 2pm. The system pre-loads their messaging framework, recent decisions, and open questions before you even ask.

**Improves extraction quality** - Grades every memory A/B/C/D based on whether it actually helped you later. Learns what makes good memories. Updates prompts automatically. Gets better at capturing what matters.

**Never loses context** - 779 sessions, 177K messages indexed and searchable. "What did we decide about authentication three months ago?" becomes instant, not impossible.

---

## Core capabilities

### Intelligence you don't have to maintain

**Contradiction detection** - Spots conflicting preferences automatically. "You said X on Tuesday, Y on Friday - which is current?" Resolves ambiguity before it causes problems.

**Provenance tracking** - Every memory tagged with session ID. "When did I say that?" shows you the exact conversation, with resume link. Context never gets lost.

**Memory versioning** - Track changes over time. Rollback to previous versions. Full audit trail. "Why did this change?" becomes answerable.

**Decision journal** - Captures decisions + rationale + outcomes. Learns from regret patterns. "You chose X over Y three times and regretted it each time - consider Y this time?"

**Quality auto-grading** - Grades every memory A/B/C/D. Learns what traits your best memories share. Updates extraction prompts based on patterns. Self-improving quality.

### Learning that compounds over time

**Sentiment tracking** - Detects frustration vs satisfaction trends. Triggers optimizations when mood drops. Emotional intelligence about your work state.

**Learning velocity** - Measures how fast you're learning topics. Correction rate by domain. Acceleration detection. "You're getting better at X, plateauing on Y."

**Personality drift detection** - Tracks communication style evolution. "Your headlines compressed 20% over 3 months - intentional?" Catches unintentional changes.

**Frustration early warning** - Detects repeated corrections, topic cycling, negative sentiment patterns. Intervenes *before* you spiral. "Add a hook to prevent this forever?"

**Writing style evolution** - Tracks style changes over time with metrics (directness, verbosity, formality). Distinguishes intentional compression from drift.

### Multimodal memory capture

**Voice memory capture** - Audio transcription → structured memories. Capture ideas while driving. "Find that idea I recorded on the way home."

**Image context extraction** - OCR + vision analysis on screenshots. Searchable visual memories. "Find that Figma mockup screenshot from last week."

**Code pattern library** - Personal Stack Overflow. Save solutions with context. Semantic search. "How did I solve async rate limiting before?"

**Meeting intelligence** - 1,900+ transcripts indexed and searchable. Extract commitments, personal intel, follow-ups. Auto-generated dossiers 60min before meetings.

**Session history** - 779 sessions, 177K messages fully indexed. Never lose context. "What approaches did we try for authentication?" with instant answers.

### Self-improvement that runs overnight

**A/B testing strategies** - System experiments on itself. Tests semantic vs keyword search, dedup thresholds, prompt variations. Auto-adopts winners at 95% confidence.

**Dream mode synthesis** - Overnight consolidation finds hidden connections across *all* memories. Cross-domain insights. Morning briefing with synthesis.

**Prompt evolution** - Genetic algorithm optimizes extraction prompts. Population of 10 variants, evolve based on quality grades. Self-improving extraction.

**Cross-system learning** - Imports patterns from other tools. Tracks what you adapted and rates effectiveness. "This worked for Tool A, try for Tool B?"

**Pattern mining** - Detects temporal patterns ("Every Monday you need X"), frequency patterns (topics that spike), sequential patterns ("After discussing X, you usually need Y").

**Conversation momentum tracking** - Detects when you're "on a roll" vs "stuck spinning." Tracks insights, decisions, repeated questions, topic cycling. Suggests interventions when stuck: "Take a break" or "Pick one topic and go deep."

**Energy-aware scheduling** - Learns your best thinking hours. Maps task cognitive load (deep_work vs admin). Suggests "Write that proposal at 9am, do email triage at 3pm." Adaptive to your natural energy curve.

**Context pre-loading** - Checks calendar 60min ahead. Pre-loads relevant context for upcoming meetings. "Connection Lab context ready before 2pm call." Zero wait time when work starts.

**Pattern transfer across clients** - "You solved this for Client A, Client B has same problem." Suggests cross-pollinating solutions. Tracks effectiveness ratings. Privacy-aware learning.

**Decision regret detection** - "You've made this decision 3 times and regretted it twice (67%)." Warns before repeating mistakes. Learns from correction patterns.

**Expertise mapping** - "Agent1 is your Python expert (score: 60), Agent2 for Rust (score: 42)." Automatic routing to best agent per domain. Self-organizing knowledge graph.

**Context decay prediction** - Predicts staleness before it happens. "These 12 memories become stale next week - review them?" Proactive maintenance, not reactive cleanup.

**Learning intervention system** - "You've asked 'How do I X' 5 times." Suggests creating tutorial/reference. Auto-generates learning resources. Tracks if interventions helped.

**Mistake cascade detector** - "Root error spawned 3 downstream failures." Analyzes cascade depth, suggests prevention strategies by depth. "Add circuit breaker after first error."

---

## How it works in practice

### Morning (Wake up to insights)

**Daily summary** (auto-generated at 11:55pm):
```
Key insights extracted:
- Learned: Connection Lab prefers async communication
- Pattern: 3rd time fixing same Webflow issue → hook needed
- Decision: Chose Notion over Airtable for CRM

Sentiment: Satisfied (7/10)
Frustration spike: 3-4pm during Webflow debugging
Resolution: Found solution in code memory library

Learning velocity:
- Client work: +15% (accelerating)
- Dev infrastructure: +5% (steady)
- Marketing: -10% (needs attention)
```

**Dream synthesis** (runs at 3am):
```
Hidden connections found:
- Your Cogent messaging approach maps to Connection Lab problem
- Both clients struggle with "boring B2B" positioning
- Solution from Client A could solve Client B's challenge

Quality patterns discovered:
- Your A-grade memories all include "why" reasoning
- Recommendation: Updated extraction prompt to ask for reasoning
```

### During work (Real-time intelligence)

**Frustration detection:**
```
⚠️ Frustration detected: You've corrected "webhook" 3 times in 20 minutes.

Suggestion: Add a hook or verification step to prevent webhook errors permanently.

[ Create Hook ] [ Ignore ]
```

**Writing style evolution:**
```
📊 Style shift detected: Headlines compressed from 8 words → 5 words over last month.

This appears intentional (consistent trend). Documenting as preference.
```

**Decision regret prevention:**
```
🤔 Pattern noticed: You chose approach X over Y in 3 similar situations.

All 3 times you later corrected to approach Y.

Consider starting with Y this time?
```

### Evening (Quality review)

**Memory quality report:**
```
Quality grades today:
- A-grade: 12 memories (precise, actionable, evidence-backed)
- B-grade: 8 memories (good, could be more specific)
- C-grade: 3 memories (vague, needs improvement)

Pattern: Your best memories include specific examples.
Action: Updated extraction prompt to ask for examples.
```

---

## Architecture highlights

**Single database strategy** - All features share `intelligence.db` with schema namespacing. Enables cross-feature queries like "Show A-grade memories that triggered frustration warnings."

**Local semantic search** - sentence-transformers (all-MiniLM-L6-v2) for embeddings. No API costs. 384-dim vectors, ~50ms per memory. 90MB model.

**Hybrid search** - 70% semantic + 30% BM25 keyword (OpenClaw pattern). Best of both worlds.

**FSRS-6 spaced repetition** - Tracks memory stability, difficulty, intervals. FAIL/HARD/GOOD/EASY grading on reinforcements.

**Connection pooling** - Prevents SQLITE_BUSY errors under concurrent operations. 5-connection pool with exponential backoff.

**Automated maintenance** - Nightly VACUUM, ANALYZE, backups with 7-day retention. Pre-computed embeddings eliminate real-time API calls.

---

## Complete feature roadmap (58 shipped, 17 deferred)

### Features 1-22: Foundation ✅ SHIPPED

Core memory infrastructure - daily summaries, contradiction detection, provenance tagging, roadmap/changelog pattern, LLM dedup, pre-compaction flush, context compaction, correction promotion, cross-agent queries, lifespan prediction, pattern mining, conflict resolution UI, session consolidation, FSRS-6 scheduling.

### Features 23-50: Intelligence enhancement (20 shipped, 8 deferred)

**F23: Memory versioning** ✅ (21 tests)
Track every change to memories over time. Rollback to previous versions. Full audit trail with change reasons.

**F24: Relationship mapping** ✅ (28 tests) | **F25: Clustering** ✅ (17 tests) | **F26: Summarization** ✅ (17 tests) | **F27: Reinforcement scheduler** ✅ (24 tests) | **F28: Search optimization** ✅ (14 tests) | **F29: Smart alerts** ✅ (16 tests) | **F30: Memory-aware search** ✅ (16 tests) | **F31: Auto-summarization** ✅ (14 tests) | **F32: Quality scoring** ✅ (13 tests)

**F33: Sentiment tracking** ✅ (5 tests)
Detect frustration vs satisfaction trends. Trigger optimizations when mood drops. Emotional intelligence.

**F34: Learning velocity** ✅ (5 tests)
Measure learning rate by topic. Correction rate tracking. Acceleration detection. ROI on memory investments.

**F35: Personality drift detection** ✅ (10 tests)
Track communication style evolution. Detect compression vs drift. Directness, verbosity, formality metrics.

**F44: Voice memory capture** ✅ (13 tests)
Audio → structured memories. MacWhisper integration. "Find that idea I recorded driving home."

**F45: Image context extraction** ✅ (5 tests)
OCR + Claude vision for screenshots. Searchable visual memories. "Find that Figma mockup screenshot."

**F46: Code pattern library** ✅ (5 tests)
Personal Stack Overflow. Semantic search across solutions. "How did I solve async rate limiting?"

**F47: Decision journal** ✅ (4 tests)
Track decisions + outcomes. Learn from regret patterns. Prevent repeated mistakes.

**F48: A/B testing strategies** ✅ (4 tests)
System experiments on itself. Tests search methods, dedup thresholds. Auto-adopts winners at 95% confidence.

**F49: Cross-system learning** ✅ (4 tests)
Import patterns from other tools. Track effectiveness. Knowledge transfer across systems.

**F50: Dream mode synthesis** ✅ (3 tests)
Overnight consolidation + synthesis. Finds hidden connections. Morning briefing with insights.

**F36-43: External integrations** 🚫 DEFERRED
*Deferred: External integration features. Core system complete without them.*

### Features 51-75: Autonomous intelligence (16 shipped, 9 deferred)

**F51: Temporal pattern prediction** ✅ (12 tests)
Predict needs before asking. Temporal pattern detection across memories.

**F52: Conversation momentum tracking** ✅ (14 tests)
Detect "on a roll" vs "stuck spinning." Track insights, decisions, topic cycling. Suggest interventions.

**F53: Energy-aware scheduling** ✅ (12 tests)
Learn best thinking hours. Map cognitive load. Suggest optimal task scheduling.

**F54: Context pre-loading** ✅ (12 tests)
Check calendar ahead. Pre-load relevant context before work starts. Zero wait time.

**F55: Frustration early warning** ✅ (9 tests)
Detects frustration *before* it peaks. Signals: repeated corrections, topic cycling, negative sentiment.

**F56: Client pattern transfer** ✅ (12 tests)
Cross-pollinate insights across clients. Privacy-aware learning. Effectiveness tracking.

**F57: Writing style analyzer** ✅ (18 tests)
Track style evolution with quantified metrics. Compression, directness, formality trends.

**F58: Decision regret detection** ✅ (14 tests)
Learn from repeated mistakes. Warn before repeating regretted decisions.

**F59: Expertise mapping** ✅ (14 tests)
Track which agents know what. Automatic routing to best agent per domain.

**F60: Context decay prediction** ✅ (14 tests)
Predict staleness before it happens. Proactive maintenance, not reactive cleanup.

**F61: A/B testing memory strategies** ✅ (14 tests)
Automated experimentation on memory extraction and retrieval approaches.

**F62: Memory quality auto-grading** ✅ (15 tests)
Grades every memory A/B/C/D. Learns from behavior. Auto-improves extraction quality.

**F63: Prompt evolution** ✅ (15 tests)
Genetic algorithm for extraction prompts. Population of 10 variants evolves weekly based on quality grades. 9 mutation operators, crossover breeding, auto-adoption at 95% confidence.

**F64: Learning intervention system** ✅ (14 tests)
"You've asked 'How do I X' 5 times." Suggests creating tutorial/reference. Tracks if interventions helped.

**F65: Mistake compounding detector** ✅ (14 tests)
Root cause cascade analysis. Analyzes cascade depth, suggests prevention strategies.

**F66-74: External integrations** 🚫 DEFERRED
- F66: Screenshot context extraction
- F67: Voice tone analysis
- F68: Meeting intelligence v3
- F69: Email pattern learning v2
- F70: Notion bidirectional sync
- F71: Git commit learning
- F72: Code review learning
- F73: Documentation gap detection
- F74: Curiosity-driven exploration

*Deferred: External integrations requiring third-party APIs. Core system complete without them.*

**F75: Dream synthesis enhanced** ✅ (16 tests)
Advanced overnight consolidation. Cross-domain insights across ALL memories.

---

## Status summary

**58 features shipped** - Production-ready with code + tests + docs
**17 features deferred** - External integrations, intentionally skipped

**Test coverage:** 765/767 passing (99.7%), 2 skipped, 0 failures
**Production code:** ~12,000 lines of Python
**Documentation:** 2,000+ lines across API docs, guides, examples
**Database:** Session history (779 sessions, 177K messages), intelligence.db (shared schema)

---

## What makes this production-ready

**Not a prototype.** Every shipped feature has:
- ✅ Complete implementation
- ✅ Comprehensive test suite (>80% coverage)
- ✅ API documentation
- ✅ Integration playbooks
- ✅ Error handling + retry logic
- ✅ Performance optimization

**Built for reliability:**
- Connection pooling prevents SQLITE_BUSY errors
- Exponential backoff on LLM failures
- Atomic writes prevent corruption
- Nightly backups with 7-day retention
- Pre-computed embeddings eliminate API timeouts

**Built for performance:**
- Semantic search: 500s → <1s (pre-computed embeddings)
- Session consolidation: 60s → <1s (async queue)
- API costs: $1,000/day → $4/day at 10K scale
- Performance grade: B+ (LLM retry handling, connection pooling with WAL mode, bounded caches)

**QA hardening (4-agent swarm):**
- Code quality, test coverage, data integrity, performance — reviewed by dedicated agents
- Critical fixes applied: bounded LRU caches (max 1000 entries), SQL injection whitelist, missing DB indices added, package init cleanup, legacy stubs deleted
- Design review (2-agent pass): feature coherence audit identified organizational debt (not bugs) — feature overlap documented for future refactoring

---

## Comparison: Before vs after

### Before (Traditional memory)

```
User: "What did we decide about Connection Lab messaging?"Assistant: *searches memories*
Assistant: "I don't have specific details. Can you remind me?"
```

### After (Intelligence system)

```
User: "What did we decide about Connection Lab messaging?"
Assistant: *searches memories + session history + decision journal*
Assistant: "On Jan 21, you decided to lead with transformation over tactics.
           Reasoning: Their buyers are overwhelmed executives, not implementers.

           Related: This mirrors your Cogent approach (both avoid feature lists).

           Status: Emma Stratton messaging framework created.
           Next: Copywriter needs to draft homepage hero.

           [View full decision] [See session transcript]"
```

---

## Installation & usage

**Prerequisites:**
- Python 3.9+
- memory-ts CLI installed
- macOS (for LaunchAgents automation)

**Setup:**
```bash
cd "_ Operations/memory-system-v1"

# Install dependencies
pip install -r requirements.txt

# Initialize intelligence database
python scripts/init_intelligence_db.py

# Seed session history
python scripts/seed_session_history_v2.py

# Run tests
pytest tests/ -v

# Set up automation (optional)
cp launch-agents/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.memory.*
```

**Usage examples:**
```python
from src.intelligence_db import IntelligenceDB

# Track sentiment
db = IntelligenceDB()
db.track_sentiment(score=7, notes="Productive day, solved auth bug")

# Grade memory
db.grade_memory(memory_id="mem123", grade="A", rationale="Precise, actionable, evidence-backed")

# Query learning velocity
velocity = db.get_learning_velocity(domain="client-work", days=30)
```

---

## Tech stack

**Core:**
- Python 3.9+ with type hints
- SQLite 3.35+ with FTS5 full-text search
- pytest for testing
- YAML frontmatter (memory-ts storage)

**AI/ML:**
- sentence-transformers (all-MiniLM-L6-v2) for local embeddings
- Claude API for LLM extraction, contradiction detection
- FSRS-6 algorithm for spaced repetition

**Automation:**
- macOS LaunchAgents for scheduled jobs
- Connection pooling (queue.Queue) for concurrency
- Exponential backoff for retry logic

---

## Credits & inspiration

**Inspired by:**
- Ben Fox's ZeroBot/Kit memory system - Reinforcement learning, quality grading
- FSRS-6 spaced repetition - Stability/difficulty tracking
- OpenClaw hybrid search - 70% semantic + 30% keyword pattern
- memory-ts storage - YAML frontmatter, file-based memories

**Built by:** Multi-agent dev team (dev-director, dev-senior, dev-junior, wild-architect)
**Orchestrated by:** Conductor agent
**Time:** Concept to 57 shipped features, QA-hardened and design-reviewed

**Key insight:** Teams ship 10x faster when you enforce quality (code + tests + docs) vs accepting "it's done" without verification.

---

*Last updated: 2026-02-15*
*Version: 0.9.0*
*Status: 58 features production-ready, 1086/1088 tests passing (99.8%)*
*Vision: Autonomous memory that thinks alongside you*

---

## Progress log

What's been done, most recent first.

**2026-02-15 — v0.10.0: Config centralization**
- Created `src/config.py` — `MemorySystemConfig` frozen dataclass, module singleton `cfg`
- All hardcoded paths now overridable via `MEMORY_SYSTEM_*` env vars
- Updated 5 source files to use `cfg` instead of inline `Path.home()` / relative `Path(__file__)` constructs
- Fixed sys.modules mock in test_search_optimizer.py (old module name → new package name)

**2026-02-15 — v0.9.0: Package infrastructure + import cleanup**
- Created `pyproject.toml` — package now installable via `pip install -e .`
- Removed all 71 sys.path hacks across tests, source, hooks, and scripts
- All imports now use `from memory_system.X import ...` — no more fragile path manipulation
- Created `conftest.py` at project root
- Venv at `~/.local/venvs/memory-system/`

**2026-02-15 — v0.8.1: Critical infrastructure tests**
- Added 322 new tests across 5 previously untested modules: db_pool (50), embedding_manager (62), semantic_search (72), hybrid_search (73), session_history_db (65)
- Fixed 3 bugs in session_history_db.py found during test writing (docstring syntax, indentation errors, FTS5 bad reference)
- Total: 1086 passing (was 765)

**2026-02-13 — v0.8.0: F63 + docs**
- Discovered F63 (prompt evolution) was already built but marked as unshipped — updated all docs
- 58 features now correctly documented

**2026-02-13 — v0.7.0: QA + design passes**
- 4-agent QA swarm: code quality, test coverage, data integrity, performance
- Critical fixes: bounded LRU caches, SQL injection whitelist, missing DB indices, automation/__init__.py, 3 legacy stubs deleted
- 2-agent design pass: feature coherence + API surface review
- 765 tests passing, 0 failing

**2026-02-13 — v0.6.0: All 58 features complete**
- Fixed 8 failing tests (API mismatches, import contamination)
- Expanded F61 A/B testing: 4 → 14 tests
- Expanded F75 dream synthesis: 4 → 16 tests
- All 57+1 features verified working
