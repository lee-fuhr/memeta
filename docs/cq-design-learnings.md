# CQ design learnings

Design ideas for Memeta inspired by [CQ](https://github.com/mozilla-ai/cq), Mozilla AI's "Stack Overflow for agents" — an open-source knowledge commons where AI agents contribute and query discoveries.

CQ approaches knowledge differently than Memeta — it treats every piece of knowledge as a structured object with explicit lifecycle metadata, rather than free-form text with importance scores. Several of its patterns are worth adopting.

---

## 1. Tripartite knowledge structure (summary / detail / action)

**CQ pattern:** Every knowledge item has three layers: a one-line summary for quick scanning, a detailed explanation for depth, and an explicit action field describing what to DO with the knowledge.

**Memeta implication:** Memeta memories currently have content + importance + tags but no explicit action field. Adding an `action` field to the memory YAML frontmatter would answer: "When this memory surfaces, what should the AI actually do?" This turns passive recall into active guidance.

**Example:**
```yaml
action: "When user mentions calendar events, always create on shared calendar with both as attendees"
```

The action field bridges the gap between "I know this" and "I should do this." Memories without actions are reference; memories with actions are behavioral.

---

## 2. Session reflection workflow

**CQ pattern:** At the end of a conversation, run a structured retrospective: what was learned, what worked, what didn't, what should be remembered. Filter candidates by four criteria: generalizable, non-obvious, actionable, novel.

**Memeta implication:** The session consolidation hook already extracts memories at session end, but it doesn't run a deliberate reflection pass. A reflection workflow would mine sessions not just for factual learnings but for process improvements — the meta-learnings that compound across hundreds of sessions.

**Integration point:** Extend `session-memory-consolidation-async.py` with a reflection phase after the extraction phase.

---

## 3. Confirmation counting

**CQ pattern:** Track how many times a piece of knowledge has been surfaced AND confirmed helpful by the user. Pure recall frequency isn't enough — the knowledge must actually help.

**Memeta implication:** FSRS tracks recall scheduling, and the importance score captures initial quality, but neither measures "times surfaced AND helpful." Adding a confirmation counter would provide an FSRS-adjacent signal: knowledge that surfaces often but never gets confirmed as helpful should decay faster; knowledge confirmed helpful repeatedly should become near-permanent.

**Integration point:** The memory injection hook already surfaces memories. Adding a lightweight signal — did the user's response indicate the memory was useful? — would feed the confirmation counter.

---

## 4. Knowledge lifecycle classification

**CQ pattern:** Classify every piece of knowledge by its lifecycle stage: permanent (always true), workaround (true until a better solution exists), gap-signal (marks something the system doesn't know yet), or expired (no longer true).

**Memeta implication:** Memeta has `is_permanent` as a boolean and importance decay for everything else, but it doesn't distinguish between a memory that's a workaround (will become obsolete) and a memory that's a gap-signal (should trigger research). Lifecycle classification would let the system treat different types of transient knowledge differently:

- **Permanent:** No decay, always surface. (Already supported via `is_permanent`.)
- **Workaround:** Surface with a note that a better approach may exist. Tag the dependency (what would make this obsolete?).
- **Gap-signal:** Don't just remember the gap — prompt research when the topic resurfaces.
- **Expired:** Archive immediately, don't surface. (Already supported via importance decay to zero.)

---

## 5. Superseded-by chains

**CQ pattern:** When knowledge is updated, don't overwrite the old version. Instead, mark the old entry as superseded and link it to the new one. This preserves the evolution history.

**Memeta implication:** Currently, when a memory becomes outdated, it either gets manually archived or decays via importance scoring. There's no explicit "this memory was replaced by that memory" link. Superseded-by chains would:

- Prevent the system from surfacing outdated memories when the replacement exists
- Preserve the decision trail (why did we change from approach A to approach B?)
- Enable "what changed?" queries — show the chain of updates for a given topic

**Implementation:** A `superseded_by` field in YAML frontmatter pointing to the replacement memory's ID. The memory injector would skip superseded memories and surface the chain tip instead.

---

## Implementation priority

These ideas are ordered by expected impact relative to implementation cost:

1. **Lifecycle classification** — Low implementation cost (add an enum field), high organizational value
2. **Action field** — Low cost, transforms passive memories into active guidance
3. **Superseded-by chains** — Medium cost, directly improves memory accuracy
4. **Confirmation counting** — Medium cost, requires signal detection, but compounds over time
5. **Session reflection** — Higher cost (new pipeline phase), but mines a currently untapped signal source

None of these require architectural changes to Memeta's core. They're all additive — new fields, new tags, new pipeline phases layered onto the existing system.

---

## Source

Synthesized from studying [CQ](https://github.com/mozilla-ai/cq) by Mozilla AI (published 2026-03-23, Apache 2.0). Full design inventory at `cq-mozilla-full-inventory.md`. CQ is a PoC-stage shared knowledge commons where AI agents contribute and query discoveries. While CQ targets multi-agent knowledge sharing, several of its structural patterns translate directly to single-user memory systems like Memeta.
