# Documentation System - Complete Map

**Version:** 1.0
**Created:** 2026-02-13
**Purpose:** Explain all .md docs, their relationships, usage, and enforcement mechanisms

---

## The Documentation Hierarchy

```
DOCUMENTATION-SYSTEM.md ← YOU ARE HERE (explains all docs)
    ↓
ORCHESTRATION.md (mission control: token-efficient build strategy)
    ↓
PROCESS.md (how to work: 5-phase workflow)
    ↓
┌─────────────────┬───────────────────┬─────────────────┐
│                 │                   │                 │
PLAN.md     CHANGELOG.md      SHOWCASE.md      HANDOFF.md
(what to do)  (what changed)    (what shipped)   (session transfer)
    ↓
docs/implementation-plans/
    - F24-relationship-mapping-plan.md
    - F27-reinforcement-scheduler-plan.md
    - F28-search-optimization-plan.md
    - F51-temporal-pattern-prediction-plan.md
    ↓
docs/planned-features/
    - F24-32-intelligence-enhancement.md
    - F51-75-wild-features.md
```

---

## Document Purposes (What Each One Does)

### ORCHESTRATION.md
**Purpose:** Token-efficient build strategy for 75-feature system
**Audience:** Mission control (main thread conductor)
**When to read:** At session start, before spawning agents
**Contains:**
- Mission control pattern (light orchestration, spawn subagents)
- Per-feature workflow (Opus review → Steelman → Sonnet implement)
- Token budget management
- Quality gates
- Autonomous operation rules
- Reddit workflow insights (Steelman technique)

**How it's enforced:** Mission control reads this to understand orchestration pattern

---

### PROCESS.md
**Purpose:** Persistent 5-phase workflow guide across all sessions
**Audience:** All agents (Opus, Sonnet, mission control)
**When to read:** Before implementing any feature
**Contains:**
- Core principles (plan deeply, build sequentially, update docs)
- 5-phase workflow: Deep Planning → Implementation → Documentation → Commit → Next
- Quality gates before moving to next feature
- Autonomous operation rules (when to stop/keep going)
- Document maintenance (what to update when)
- Test coverage standards
- Commit message format

**How it's enforced:**
- Sonnet agents receive explicit instruction: "Follow PROCESS.md workflow"
- Quality gates checked by mission control before moving to next feature
- Git commits must follow format from PROCESS.md

---

### PLAN.md
**Purpose:** Project plan with execution sequence and progress tracking
**Audience:** All agents + mission control
**When to read:** After each feature to update status
**Contains:**
- Progress log (dated entries for each completed step)
- Current state (features shipped/coded/planned, test status)
- Execution sequence (what depends on what)
- Open issues (critical/high/medium)
- Next immediate actions

**How it's enforced:**
- PROCESS.md Phase 3 (Documentation) requires: "Update PLAN.md: Mark feature complete"
- Mission control checks PLAN.md after each feature
- Progress log is append-only (never delete history)

---

### CHANGELOG.md
**Purpose:** Semantic versioned release notes
**Audience:** Developers, users, future maintainers
**When to read:** To understand what changed in each version
**Contains:**
- Organized by version (0.1.0, 0.2.0, 0.3.0)
- Format: Added / Fixed / Changed sections
- Chronological order within version
- Test counts per feature

**How it's enforced:**
- PROCESS.md Phase 3 requires: "Update CHANGELOG.md (add to 'Added' section)"
- Sonnet agents include this in their deliverables
- Mission control verifies CHANGELOG updated before marking feature complete

---

### SHOWCASE.md
**Purpose:** User-facing product presentation using VBF framework
**Audience:** Users, potential users, stakeholders
**When to read:** To understand what the system does and why it matters
**Contains:**
- Problem statement (what breaks with traditional systems)
- Values → Benefits → Features progression
- Test count and feature count in header
- Capability descriptions grounded in user benefits

**How it's enforced:**
- PROCESS.md Phase 3 requires: "Update SHOWCASE.md: Test count + feature count"
- Mission control checks test count increased after each feature
- Header format: `**Status:** v0.3.0 | 552/554 tests passing (99.6%) | 39 features shipped`

---

### HANDOFF.md
**Purpose:** Session transfer document for context compaction
**Audience:** Next agent in fresh session
**When to read:** At start of fresh session after compaction
**Contains:**
- Current goal and user directive
- How to use the documentation system
- What's complete (detailed feature summaries)
- What's working/broken
- In progress work
- What worked/didn't work
- Key decisions
- Important files
- Next steps (priority order)
- Critical context for next agent

**How it's enforced:**
- Created when main thread hits ~150K tokens
- User runs `/qq-handoff` skill to create
- Next session starts with: `read HANDOFF.md and continue`

---

### docs/implementation-plans/*.md
**Purpose:** Detailed feature specifications ready for implementation
**Audience:** Opus (for review), Sonnet (for implementation)
**When to read:** Before implementing a feature
**Contains:**
- Complete database schemas with indexes justified
- Full class design with all methods and docstrings
- Integration points with existing systems
- Complete test plan (not just count)
- Edge cases and error handling
- Performance considerations
- Success criteria

**How it's enforced:**
- PROCESS.md Phase 1 (Deep Planning) requires reading implementation plan
- Opus reviews these for completeness before Sonnet implements
- Sonnet uses these as source of truth during implementation

---

### docs/planned-features/*.md
**Purpose:** Feature specifications before detailed planning
**Audience:** Planning phase (Opus)
**When to read:** During initial feature planning
**Contains:**
- Feature groups (F24-32, F51-75, etc.)
- Problem statements
- Basic schema ideas
- Algorithm sketches
- Test count targets

**How it's enforced:**
- Opus reads these during initial review
- If underspecified, mission control creates detailed implementation plan
- These get promoted to docs/implementation-plans/ when ready

---

## Documentation Workflow Per Feature

```
1. Mission control reads ORCHESTRATION.md
   ↓
2. Spawn Opus to review feature plan
   - Opus reads: PROCESS.md + docs/implementation-plans/FXX-*.md
   - Outputs: Blockers, gaps, READY/NEEDS_WORK
   ↓
3. If NEEDS_WORK: Mission control creates/fixes implementation plan
   ↓
4. Spawn Opus for Steelman review
   - Opus argues against its own criticism
   - Kills weak issues, keeps blocking issues
   ↓
5. Spawn Sonnet to implement
   - Sonnet reads: PROCESS.md + implementation plan
   - Sonnet delivers: source + tests + updated docs
   - Sonnet updates: CHANGELOG.md, SHOWCASE.md, PLAN.md
   - Sonnet commits: Git with comprehensive message
   ↓
6. Mission control verifies:
   - Test suite passing (check SHOWCASE.md test count increased)
   - CHANGELOG.md has new entry
   - PLAN.md marked feature complete
   - Git status clean
   ↓
7. Mission control updates todo list
   ↓
8. Move to next feature
```

---

## Enforcement Mechanisms

### 1. Explicit Instructions to Agents

**Opus agents receive:**
- "Read PROCESS.md to understand workflow"
- "Review plan at docs/implementation-plans/FXX-*.md"
- "Output: READY or NEEDS_WORK with specific gaps"

**Sonnet agents receive:**
- "Follow PROCESS.md workflow"
- "Implement from docs/implementation-plans/FXX-*.md"
- "Update CHANGELOG.md, SHOWCASE.md, PLAN.md"
- "Deliverables: source + tests + docs + commit"

### 2. Quality Gates (Mission Control Verification)

**Before moving to next feature, mission control checks:**
- [ ] Feature tests: 100% passing
- [ ] Full test suite: No regressions (compare before/after counts)
- [ ] CHANGELOG.md: Feature added to current version
- [ ] SHOWCASE.md: Test count + feature count increased
- [ ] PLAN.md: Feature marked complete in progress log
- [ ] Git: Changes committed with proper format
- [ ] Todo list: Updated

**If any gate fails:** Stop, fix, verify before proceeding.

### 3. File Location Conventions

**Enforced by:**
- PROCESS.md specifies where files go
- Opus reviews check file locations match conventions
- Mission control verifies created files in correct directories

**Conventions:**
- Source: `src/wild/` for F51-75, `src/intelligence/` for F24-32
- Tests: `tests/wild/` or `tests/intelligence/` matching source location
- Plans: `docs/implementation-plans/` for detailed specs
- Features: `docs/planned-features/` for high-level specs

### 4. Git Commit Format

**Enforced by:**
- PROCESS.md provides commit message template
- Sonnet agents follow this template
- Template includes: type(scope): subject, bullet points, co-author

**Template:**
```
feat(FXX): Feature Name - complete implementation

- List key capabilities (3-5 bullets)
- Algorithm/approach used
- Test coverage (N tests covering X, Y, Z)
- Integration points
- Any fixes or notable changes

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### 5. Token Budget Management

**Enforced by:**
- ORCHESTRATION.md sets target: <120K for main thread
- Mission control checks token usage after each 5 features
- When approaching limit: create HANDOFF.md, start fresh session

**Budget allocation:**
- Main thread: Coordination, verification, tracking (<120K)
- Subagents: Planning, implementation, testing (full 200K each, disposable)

---

## How Documents Stay Synchronized

### After Each Feature

**Sonnet automatically updates:**
1. CHANGELOG.md (adds feature to current version's "Added" section)
2. SHOWCASE.md (increments test count + feature count in header)
3. PLAN.md (appends dated progress log entry)

**Mission control verifies:**
- All three docs updated
- Test counts match (pytest count = SHOWCASE.md count)
- Feature count matches (shipped features = SHOWCASE.md count)

### Manual Updates (When Needed)

**ORCHESTRATION.md:** When we learn new patterns (like Steelman)
**PROCESS.md:** When workflow evolves (rare, fundamental changes only)
**HANDOFF.md:** Created manually when session approaching token limit

---

## Documentation Anti-Patterns (What NOT to Do)

### ❌ Don't create docs that duplicate existing ones
- If it's about workflow → add to PROCESS.md
- If it's about orchestration → add to ORCHESTRATION.md
- If it's feature status → update PLAN.md
- Don't create "workflow-v2.md" or "new-process.md"

### ❌ Don't let docs drift from reality
- After each feature: Update CHANGELOG, SHOWCASE, PLAN
- Test counts must match pytest output
- Feature counts must match actual shipped features
- Git status must be clean (committed) before moving on

### ❌ Don't create orphan implementation plans
- Every plan in docs/implementation-plans/ must have corresponding feature
- Delete plans for cancelled features
- Archive plans for completed features (optional, keep for reference)

### ❌ Don't skip quality gates
- "I'll update docs later" = docs never get updated
- "Tests are mostly passing" = regressions creep in
- "I'll commit after the next feature" = lose track of what changed

---

## How to Add a New Document

**When to add:**
- New orchestration pattern that persists across features
- New category of features needing different workflow
- New integration requiring setup guide

**Process:**
1. Write document with clear purpose and audience
2. Add entry to this file (DOCUMENTATION-SYSTEM.md)
3. Update ORCHESTRATION.md or PROCESS.md with reference
4. Ensure enforcement mechanism exists

**Example:** F51 needed detailed implementation plan
- Created: `docs/implementation-plans/F51-temporal-pattern-prediction-plan.md`
- Added to: This file under "docs/implementation-plans/"
- Enforcement: Opus reads before review, Sonnet reads before implementation

---

## Quick Reference: Which Doc When?

| Situation | Read This |
|-----------|-----------|
| Starting session as mission control | ORCHESTRATION.md |
| Implementing a feature | PROCESS.md + docs/implementation-plans/FXX-*.md |
| Reviewing a feature plan | docs/implementation-plans/FXX-*.md |
| Checking what's done | PLAN.md (current state section) |
| Understanding what changed | CHANGELOG.md |
| Explaining system to user | SHOWCASE.md |
| Transferring to fresh session | HANDOFF.md |
| Checking token budget | ORCHESTRATION.md (token management section) |
| Finding next feature | PLAN.md (next immediate actions) |
| Understanding test counts | SHOWCASE.md (header) |

---

## Success Metrics

**Documentation is working when:**
- Agents never ask "what should I update?"
- Test counts always match between pytest and SHOWCASE.md
- Git history shows consistent commit format
- New features always have updated docs
- Session handoffs preserve full context
- Token budget stays under 120K for main thread
- Subagents complete features autonomously (30+ min runs)

**Documentation is failing when:**
- Agents update wrong docs
- Test/feature counts drift from reality
- Git commits missing or poorly formatted
- Features shipped without doc updates
- Handoffs lose critical context
- Main thread runs out of tokens unexpectedly
- Subagents get blocked asking for clarification

---

**The system is self-documenting, self-enforcing, and self-improving.**
**Every feature makes the system better at building features.**
**Every doc makes agents better at using docs.**

---

**Current state:** 39 features shipped, 552/554 tests passing, docs synchronized, F51 complete.
