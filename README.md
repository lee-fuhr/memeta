# memory-system-v1

Automatic memory extraction, spaced repetition review, and promotion system for [memory-ts](https://github.com/benkoo/memory-ts). Turns every Claude Code session into durable, cross-project knowledge without manual work.

**Status:** Alpha — running in production, 190 tests passing.

## What it does

1. **Session consolidation** — After each Claude Code session, automatically extracts learnings using pattern matching + LLM analysis, deduplicates against existing memories, saves to memory-ts
2. **FSRS-6 scheduling** — Tracks memory reinforcement using a simplified Free Spaced Repetition Scheduler. When the same insight appears across different sessions or projects, stability increases
3. **Pattern detection** — Compares new memories against existing ones using fuzzy word-overlap matching. Same insight from a different project = strong cross-validation signal
4. **Automatic promotion** — When a memory reaches sufficient stability, review count, and cross-project validation, it promotes from project scope to global scope
5. **Memory clustering** — Groups related memories by keyword themes for synthesis and dashboard display
6. **Weekly synthesis** — Generates a markdown draft of newly promoted memories, grouped by cluster, with push notification

## Architecture

```
Session ends (hook)
  → Extract memories (pattern + LLM)
  → Deduplicate against existing
  → Save to memory-ts
  → Detect reinforcement patterns
  → Log to FSRS scheduler

Daily (3am)
  → Decay low-importance memories
  → Archive stale memories
  → Health check

Weekly (Friday 5pm)
  → Check promotion candidates
  → Promote eligible memories (project → global)
  → Cluster and synthesize
  → Push notification
```

## Modules

| Module | Purpose | Tests |
|--------|---------|-------|
| `session_consolidator` | Extract + deduplicate memories from sessions | 35 |
| `memory_ts_client` | CRUD operations on memory-ts markdown files | 25 |
| `importance_engine` | Score memory importance (0.0–1.0) | 17 |
| `llm_extractor` | LLM-powered extraction via `claude -p` CLI | 23 |
| `fsrs_scheduler` | FSRS-6 spaced repetition (SQLite-backed) | 22 |
| `pattern_detector` | Cross-session fuzzy matching + reinforcement | 25 |
| `promotion_executor` | Project → global scope promotion | 14 |
| `memory_clustering` | Keyword-based memory grouping | 20 |
| `weekly_synthesis` | Draft generation + notification | 9 |
| **Total** | | **190** |

## Requirements

- Python 3.10+
- [memory-ts](https://github.com/benkoo/memory-ts) installed and configured
- Claude Code (for LLM extraction and session hooks)
- pytest (for running tests)

No other dependencies — uses only Python standard library + SQLite.

## Quick start

```bash
git clone https://github.com/lee-fuhr/memory-system-v1.git
cd memory-system-v1

# Run tests
python3 -m pytest tests/ -v

# Wire the SessionEnd hook (add to ~/.claude/settings.json)
```

### Hook configuration

Add to `~/.claude/settings.json` under `hooks.SessionEnd`:

```json
{
  "type": "command",
  "command": "python3 /path/to/memory-system-v1/hooks/session-memory-consolidation.py",
  "timeout": 180000
}
```

### Scheduled tasks (macOS LaunchAgents)

- **Daily maintenance** at 3am: decay, archival, health check
- **Weekly synthesis** Friday 5pm: promotion check, clustering, draft generation

Plist templates in the repo. Adapt paths for your system.

## How memories flow

```
New session
  → pattern extraction (regex-based, fast, free)
  → LLM extraction (claude -p CLI, richer but slower)
  → deduplicate (70% word overlap = duplicate)
  → save to memory-ts (scope: project)
  → pattern detection against all existing memories (50% overlap = reinforcement)
  → FSRS records review (GOOD=same project, EASY=cross-project)
  → stability grows → interval grows
  → after 3+ reviews, 2+ projects, stability 3.0+ → PROMOTED
  → scope changes to global, #promoted tag added
  → weekly synthesis collects promoted memories → draft → notification
```

## FSRS grading

| Grade | When | Stability multiplier |
|-------|------|---------------------|
| FAIL (1) | Memory contradicted or invalidated | ×0.5 |
| HARD (2) | Memory not reinforced (weak signal) | ×0.8 |
| GOOD (3) | Same insight, same project | ×1.5 |
| EASY (4) | Same insight, different project | ×2.2 |

## Promotion criteria

All must be met:

- Stability ≥ 3.0 (well-established)
- Review count ≥ 3 (seen multiple times)
- Validated in 2+ different projects (cross-project signal)
- Not already promoted

## Memory health

The system prevents unbounded growth through:

- **Importance decay** — Low-value memories fade over time (daily maintenance)
- **Archival** — Stale memories with no reinforcement get archived
- **Deduplication** — 70% word overlap threshold prevents duplicates at capture time
- **Promotion filtering** — Only cross-project validated patterns make it to global scope

## License

MIT
