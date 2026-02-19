# Total Rekall — project instructions

**Version:** 0.19.0
**Last updated:** 2026-02-19

---

## What this is

Intelligent memory system for Claude Code. 72 features, 1,079 tests, Python 3.11+. Extracts knowledge from sessions, grades it, searches it semantically, and synthesizes insights across projects.

**Architecture:** Memory files (YAML frontmatter + markdown) at `~/.local/share/memory/LFI/memories/`. Intelligence layer in `intelligence.db` (SQLite). FAISS vector store for semantic search. Flask dashboard at localhost:8766.

**Python package:** `memory_system` (mapped to `src/` via pyproject.toml). All imports use `from memory_system.X import Y`.

---

## File organization

```
src/                        # Core modules (memory_system package)
src/intelligence/           # Intelligence layer (clustering, orchestrator, vectors)
src/automation/             # Autonomous features (dream mode, consolidation)
src/multimodal/             # Voice capture, image analysis
src/wild/                   # Experimental features (energy, frustration, regret, etc.)
tests/                      # Mirror of src/ structure
tests/wild/                 # Wild feature tests (excluded from CI: --ignore=tests/wild)
dashboard/                  # Flask server + single-page HTML dashboard
hooks/                      # Claude Code hook scripts
scripts/                    # CLI utilities and maintenance scripts
launch-agents/              # macOS LaunchAgent plists
examples/                   # Usage examples
docs/features/              # Feature detail documentation (user-facing)
_internal/                  # Dev planning docs (gitignored — gap analysis, specs, plans)
```

---

## Development workflow

### Before writing ANY code

1. **Check for existing implementation** — grep `src/` before building. Features may exist but be undocumented.
2. **Write tests first (TDD)** — create `tests/[module]/test_[feature].py` with red tests before writing source.
3. **Check dependencies** — what does this feature need? What will use it?

### Implementation cycle

1. **Tests (red)** — Write comprehensive tests. Minimum 10-15 per feature. Target 20-30 for complex features.
2. **Source (green)** — Implement in `src/[module]/[feature].py`. Run tests until green.
3. **Dashboard endpoint** — If feature has queryable data, add `/api/[feature]` endpoint to `dashboard/server.py`.
4. **Documentation** — Update CHANGELOG.md, FEATURES.md, README.md as needed.
5. **Commit** — Conventional commit format (see below). Push to main.

### Quality gates (mandatory before moving on)

- [ ] Feature tests: 100% passing
- [ ] Full suite: no regressions (`pytest tests/ -q --ignore=tests/wild --tb=short`)
- [ ] CHANGELOG.md updated (feature added to current version)
- [ ] FEATURES.md updated (if new feature)
- [ ] Git: committed and pushed

**If any gate fails:** Stop and fix before proceeding.

---

## Testing

**Run all tests:**
```bash
cd /Users/lee/CC/LFI/_ Operations/memory-system-v1
~/.local/venvs/memory-system/bin/python3 -m pytest tests/ -q --ignore=tests/wild --tb=short
```

**Run specific module:**
```bash
~/.local/venvs/memory-system/bin/python3 -m pytest tests/intelligence/test_clustering.py -v
```

**CI runs:** Python 3.11, 3.12, 3.13 via GitHub Actions on push to main.

**Test organization:**
- `tests/` mirrors `src/` structure
- `tests/wild/` excluded from CI (experimental features, may need special deps)
- Each test file self-contained (creates temp dirs, temp DBs, cleans up)

**Coverage expectations:**
- Per feature: 10-15 tests minimum, 20-30 for complex features
- Full suite must maintain or improve pass rate
- No previously passing test may break

---

## Commit format

```
<type>(<scope>): <subject>

- Key change 1
- Key change 2
- Test coverage summary

Co-Authored-By: Claude <model> <noreply@anthropic.com>
```

**Types:** `feat` (new feature), `fix` (bug fix), `docs` (documentation), `refactor` (restructure), `test` (test changes), `chore` (maintenance)

---

## Documentation rules

### What to update when

| When you... | Update... |
|-------------|-----------|
| Ship a new feature | CHANGELOG.md, FEATURES.md |
| Fix a bug | CHANGELOG.md |
| Change architecture | README.md, this file |
| Add/remove files | This file (file organization section) |
| Bump version | pyproject.toml, CHANGELOG.md |
| Create a release | GitHub Release + Discussion announcement |

### Document hierarchy

| Document | Purpose | Audience |
|----------|---------|----------|
| README.md | Project homepage, install, overview | Visitors |
| FEATURES.md | Complete feature reference (all 68) | Visitors + devs |
| ROADMAP.md | Timeline narrative + phase milestones | Visitors |
| CHANGELOG.md | Semantic versioned release notes | Devs |
| CONTRIBUTING.md | How to contribute | Contributors |
| SECURITY.md | Vulnerability reporting | Security researchers |
| CLAUDE.md (this file) | Dev guide for Claude Code sessions | Claude Code agents |
| docs/features/*.md | Detailed feature documentation | Deep-dive readers |

### Anti-patterns

- **Don't let docs drift from reality** — test counts, feature counts, file paths must match actual state
- **Don't create orphan docs** — every doc must be referenced from README or this file
- **Don't skip doc updates** — "I'll update docs later" = docs never get updated
- **Don't duplicate** — one source of truth per topic

---

## Key files

| File | What it does |
|------|-------------|
| `src/config.py` | `MemorySystemConfig` frozen dataclass — all paths/constants, env var overrides |
| `src/memory_ts_client.py` | Read/write memory files (YAML + markdown) |
| `src/semantic_search.py` | FAISS-backed similarity search |
| `src/hybrid_search.py` | Combined semantic + BM25 search |
| `src/db_pool.py` | SQLite connection pool for intelligence.db |
| `src/session_consolidator.py` | End-of-session memory extraction pipeline |
| `src/intelligence/orchestrator.py` | Brain stem — synthesizes 5 signal sources into daily briefing |
| `src/intelligence/clustering.py` | K-means clustering of memories by topic |
| `src/intelligence/vector_store.py` | FAISS IndexFlatIP wrapper with persistence |
| `dashboard/server.py` | Flask dashboard with 13+ API endpoints |
| `hooks/session-memory-consolidation-async.py` | Claude Code hook for automatic memory extraction |

---

## Environment

- **Python venv:** `~/.local/venvs/memory-system/`
- **Memory files:** `~/.local/share/memory/LFI/memories/`
- **Intelligence DB:** `intelligence.db` (created at runtime, gitignored)
- **Dashboard:** `http://localhost:8766`
- **Config override:** All paths overridable via `MEMORY_SYSTEM_*` env vars (see `src/config.py`)

---

## Autonomous operation

### Keep building when
- Tests passing → move to next feature
- Clear path forward → keep executing
- Minor decisions → make reasonable choice and document

### Stop and ask when
- Major architectural decision with trade-offs
- Ambiguous requirements
- Breaking changes affecting many features
- External dependencies or credentials needed

**Default to action.** When uncertain, make a reasonable choice and document the decision in the commit message.
