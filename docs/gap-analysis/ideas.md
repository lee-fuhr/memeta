# Ideas — speculative features and wild possibilities

**Created:** 2026-02-14
**Format:** Loose creative writeup. No formal spec. Inspired by Ben's nice-to-haves, the wild/ features, and patterns observed while reading the code.

---

## The thing nobody has built yet: a memory that argues with you

Every memory system in existence is passive. You tell it something, it stores it. You ask, it retrieves. ZeroBot is genuinely better — it deduplicates, detects contradictions, tracks provenance. But it's still fundamentally a smart filing cabinet.

What nobody has built is a memory that *pushes back*.

Imagine: you're about to make a decision and the system says "hold on, you've made this exact call three times. You regretted it twice. Are you sure?" That's what `regret_detector.py` (F58) is doing. But it's dormant — it's sitting in a module waiting to be called. What if instead it was running continuously, proactively surfacing patterns before you have to ask?

The vision isn't a search engine. It's a partner who has read everything you've ever thought, noticed patterns you haven't, and isn't afraid to mention them. That's the gap between where this system is and where it could go.

---

## Idea 1: Confidence momentum — memories that fight to stay alive

Right now confidence is a static score. A memory gets confirmed a few times and sits at 0.8 indefinitely. But confidence should decay if a memory isn't being reinforced. A preference you stated 18 months ago but never mentioned since — is that still true? The system should start asking.

**The wild version:** Memories have a "fight-or-die" mechanic. When importance drops below 0.3 and the memory hasn't been accessed in 90 days, instead of silently archiving it, the system asks you once: "You mentioned X on [date]. Still relevant?" One confirmation: the memory resets. No response in 48 hours: archived. The memory had to earn its keep.

This creates a living memory corpus — constantly pruned, always current, never stale by default. The current decay system does the math but doesn't close the loop with the user.

The implementation is straightforward given what already exists: `decay_predictor.py` identifies candidates, `confidence_scoring.py` tracks state, a new `review_prompt_generator.py` generates the ask. A LaunchAgent fires the review cycle weekly. Lee gets a Pushover notification ("3 memories need your review") and responds in a simple CLI command. Five minutes, once a week, and the corpus is permanently alive.

---

## Idea 2: Memory clustering as a conversation starter

`intelligence/clustering.py` (F25) groups semantically similar memories. But the output currently goes nowhere — it's computed and stored but nothing acts on it.

**The wild version:** When you start a session, the system doesn't just load recent memories. It loads *cluster summaries*. "You have 14 memories in the Connection Lab cluster — last updated 3 days ago. The dominant theme has shifted from 'positioning' to 'pricing objections.'" That's a morning briefing that took no effort to write.

Take it further: cluster divergence as an insight signal. When a cluster that was previously coherent starts splitting into two, it usually means a belief or approach is evolving. "Your thinking about content strategy used to be unified (blog posts + social = same audience). Over the last month it's split into two distinct clusters (thought leadership vs lead generation). Intentional?" That's the kind of pattern you'd never spot manually.

The work to add this is modest: a `ClusterMonitor` class that compares cluster state across runs, detects splits/merges, and queues insights for the morning briefing. The heavy lifting (actual clustering) already runs in F25.

---

## Idea 3: The session wrapper — automatic end-of-session memory extraction

Right now memories are saved in two ways: the user explicitly says "remember this," or the pre-compaction flush extracts facts when a session hits 50 messages. Both have failure modes. Explicit saves are inconsistent (you forget). Pre-compaction fires late and only covers a narrow window.

**The wild version:** Every session ends with a 30-second synthesis. When the Claude Code window closes (a hook event), an async agent spins up, reads the last session's transcript, extracts 3–7 memories, runs contradiction detection, saves them with session provenance, and posts a summary to Pushover: "Session ended. Saved 5 memories. 1 contradiction resolved (dark mode preference updated)."

This is the pattern from ZeroBot's pre-compaction flush, but applied to *every session end* instead of waiting for the 50-message threshold. The system is already close — `session_consolidator.py` does the extraction, the hooks infrastructure can fire on window close, and `send_poke_pushover.py` handles notifications. The missing piece is the hook and the async trigger.

This would transform the memory system from "fires when it happens to" to "catches everything automatically." That's the promise of autonomous memory.

---

## Idea 4: Cross-client pattern transfer as active intelligence

`wild/pattern_transfer.py` (F56) exists but `cross_project_sharing.py` is a stub. The vision is compelling: Lee solves a positioning problem for Cogent Analytics, and the system notices the same positioning problem emerging in Connection Lab and surfaces the Cogent solution proactively.

**The wild version:** Not just "here's a similar memory from another client." Instead: "Connection Lab is showing early signs of the same positioning trap that Cogent had in October (feature-led messaging, unclear buyer). The Cogent breakthrough: lead with CFO pain, not capability. Applied to Connection Lab: lead with partner anxiety, not platform features." That's an agent synthesizing across two projects, generating a hypothesis, and surfacing it as an actionable suggestion.

The privacy question is real but solvable: a tag-based consent model where clients can be flagged `cross_client_ok: true` by Lee. Within that consent boundary, pattern transfer is aggressive.

The infrastructure already has `pattern_transfer.py`, `client_pattern_transfer.py` (from F56), and `cross_project_sharing.py`. What's missing is the synthesis layer — an agent that reads across tagged insights and generates cross-client hypotheses. This is a task for `wild/dream_synthesizer.py` running with a cross-client lens.

---

## Idea 5: The decision regret loop — real-time warning before you repeat mistakes

`wild/regret_detector.py` (F58) tracks decisions and their outcomes. It knows Lee has made a certain class of mistake repeatedly. But the detection fires after the fact — it's a retrospective.

**The wild version:** Real-time decision gating. When a new decision is being discussed in a session, a hook intercepts it and checks against the regret database before the session ends. "Before you commit to X: you've made a similar call 4 times. Three of those you rated negatively in retrospect. The common thread was [Y]. Is Y present here?"

This is pre-crime prevention for decision errors. The challenge is detection: how does the system know a decision is being made vs discussed? The `event_detector.py` (already exists) has patterns for detecting decisions. Wire it to the regret database.

The user experience could be as lightweight as a Pushover notification at end-of-session: "Decision pattern detected. Before you act on [X], here's your track record on similar calls." Lee has 30 seconds to review before committing. Low friction, high value.

---

## Idea 6: Energy-aware memory loading

`wild/energy_scheduler.py` (F53) knows Lee's best thinking hours. Morning = deep work. Afternoon = administrative tasks. 3pm is a trough.

**The wild version:** Load different memory packages depending on time of day. 9am session: load strategic memories (decisions, frameworks, positioning work). 3pm session: load operational memories (task lists, commitments, logistics). Session at 11pm: load reflective memories (patterns, lessons learned, what worked today).

This isn't about restricting access — it's about surfacing the most relevant context for the cognitive state you're in. A morning session on Connection Lab strategy doesn't need to start with last month's billing logistics. A 3pm task-clearance session doesn't need to start with the brand strategy framework.

Implementation: extend `session_consolidator.py`'s context loading to consult `energy_scheduler.py` for the current energy state, then select from different memory priority queues based on that state. Memory types have a `time_of_day_relevance` field. The scheduler determines which queue to load from.

---

## Idea 7: Frustration archaeology — learning from past spirals

`wild/frustration_detector.py` (F55) detects frustration *as it happens*. But the system only looks backward 20 minutes. What about the pattern across months?

**The wild version:** A frustration archaeology report. Run weekly, analyze all frustration events in `intelligence.db` over the last 90 days. Cluster them: "You've had 23 frustration events. They cluster into 3 patterns: (1) Webflow rendering bugs — 8 events, avg 2 hours resolution time. (2) Claude going too deep on technical topics — 7 events, all resolved by redirecting to business framing. (3) Client revision cycles — 5 events, highest emotional intensity."

For pattern 1 (Webflow), the insight might be: "Every one of these started with a CSS specificity issue. Consider adding a reference hook for Webflow specificity rules." For pattern 2: "Your hookify rules have already addressed some of these. Three are still open — want to add rules now?"

This is the mistake cascade detector (F65) running with a longer time horizon and a clustering lens. It turns incident response into preventive maintenance.

---

## Idea 8: The memory interview — structured periodic review

Every productivity system eventually has too much stuff. The inbox fills up. The archive grows. Even with decay, a corpus of 2,300 memories is dense.

**The wild version:** A weekly 10-minute memory interview. Not "review your memories" — that's a chore. Instead: the system interviews *you*. Five questions, generated from patterns it noticed:

"Last week you had 4 sessions on Connection Lab pricing. Your oldest memory about Connection Lab is from October and says 'pricing conversations feel premature.' Is that still true?"

"You saved 3 memories about async communication preferences. They tell inconsistent stories. Let me show you all three — which one is current?"

"Your decision journal shows a decision on Jan 12 that you haven't rated yet. What happened?"

The interview is generated by `wild/dream_synthesizer.py` looking for contradiction clusters, stale high-importance memories, and un-rated decisions. Output is a structured 5-question markdown file. Lee responds inline. The responses update confidence scores, resolve contradictions, and close out the decision journal entries.

Total time: 10 minutes. Result: living corpus, zero maintenance overhead feel.

---

## Idea 9: Persona-aware memory filtering

Lee has multiple modes: business consultant Lee, health-tracking Lee, technical builder Lee, family administrator Lee. Each mode has different relevant memories.

**The wild version:** When Claude Code detects the project context (LFI business work vs Health project vs terra-office explainer), it loads a different memory subset. LFI project: load client memories, messaging frameworks, sales pipeline context. Health project: load health tracking memories, therapy notes, pattern data. Personal: load family commitments, logistics, financial context.

This is already partially true — memories have project_id tags. But there's no orchestration layer that *enforces* relevance filtering. The Claude Code project's CLAUDE.md context loading is the hook. Add a `MemoryFilter` class that takes `project_context: str` and returns a filtered, ranked memory set. Session startup becomes: "current project = LFI → load LFI-tagged + universal memories, suppress personal and health memories."

The psychological benefit is real: Lee shouldn't be thinking about Terra's sublease during a Cogent Analytics messaging session. Context segregation is a feature, not a limitation.

---

## Idea 10: The "explain why you remembered this" layer

When the system surfaces a memory as relevant to a query, it should explain its reasoning. Not just "here's a memory about dark mode" but "I'm showing you this because: (1) semantic similarity 0.87 — 'workspace preferences' matches 'office setup,' and (2) this memory was confirmed twice in the last month, giving it high confidence."

This is transparency-as-trust-building. Lee has expressed frustration with silent failures and opaque system behavior. A memory system that explains itself isn't just nicer — it's more trustworthy and debuggable.

Implementation: Add a `relevance_explanation` field to search results. Hybrid search already computes semantic_score, bm25_score, and hybrid_score. Add one more field: `explanation = f"Semantic match: {semantic_score:.0%}. Confirmed {confirmations}x. Tags overlap: {matching_tags}."` The frontend renders this as an expandable "why?" tooltip on each memory card.

This costs almost nothing to add (all the data is already computed) and substantially reduces the "why is it showing me this?" friction.

---

## Idea 11: Memory-as-training-data

Here's the long-game vision: the 2,300 memories, 779 sessions, and 177K messages are a dataset. Not just for Lee's personal use — as fine-tuning data for a model that knows Lee's communication style, preferences, and decision patterns deeply.

The practical version doesn't require model training. It uses the existing FSRS-6 scheduler (F27) as a guide: A-grade memories become "gold standard" examples of what a good memory looks like. The `prompt_evolver.py` (F63) already runs genetic algorithm optimization on extraction prompts using quality grades as fitness scores.

**The wild version:** Export the full corpus in a format suitable for few-shot prompting or fine-tuning. Build a `corpus_exporter.py` that outputs: (1) A/B/C/D graded memories as examples for "what is a good memory" classification. (2) Confirmed corrections as preference examples. (3) Session→memory extraction pairs as training data for the extraction model.

This isn't just export — it's self-improving infrastructure. Every A-grade memory Lee confirms makes the extraction model smarter on the next training cycle. The system feeds on its own output.

---

## The through-line

Looking across all the ideas: the wild/ features are ambitious but scattered. Dream synthesis, momentum tracking, energy scheduling, regret detection — each is interesting alone. Together they're a system.

The missing connective tissue is a **memory brain stem** — a background process that runs 24/7, reads all the outputs from the wild/ features, synthesizes them into a small number of high-priority signals, and surfaces exactly what Lee needs without requiring him to ask.

Ben built this for ZeroBot with the 11 layers and 10 mechanisms. Lee has the components. What's missing is the conductor — an `intelligence_orchestrator.py` that wires them together into a coherent system, not just a collection of features.

That's the next phase. Not more features. Integration.

The components are: frustration archaeology (F55+archaeology), decision gating (F58 + real-time), energy-aware loading (F53 + session startup), weekly interview (dream synthesizer + contradiction detector), and provenance-tagged everything (Gap 1).

Wire those together, add the circuit breaker so it doesn't collapse when Claude API has a bad night, and you have a memory system that genuinely thinks alongside you — not just stores things for you.

---

*1,800 words. All grounded in existing architecture. None of this requires a new database, new infrastructure, or external APIs.*
