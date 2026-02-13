# Orchestration Strategy for Memory System v1

**Version:** 1.0
**Created:** 2026-02-13
**Purpose:** Token-efficient build strategy for 75-feature system

---

## Mission Control Pattern

**This session operates as mission control:**
- Light orchestration only
- Spawn subagents for all actual work
- Use Opus for planning reviews
- Use Sonnet for implementations
- Keep main thread context focused on coordination

**Why this works:**
- Main thread stays under 120K tokens (coordination only)
- Heavy lifting happens in subagent contexts (disposable)
- Can run 30+ features without compaction
- Each subagent has full 200K budget for deep work

---

## Per-Feature Workflow

### 1. Opus Planning Review with Steelman (disposable context)

**Inspired by:** Reddit post on autonomous Claude workflow - have Claude argue against its own criticism to kill weak issues

```bash
Task tool, model="opus", subagent_type="Plan"
```

**Pattern: Review → Steelman → Fix**

**Round 1: Critical Review**
- Input: Feature plan location, critical requirements, review checklist
- Output: List of all issues/gaps found

**Round 2: Steelman (when needed)**
- Have Opus argue against its own criticism
- Defend the original plan
- Kill weak criticisms that don't hold up under scrutiny
- Output: Only issues that survive Steelman defense

**Round 3: Fix Surviving Issues**
- Apply only the validated critical issues
- Spawn Sonnet for surgical fixes
- Re-review with Opus to confirm READY

**Why this works:**
- Catches real issues in first pass
- Steelman kills false positives and overthinking
- What survives is genuinely blocking
- Avoids unnecessary complexity

**If NEEDS_WORK:** Create detailed implementation plan, fix issues, re-review until READY.

---

### 2. Sonnet Implementation (disposable context)

```bash
Task tool, model="sonnet", subagent_type="general-purpose"
```

**Input to Sonnet:**
- Complete implementation plan (after Opus review)
- Instruction: "Implement [Feature] following PROCESS.md workflow"
- Reference to PROCESS.md for workflow steps

**Sonnet deliverables:**
- Source implementation (`src/[module]/[feature].py`)
- Comprehensive tests (`tests/[module]/test_[feature].py`)
- Updated CHANGELOG.md
- Updated SHOWCASE.md
- Updated PLAN.md
- Git commit with comprehensive message

**Output from Sonnet:**
- Completion report with test results
- Any issues encountered
- Next steps if blocked

---

### 3. Mission Control Verification

**Main thread checks:**
- Test suite passing (run pytest)
- Git status clean (all committed)
- Documentation updated (CHANGELOG, SHOWCASE, PLAN)
- Todo list updated

**Then:** Move to next feature.

---

## Token Budget Management

**Main thread (mission control):**
- Target: <120K tokens
- Activities: coordination, verification, tracking
- Tools: TodoWrite, Read (verification), Bash (test runs)

**Subagents (disposable):**
- Full 200K budget each
- Activities: planning, implementation, testing
- Tools: Read, Write, Edit, Bash, Grep, Glob, Task (for sub-sub-agents)

**When main thread hits 120K:**
- Create handoff document
- Start fresh session
- Resume from handoff

---

## Execution Sequence

**Current state:** F24, F27, F28 complete (38 features total)

**Remaining features:**
1. F25, F26, F29-F32: Intelligence Enhancement (6 features)
2. F51-F60: Wild Features Tier 1-2 (10 features)
3. F64-F75: Wild Features Tier 3 (12 features)
4. F36-F43: Integrations (8 features, DEFERRED)

**Total workload:** 28 features + QA pass + design pass

---

## Quality Gates

**Before moving to next feature:**
- [ ] Feature tests: 100% passing
- [ ] Full test suite: No regressions
- [ ] CHANGELOG.md: Feature added
- [ ] SHOWCASE.md: Test count + feature count updated
- [ ] PLAN.md: Feature marked complete
- [ ] Git: Changes committed
- [ ] Todo list: Updated

**Before QA pass:**
- [ ] All 75 features implemented
- [ ] Test suite: 100% passing
- [ ] Documentation: Complete

**Before final delivery:**
- [ ] QA findings: All critical/high resolved
- [ ] Product findings: All critical/high resolved
- [ ] System tested end-to-end

---

## Autonomous Operation Rules

**Don't stop for:**
- Minor implementation decisions (make reasonable choice, document)
- Tool selection (use best available)
- Code style choices (follow existing patterns)
- Test structure (follow existing test patterns)

**Do stop for:**
- Major architectural decisions with multiple valid approaches
- Ambiguous requirements affecting feature behavior
- Breaking changes to existing features
- External dependencies requiring credentials/access

**User directive:** "Hammer at it till it's done. No time estimates. Work autonomously without stopping unless absolutely necessary."

---

## Progress Tracking

**After each feature:**
1. Update todo list (TodoWrite)
2. Run test suite (verify count increased)
3. Check git status (verify committed)
4. Brief completion summary

**After each 5 features:**
1. Update PLAN.md progress log
2. Check main thread token usage
3. Assess if handoff needed

**After all features:**
1. Comprehensive test run
2. Spawn QA swarm (7 agents)
3. Fix all findings
4. Spawn design swarm (7 agents)
5. Fix all findings
6. Final delivery

---

## Example Flow

```
Mission Control: "Build F51"
  ↓
Spawn Opus (Plan review)
  → Output: "NEEDS_WORK - missing topic_resumption_detector hook"
  ↓
Mission Control: Create detailed implementation plan
  ↓
Spawn Opus (Plan re-review)
  → Output: "READY - all blockers resolved"
  ↓
Spawn Sonnet (Implementation)
  → Sonnet: Builds source + tests + docs + commits
  → Output: "Complete - 18 tests passing"
  ↓
Mission Control: Verify
  → pytest: 545/547 passing (99.6%)
  → git status: clean
  → Documentation: updated
  ↓
Mission Control: Update tracking, move to F52
```

---

## Lessons Learned

**From F24-F28 build:**
1. Opus plan review catches blockers before implementation (saved rework on F28)
2. PROCESS.md workflow ensures quality (comprehensive tests, docs updated)
3. Sequential execution cleaner than parallel (easier to debug)
4. User feedback: "Take your time with planning before building"

**From Reddit autonomous workflow post:**
1. **Brainstorm before building** - Have normal conversation to break down problem from first principles
2. **Let Claude write the plan** - It knows what it needs better than we do
3. **Iterate on the plan** - Treat plan like a product, sharpen sections, cut unnecessary stuff
4. **Steelman review** - Have Claude argue against its own criticism, kills ~50% of "critical" issues
5. **Multiple revision cycles** - Run review → steelman → fix cycle 2-3 times until clean
6. **Autonomous execution** - Clear, detailed instructions enable 30min+ autonomous runs

**Applying to F51-F75:**
- Never skip Opus plan review
- Use Steelman to validate criticisms before fixing
- Create detailed implementation plans for underspecified features
- Follow 5-phase workflow religiously
- Enable truly autonomous Sonnet implementation with comprehensive instructions

---

**Ready for autonomous execution. Let's build 28 more features.**
