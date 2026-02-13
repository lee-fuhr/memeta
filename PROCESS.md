# Development Process

**Version:** 1.0
**Last updated:** 2026-02-13
**Purpose:** Persistent process guide across all sessions and compactions

---

## Core Principles

1. **Plan deeply before building** - Never rush to implementation
2. **Build sequentially and completely** - One feature at a time, fully done (code + tests + docs)
3. **Update docs at each step** - Keep PLAN.md, CHANGELOG.md, SHOWCASE.md current
4. **Verify continuously** - Run full test suite after each feature
5. **Operate autonomously** - Keep building without stopping unless absolutely necessary

---

## Feature Implementation Workflow

### Phase 1: Deep Planning (BEFORE any code)

**For each feature:**

1. **Read the existing plan** (if exists) - e.g., `docs/implementation-plans/F24-relationship-mapping-plan.md`
2. **Create comprehensive spec** (if doesn't exist):
   - Problem statement and goals
   - Database schema (complete table definitions with indices)
   - Complete API design (all methods with signatures, parameters, return types)
   - Integration points (how it connects to existing features)
   - Test plan (specific test categories and edge cases)
   - Edge cases and error handling
   - Performance considerations at 10K scale
   - Success criteria

3. **Review dependencies** - What needs to exist first? What will use this?
4. **Estimate scope** - How complex? How many tests needed?

**Output:** Comprehensive plan document in `docs/implementation-plans/` or `docs/planned-features/`

**User feedback:** "Take your time with the planning before you get to building, at each step along the way."

---

### Phase 2: Implementation

**Only after planning is complete:**

1. **Create source file** - `src/[module]/[feature].py`
2. **Create test file** - `tests/[module]/test_[feature].py`
3. **Implement feature fully** - All methods, error handling, edge cases
4. **Write comprehensive tests** - Cover all functionality, edge cases, error paths
5. **Run tests** - `pytest tests/[module]/test_[feature].py -v`
6. **Fix failures** - Iterate until all tests pass
7. **Run full suite** - `pytest tests/ -v --tb=short` to verify no regressions

**Output:** Working feature with comprehensive test coverage

---

### Phase 3: Documentation

**Immediately after feature works:**

1. **Update CHANGELOG.md**:
   - Add feature to current version's "Added" section
   - Use format: `**FXX: Feature Name** - Brief description highlighting key capabilities. Include test count.`
   - Add any fixes to "Fixed" section with file/line references

2. **Update SHOWCASE.md**:
   - Update test count in status line: `489/491 tests passing (99.6%)`
   - Update feature count: `36 features shipped`
   - Add capability to appropriate benefit section if major feature

3. **Update PLAN.md**:
   - Mark feature as complete in todo list
   - Update current status
   - Note any discoveries or changes to approach

**Output:** All documentation current and accurate

---

### Phase 4: Commit

**Only after docs updated:**

1. **Stage changes**: `git add -A`
2. **Write comprehensive commit message**:
   ```
   feat(FXX): Feature Name - complete implementation

   - List key capabilities (3-5 bullets)
   - Algorithm/approach used
   - Test coverage (N tests covering X, Y, Z)
   - Integration points
   - Any fixes or notable changes

   Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
   ```
3. **Commit**: `git commit -m "[message]"`

**Output:** Clean commit with feature + tests + docs

---

### Phase 5: Move to Next Feature

**Verify completion:**
- ✅ All tests passing for this feature
- ✅ Full test suite still passing (no regressions)
- ✅ CHANGELOG.md updated
- ✅ SHOWCASE.md updated
- ✅ PLAN.md updated
- ✅ Committed to git

**Then:** Start Phase 1 (Deep Planning) for next feature

---

## Execution Patterns

### Sequential (Default)

**When:** Features have dependencies or build on each other

**Pattern:**
```
F24 (Relationship Mapping)
  ↓ Complete (code + tests + docs + commit)
F27 (Reinforcement Scheduler)
  ↓ Complete
F28 (Search Optimization)
  ↓ Complete
...
```

### Parallel (Rare)

**When:** Features are completely independent with zero shared code/schema

**Pattern:**
```
F51 + F52 + F58 (all Tier 1 wild features)
  → Implement all three
  → Test all three
  → Doc all three
  → Commit together
```

**Note:** Usually not worth it - sequential is cleaner and easier to debug

---

## Quality Gates

### Before Moving to Next Feature

**Must verify:**
1. Feature tests: 100% passing
2. Full test suite: No regressions (compare before/after counts)
3. Documentation: CHANGELOG.md + SHOWCASE.md + PLAN.md updated
4. Git: Changes committed with clear message
5. Integration: Any features depending on this will work

**If any gate fails:** Stop and fix before proceeding

---

## Autonomous Operation Rules

### When to Keep Building (Don't Stop)

- Tests passing → move to next feature
- Clear path forward → keep executing
- Minor decisions → make reasonable choice and document
- Implementation details → follow established patterns

### When to Stop (Ask User)

- **Major architectural decision** - Multiple valid approaches with different trade-offs
- **Ambiguous requirements** - "Should this do X or Y?"
- **Scope creep detected** - Feature growing beyond original plan
- **Breaking changes** - Change would affect many other features
- **External dependencies** - Need user's credentials, access, or decisions

**User guidance:** "I'd rather you be building in a suboptimal sequence than waiting for me when I might not be standing here waiting to type 'go' to you."

**Interpretation:** Default to action. When uncertain, make reasonable choice and document. Only stop for genuinely blocking decisions.

---

## Document Maintenance

### Keep Current (Update After Each Feature)

**PLAN.md:**
- Current status
- Completed features
- Next immediate actions
- Any discoveries or changes to approach

**CHANGELOG.md:**
- Add feature to current version
- Add any fixes with file references
- Maintain chronological order within version
- Use semantic versioning (0.X.0 for features)

**SHOWCASE.md:**
- Update test counts
- Update feature counts
- Add major capabilities to benefit sections
- Keep "Updated" date current

**PROCESS.md (this file):**
- Capture any new patterns discovered
- Refine workflow based on learnings
- Update examples

---

## Test Coverage Standards

### Per Feature

**Minimum:** 10-15 tests covering:
- Initialization and schema creation
- Basic functionality (happy path)
- Error handling (invalid inputs, edge cases)
- Integration points (how it connects to other features)
- Edge cases (empty data, maximum values, boundary conditions)

**Target:** 20-30 tests for complex features

### Full Suite

**Gate:** Must maintain or improve passing percentage
- Before feature: X/Y passing (Z%)
- After feature: X+N/Y+N passing (≥Z%)

**Regression check:** No previously passing tests should fail

---

## Commit Message Format

### Structure

```
<type>(<scope>): <subject> - <brief>

<body>
- Bullet points of key changes
- Algorithms or approaches used
- Test coverage summary
- Integration points

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### Types

- **feat** - New feature (F24, F27, etc.)
- **fix** - Bug fix
- **refactor** - Code restructuring without behavior change
- **test** - Adding or updating tests
- **docs** - Documentation only
- **chore** - Maintenance (file cleanup, etc.)

### Examples

**Feature:**
```
feat(F24): Memory Relationship Mapping - complete implementation

- Graph-based relationship system with 5 types
- BFS causal chain discovery
- Bidirectional queries and contradiction detection
- 28 tests covering initialization, creation, retrieval, chains
- Integration points for contradiction_detector and pattern_detector

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Fix:**
```
fix(relationship_mapper): SQL WHERE clause precedence issue

- Wrapped OR conditions in parentheses for correct precedence
- Prevents: WHERE from = ? OR to = ? AND type = ?
- Correct: WHERE (from = ? OR to = ?) AND type = ?
- All 28 tests now passing

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## Reference This Document

**In PLAN.md:** Link to PROCESS.md in "Implementation Sequence" section
**In Compaction:** Refer to PROCESS.md for workflow guidance
**When Uncertain:** Read PROCESS.md for decision framework

**This document persists across all sessions and captures the "how we work" methodology.**
