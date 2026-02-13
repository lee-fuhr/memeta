# Handoff: Memory system FSRS promotion alpha

**Session:** Memory system FSRS promotion alpha
**Date:** 2026-02-02

---

## Goal

Build memory-system-v1: automatic memory extraction, spaced repetition scheduling, and promotion system as a companion tool for memory-ts. Release as alpha on GitHub.

## What's done

### Phase 1 — Session consolidation (100 tests)
- `session_consolidator` — Extract + deduplicate memories from sessions (35 tests)
- `memory_ts_client` — CRUD operations on memory-ts markdown files (25 tests)
- `importance_engine` — Score memory importance 0.0–1.0 (17 tests)
- `llm_extractor` — LLM-powered extraction via `claude -p` CLI (23 tests)

### Phase 2 — FSRS promotion system (90 tests)
- `fsrs_scheduler` — FSRS-6 spaced repetition, SQLite-backed (22 tests)
- `pattern_detector` — Cross-session fuzzy matching + reinforcement (25 tests)
- `promotion_executor` — Project → global scope promotion (14 tests)
- `memory_clustering` — Keyword-based memory grouping (20 tests)
- `weekly_synthesis` — Draft generation + Pushover notification (9 tests)

**Total: 190 tests, all passing.**

### Deployment
- SessionEnd hook wired: `LFI/_ Operations/hooks/session-memory-consolidation.py`
- Weekly synthesis LaunchAgent: `com.lfi.memory-weekly-synthesis.plist` (Friday 5pm)
- Runner scripts: `scripts/weekly_synthesis_runner.py`, `scripts/pattern_detection_runner.py`

### Alpha release
- Repo public: https://github.com/lee-fuhr/memory-system-v1
- README rewritten for public consumption
- MIT license added
- .gitignore updated (fsrs.db, clusters.db, _working/, synthesis/)
- Working artifacts moved to _working/

### Brain emoji visibility (new feature)
- Modified `/opt/homebrew/lib/node_modules/@rlabs-inc/memory/hooks/claude/user-prompt.ts`
- When memories are active (message 2+ of session), user sees in terminal:
  ```
  🧠 2 memories active:
     · Docker MCP Gateway caused 83K token context bloat with 108 t…
     · MCP server configs now live in ~/.claude/.mcp.json, not ~/.c…
  ```
- Uses stderr (user-visible) vs stdout (Claude context injection)
- Parses `context_text` format: `[emoji • importance • age] [tags] content`
- Tested end-to-end, working

## What's working

- All 190 tests pass: `python3 -m pytest /Users/lee/CC/LFI/_ Operations/memory-system-v1/tests/ -v`
- Brain emoji hook tested and confirmed working with real memory retrieval
- Memory-ts has 863 memories stored in `~/.local/share/memory/LFI/memories/`

## Critical bug fixed (needs production validation)

**SessionEnd hook was silently failing** — every consolidation was `status: "skipped"` because the hook used `os.environ.get("PROJECT_ID")` but Claude Code passes session context via **stdin JSON**.

**Fix applied:** Hook now reads stdin JSON first (`_STDIN_DATA.get("session_id")`), falls back to `CLAUDE_SESSION_ID` env var. Added diagnostic logging (`stdin_keys`, `env_session`) for debugging.

**Validation:** Next session end should produce `status: "success"` in `LFI/_ Operations/hooks/hook_events.jsonl`. Check with:
```bash
tail -5 "/Users/lee/CC/LFI/_ Operations/hooks/hook_events.jsonl" | python3 -m json.tool
```

## What's NOT done

- **Capability evolution loop** (item 3 from plan) — A/B testing for agent prompts/sequences. Separate project, not started.
- **FSRS database** doesn't exist yet (expected — hook wasn't working before the fix). Will be auto-created once the hook fix is validated.
- **Community contribution** — haven't submitted to memory-ts companion list yet. Do this after production validation.

## Key technical details

- **Memory retrieval**: messageCount === 0 returns primer only (no memories). Memories surface starting from message 2+.
- **Activation signals**: Retrieval requires 2+ signals (trigger phrases, tag overlap, domain, feature, content keywords, vector similarity ≥40%)
- **Hook channels**: stdout → Claude's context (system-reminder), stderr → user's terminal
- **Memory-ts server**: @rlabs-inc/memory v0.3.8, HTTP daemon on port 8765, LaunchAgent
- **Dual write paths**: memory-ts curation AND our consolidation hook both write to `~/.local/share/memory/LFI/memories/` — dedup handles overlap (61-67% filtered)

## Important files

| File | Purpose |
|------|---------|
| `/Users/lee/CC/LFI/_ Operations/memory-system-v1/` | Main repo (9 modules, 190 tests) |
| `/Users/lee/CC/LFI/_ Operations/hooks/session-memory-consolidation.py` | SessionEnd hook (fixed stdin) |
| `/opt/homebrew/lib/node_modules/@rlabs-inc/memory/hooks/claude/user-prompt.ts` | Brain emoji hook (modified) |
| `/Users/lee/Library/LaunchAgents/com.lfi.memory-weekly-synthesis.plist` | Weekly synthesis scheduler |
| `/Users/lee/CC/LFI/_ Operations/hooks/hook_events.jsonl` | Hook event log (check for validation) |
| `~/.local/share/memory/LFI/memories/` | 863 memory files |

## Next steps

1. **Validate hook fix** — Check hook_events.jsonl after next session end for `status: "success"`
2. **Monitor FSRS database creation** — Should appear at `memory-system-v1/fsrs.db` after first successful consolidation
3. **Capability evolution loop** — Separate project: A/B testing for agent prompts, sequences, patterns
4. **Community contribution** — After production validation, submit to memory-ts companion tools
