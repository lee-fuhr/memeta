# Features 36-43: Integration Features

**Status:** Planning phase
**Category:** External system integrations
**Database:** intelligence.db (shared schema)

---

## Overview

Integration features connect memory system to external data sources. Many of these are lower priority than core intelligence features.

**Decision:** Most F36-43 integrations are **DEFERRED** until core features (F24-65) are stable and proven.

**Rationale:**
- External APIs change frequently (maintenance burden)
- Privacy/security concerns with auto-processing
- Better to nail core features first
- Many integrations overlap with existing features

---

## F36: Obsidian Integration (DEFERRED)

**Problem:** Memories live in memory-ts, notes in Obsidian.

**Status:** DEFERRED - manual export/import (F29) is sufficient for now

**If built:**
- Bi-directional sync
- Convert Obsidian notes → memories
- Link memories ← → notes
- Obsidian plugin for search

---

## F37: Roam Research Integration (DEFERRED)

**Problem:** Roam users want memory integration.

**Status:** DEFERRED - Roam's daily notes paradigm conflicts with memory-ts model

**If built:**
- Import Roam graph
- Convert daily notes → memories
- Maintain block references

---

## F38: Email Intelligence (PARTIAL - EXISTS)

**Problem:** Emails contain commitments, decisions, context.

**Status:** EXISTS in `_ Operations/email-intelligence/` but needs integration with memory system

**Current state:**
- Email rules and categorization exist
- Commitment tracking exists
- NOT integrated with memory-ts

**If integrated:**
- Extract email commitments → memories
- Tag with #email, #commitment
- Link to calendar events
- Search across email + memory

**Schema:**
```sql
CREATE TABLE email_memories (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,  -- Link to memory-ts
    email_id TEXT NOT NULL,
    from_address TEXT,
    subject TEXT,
    extracted_at INTEGER NOT NULL
);
```

---

## F39: Notion Integration (LOW PRIORITY)

**Problem:** Notion databases contain structured data.

**Status:** LOW PRIORITY - F29 (import/export) handles one-time migration

**If built:**
- Bi-directional sync with Notion databases
- Memory → Notion row
- Notion row → Memory
- Conflict resolution

---

## F40: Calendar Intelligence (PARTIAL - EXISTS)

**Problem:** Calendar contains context about meetings.

**Status:** EXISTS in `_ Operations/ea_brain/` (Penny's dossiers)

**Current state:**
- Pre-meeting dossiers auto-generated
- Meeting transcripts indexed (1,900+ meetings)
- NOT integrated with memory-ts for post-meeting learning

**If integrated:**
- Extract meeting decisions → memories
- Link memories to calendar events
- Pre-meeting context retrieval from memories
- Post-meeting commitment tracking

---

## F41: Git Commit Intelligence (DEFERRED)

**Problem:** Git history contains decisions, approaches tried.

**Status:** DEFERRED - F71 covers this in wild features

**If built:**
- Parse commit messages → memories
- Extract "tried X, didn't work" patterns
- Link code changes to decisions

---

## F42: Code Review Intelligence (DEFERRED)

**Problem:** Code review feedback is learning opportunity.

**Status:** DEFERRED - F72 covers this in wild features

**If built:**
- Extract review patterns
- "You always forget X" → memory
- Pre-review checks

---

## F43: Documentation Gap Detection (DEFERRED)

**Problem:** Answer same question 5x, should be in docs.

**Status:** DEFERRED - F73 covers this in wild features

**If built:**
- Detect repeated questions
- Suggest doc updates
- Auto-generate docs from memories

---

## Priority Assessment

**Build now:**
- NONE - defer all integrations until core features stable

**Build later (if valuable):**
- F38: Email Intelligence (partial integration with existing email system)
- F40: Calendar Intelligence (partial integration with Penny)

**Probably never build:**
- F36, F37, F39: External note-taking systems (F29 import/export sufficient)
- F41, F42, F43: Covered by F71-73 in wild features

---

## Recommendation

**Skip F36-43 entirely.** Reason:

1. **F29 (Import/Export)** handles migration use case
2. **F38 partial** (Email Intelligence) already exists standalone
3. **F40 partial** (Calendar) already exists in Penny
4. **F41-43** are duplicates of F71-73
5. **External API maintenance** is high burden
6. **Core intelligence** (F24-32, F51-65) delivers more value

**Action:** Mark F36-43 as DEFERRED in feature roadmap. Focus on F24-32 and F51-65 instead.

---

## Database Impact

**If built:** ~10MB additional per 10K memories
**API cost:** ~$5/day for email/calendar processing

**But we're not building these, so: $0 additional cost**
