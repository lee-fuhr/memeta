# Memory Meta — Standing on the shoulders of giants

Research compiled: February 2026

This document synthesizes the open-source LLM memory landscape as of early 2026, identifying key projects and how Memory Meta synthesizes and extends prior art.

---

## Key finding

The memory systems ecosystem has matured into **distinct philosophical camps**, each solving the same fundamental problem (agents need persistent, retrievable context) through fundamentally different architectural approaches.

**Memory Meta's position:** Universal memory layer that bridges all approaches — semantic vectors, knowledge graphs, temporal reasoning, compression, consolidation — under one platform.

---

## Core memory systems (ranked by community adoption)

### 1. mem0 — Universal memory layer
- **GitHub:** [mem0ai/mem0](https://github.com/mem0ai/mem0)
- **Stars:** ~46,800 (as of Feb 2026)
- **Approach:** Hybrid triple storage (vector + graph + key-value) for semantic memory
- **Philosophy:** "Memory for any LLM API" — agnostic to the underlying model
- **Core mechanism:**
  - Vector database for semantic similarity search
  - Graph database for relationship modeling
  - Key-value store for fast fact retrieval
  - Unified API: `memory.add(data)` → extraction → storage in all three

**Performance (LOCOMO benchmark):**
- 26% higher accuracy than OpenAI's native memory
- 91% lower latency than full-context approaches
- 90% token cost savings

**What overlaps with Memory Meta:**
- Fact extraction and storage
- Multi-modal storage backends
- Semantic similarity retrieval
- User preference learning

**License:** Apache 2.0

---

### 2. Letta (formerly MemGPT) — Stateful agents with memory hierarchy
- **GitHub:** [letta-ai/letta](https://github.com/letta-ai/letta)
- **Approach:** OS-inspired memory hierarchy (core memory ≈ RAM, archival ≈ disk)
- **Philosophy:** "LLMs as operating systems" — treat context window as scarce resource, move data between tiers
- **Core mechanism:**
  - **Core memory:** In-context (system prompt, working scratch, conversational history)
  - **Archival memory:** External storage (full conversation logs)
  - **Recall memory:** Intermediate retrieval cache
  - Intelligent context eviction and re-population
  - Interrupts/callbacks for control flow management

**Recent developments (2026):**
- Context Repositories — git-based versioning of agent memory state
- Conversations API — shared memory across parallel user interactions
- Letta Code (coding agent) — #1 on Terminal-Bench LLM leaderboard

**What overlaps with Memory Meta:**
- Hierarchical memory (working vs. long-term vs. archival)
- Context window optimization
- Multi-stage retrieval
- State management for agents

**License:** MIT

**Research foundation:** ["MemGPT: Towards LLMs as Operating Systems"](https://arxiv.org/abs/2310.08560) (Packer et al., 2023)

---

### 3. Zep — Temporal knowledge graph for agent memory
- **GitHub:** [getzep/zep](https://github.com/getzep/zep)
- **Stars:** ~4,035 (main repo), ~20,000 (Graphiti subproject)
- **Approach:** Temporal knowledge graph engine (Graphiti) that builds and maintains KGs with temporal awareness
- **Philosophy:** "Memory that understands change over time" — track how relationships and context evolve
- **Core mechanism:**
  - **Graphiti:** Temporal knowledge graph framework
    - Autonomously builds KGs from unstructured conversations
    - Each fact tagged with valid_at/invalid_at timestamps
    - Synthesizes conversational data + structured business data
    - Maintains historical relationship chains
  - **Vector store:** Postgres + pgvector for semantic search
  - **Graph store:** Neptune/FalkorDB support (2025 addition)
  - **Text search:** Amazon OpenSearch integration

**Performance (benchmarks):**
- Deep Memory Retrieval: 94.8% accuracy vs. MemGPT's 93.4%
- LongMemEval (complex temporal tasks): 18.5% accuracy improvement + 90% latency reduction

**What overlaps with Memory Meta:**
- Temporal reasoning and change tracking
- Knowledge graph construction
- Multi-modal storage (graph + vector + text)
- Complex query resolution across time

**License:** MIT/Open source

**Powered by:** [getzep/graphiti](https://github.com/getzep/graphiti) (20K stars)

---

### 4. Memary — Knowledge graphs for agents
- **GitHub:** [kingjulio8238/Memary](https://github.com/kingjulio8238/Memary)
- **Approach:** Multi-tier knowledge graphs for semantic memory
- **Philosophy:** "Human-like memory for autonomous agents" — emulate how humans consolidate memories
- **Core mechanism:**
  - **Memory Stream:** Sequential entity+timestamp capture (all interactions)
  - **Entity Knowledge Store:** Frequency/recency tracking (what matters most)
  - **Knowledge Graph:** FalkorDB for relationship storage
  - **Recursive retrieval:** Extract key entities → build localized subgraph → generate response
  - Frequency-biased relevance (recency + mentions)

**Model support:** Ollama (Llama 3 8B/40B) or OpenAI GPT-3.5-turbo

**What overlaps with Memory Meta:**
- Entity extraction and tracking
- Frequency-biased relevance scoring
- Knowledge graph as primary storage
- Recursive retrieval patterns

**License:** Open source

---

### 5. SimpleMem — Efficient lifelong memory via compression
- **GitHub:** [aiming-lab/SimpleMem](https://github.com/aiming-lab/SimpleMem)
- **Approach:** Three-stage semantic lossless compression pipeline
- **Philosophy:** "Maximum information density, minimum tokens" — compress interactions into actionable summaries
- **Core mechanism:**
  - **Stage 1: Semantic Structured Compression**
    - Entropy-aware filtering (discard noise)
    - Multi-view indexed memory units (different summaries for different contexts)
  - **Stage 2: Recursive Memory Consolidation**
    - Asynchronous integration of related units
    - Hierarchical abstraction (raw facts → patterns → themes)
    - Reduce redundancy through consolidation
  - **Stage 3: Adaptive Query-Aware Retrieval**
    - Dynamic scope adjustment based on query complexity
    - Construct precise context without over-fetching

**Performance:**
- 26.4% F1 improvement over baselines
- 30× token reduction at inference time
- **SimpleMem-Cross:** Persistent memory across conversation sessions

**What overlaps with Memory Meta:**
- Consolidation and hierarchical abstraction
- Compression and entropy-aware filtering
- Query-aware retrieval scope
- Cross-conversation persistence

**License:** Open source (research-backed)

---

### 6. LangChain memory ecosystem
- **Source:** [LangChain Memory Documentation](https://python.langchain.com/api_reference/core/vectorstores/langchain_core.vectorstores.in_memory.InMemoryVectorStore.html)
- **Approach:** Modular memory blocks for different use cases
- **Philosophy:** "Building blocks for memory" — don't prescribe a single pattern, enable many
- **Core components:**
  - **MemoryVectorStore:** In-memory vector search (FAISS, Chroma, Pinecone, Milvus)
  - **InMemoryVectorStore:** Ephemeral embeddings with cosine similarity
  - **Chat message history:** FIFO or summarization-based retention
  - Customizable memory classes for app-specific needs
  - Cosine/Euclidean/Hamming similarity metrics

**Use pattern:** Embedding → Store → Retrieve (semantic) → Inject into context

**What overlaps with Memory Meta:**
- Vector storage and similarity search
- Multiple similarity metrics
- Modular/pluggable approach
- Integration with external vector DBs

**License:** MIT

---

### 7. LlamaIndex memory blocks (2026 updates)
- **Source:** [LlamaIndex Memory Documentation](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/memory/)
- **Approach:** Context engineering with memory blocks
- **Philosophy:** "Structured context for complex reasoning" — don't just store, architect context strategically
- **Core components:**
  - **StaticMemoryBlock:** Static reference information
  - **FactExtractionMemoryBlock:** Extraction from chat history
  - **VectorMemoryBlock:** Batch message storage in vector DB
  - **Agent Workflow integration:** MCP server support, filesystem/bash tools, TODO tracking
  - Context ratio management (token allocation)

**2026 additions:**
- Memory blocks + agent workflows for dynamic context construction
- MCP server protocol for tools/skills
- Step-by-step context optimization

**What overlaps with Memory Meta:**
- Structured memory extraction (facts)
- Different block types for different purposes
- Context ratio management
- Integration with agent orchestration

**License:** MIT

---

### 8. Other notable systems

#### Graphiti (Zep's engine)
- **GitHub:** [getzep/graphiti](https://github.com/getzep/graphiti)
- **Stars:** ~20,000
- **Approach:** Temporal knowledge graph for real-time graph construction
- **What it does:** Autonomous KG building from conversations, temporal reasoning
- **Integration:** Now integrated into Neptune, FalkorDB
- **License:** MIT

#### Cognee
- **Approach:** Conversation → semantic memory nodes and edges
- **What it does:** Turn all input (text, documents, images, audio) into KG nodes
- **License:** Open source

#### OpenMemory
- **GitHub:** [CaviraOSS/OpenMemory](https://github.com/CaviraOSS/OpenMemory)
- **Approach:** Local persistent memory for Claude Desktop, GitHub Copilot, etc.
- **What it does:** Explainable memory engine with LangGraph integration
- **License:** Open source

---

## Architectural patterns (what Memory Meta synthesizes)

### Storage tier patterns
| Pattern | Example projects | Memory Meta relevance |
|---------|------------------|----------------------|
| **Vector-only** | LangChain, LlamaIndex | Single modality limitation |
| **Vector + KG** | mem0, Zep, Memary | Comprehensive relationship + semantic coverage |
| **Vector + KG + KV** | mem0 (triple) | Fast fact lookup + reasoning |
| **Temporal KG** | Zep/Graphiti, SimpleMem | Change tracking, consolidation |

**Memory Meta synthesis:** Supports all four tiers. User decides based on use case (simple semantic search vs. complex reasoning).

### Retrieval patterns
| Pattern | Example projects | Memory Meta relevance |
|---------|------------------|----------------------|
| **Similarity search** | LangChain, LlamaIndex, mem0 | Semantic matching |
| **Graph traversal** | Memary, Zep | Entity relationships |
| **Temporal queries** | Zep, SimpleMem | "When did X happen?" |
| **Recursive/multi-hop** | Memary, Letta | Complex query decomposition |
| **Query-aware scope** | SimpleMem | Efficiency (don't fetch unnecessary context) |

**Memory Meta synthesis:** Implements all five patterns with pluggable retrieval orchestrator.

### Consolidation patterns
| Pattern | Example projects | Memory Meta relevance |
|---------|------------------|----------------------|
| **Hierarchical abstraction** | SimpleMem, Letta | Raw → summaries → themes |
| **Entity deduplication** | Memary, Zep | Merge duplicate entities |
| **Temporal compression** | SimpleMem | Lossless compression |
| **Frequency-biased pruning** | Memary | Keep high-signal memories |

**Memory Meta synthesis:** Scheduled consolidation with multiple algorithms (user selects).

### Context window optimization
| Pattern | Example projects | Memory Meta relevance |
|---------|------------------|----------------------|
| **Tier-based eviction** | Letta | Core/recall/archival |
| **Token budget management** | LlamaIndex | Allocate token percentage to memory |
| **Compression** | SimpleMem | Reduce memory token footprint |
| **Intelligent summarization** | Letta, LlamaIndex | Lossy summaries for working context |

**Memory Meta synthesis:** Adaptive context budgeting based on query complexity.

---

## Competitive landscape summary

### By philosophy

**"Universal memory layer" (API-first)**
- mem0 (dominant)
- Memory Meta (synthesis)

**"OS-inspired hierarchy" (context optimization)**
- Letta (clear leader)
- Memory Meta (broader approach)

**"Temporal reasoning" (time-aware KGs)**
- Zep/Graphiti (most sophisticated)
- Memory Meta (additional patterns)

**"Efficient compression" (token optimization)**
- SimpleMem (most advanced)
- Memory Meta (integrated)

**"Memory blocks/composable" (modular)**
- LangChain, LlamaIndex
- Memory Meta (full systems, not blocks)

### Adoption metrics (Feb 2026)
| Project | GitHub stars | Primary use | Maturity |
|---------|-------------|------------|----------|
| mem0 | ~46.8K | API memory layer | Production |
| Graphiti | ~20K | Knowledge graphs | Production |
| Zep | ~4K | Agent memory platform | Production |
| Letta | Unknown (likely 13K+) | Stateful agents | Production |
| SimpleMem | Unknown | Research/early adoption | Research |
| LangChain | >100K | Frameworks (memory is 1 module) | Production |
| LlamaIndex | >50K | Frameworks (memory is 1 module) | Production |
| Memary | Unknown | Autonomous agents | Early adoption |

---

## Key differentiators for Memory Meta rebranding

### What Memory Meta offers that the ecosystem doesn't

1. **Everything at once**
   - Unlike mem0 (triple), Letta (hierarchy), Zep (temporal), SimpleMem (compression), or LangChain/LlamaIndex (modular blocks), Memory Meta runs all approaches simultaneously
   - User doesn't choose: all features are active, all optimizations run

2. **Cognitive psychology foundation**
   - Draws from research on human memory (forgetting curves, spacing effects, consolidation theory)
   - Other projects focus on CS/DB techniques (vectors, graphs, compression)
   - Memory Meta makes psychology actionable (emotion tagging, consolidation schedules)

3. **Autonomous consolidation**
   - SimpleMem has stage 2 consolidation, Letta has implicit eviction
   - Memory Meta explicitly runs scheduled consolidation with multiple strategies
   - Users can tune or let it run automatically (dream mode)

4. **Wild features** (experimental)
   - Frustration scoring (emotion state tracking)
   - Regret detection (decision reversals)
   - Energy level tracking (cognitive load)
   - None of the other projects track these
   - Memory Meta's competitive moat

5. **Dashboard and observability**
   - mem0 has APIs, Letta has UI, Zep has platform
   - Memory Meta has full intelligence dashboard (clustering, synthesis, metrics)
   - User can see why memories are being consolidated, what was forgotten

6. **101 features** (vs. systems with 15-30 each)
   - mem0: hybrid storage, fact extraction, user preferences (~15)
   - Letta: hierarchical context, interrupts, state management (~12)
   - Zep: temporal KG, synthesis, temporal queries (~10)
   - SimpleMem: compression, consolidation, query-aware retrieval (~8)
   - LangChain: modular blocks, multiple backends (~20)
   - Memory Meta: union of all + cognitive features + wild features + orchestration = **101**

---

## Attribution strategy for "Standing on the shoulders of giants"

### README section structure

```markdown
## Standing on the shoulders of giants

Memory Meta synthesizes proven memory architectures from across the open-source AI ecosystem. We give full credit to the researchers, engineers, and communities who pioneered these approaches.

### Core architectural inspirations

**Semantic storage + relationships (mem0)**
- Triple storage pattern (vector + graph + key-value)
- "Universal memory layer" philosophy
- Fact extraction and multi-modal storage

**Memory hierarchy + context optimization (Letta/MemGPT)**
- OS-inspired tier management (core/recall/archival)
- Context window as scarce resource
- Virtual memory and intelligent eviction

**Temporal knowledge graphs (Zep/Graphiti)**
- Time-aware relationship modeling
- Autonomous knowledge graph construction
- Temporal reasoning and change tracking

**Semantic compression (SimpleMem)**
- Lossless semantic compression via entropy filtering
- Hierarchical abstraction and consolidation
- Query-aware retrieval scope

**Modular memory blocks (LangChain/LlamaIndex)**
- Fact extraction blocks
- Customizable memory patterns
- Integration with multiple storage backends

**Human memory theory**
- Ebbinghaus forgetting curves (spacing effect)
- Consolidation and replay during sleep
- Emotion-tagged memory enhancement
- Retrieval practice and active recall

### Open-source projects we build on
- [mem0ai/mem0](https://github.com/mem0ai/mem0) — Universal memory layer (Apache 2.0)
- [letta-ai/letta](https://github.com/letta-ai/letta) — Stateful agents with memory hierarchy (MIT)
- [getzep/zep](https://github.com/getzep/zep) + [getzep/graphiti](https://github.com/getzep/graphiti) — Temporal knowledge graphs (MIT)
- [aiming-lab/SimpleMem](https://github.com/aiming-lab/SimpleMem) — Efficient lifelong memory (research)
- [LangChain](https://github.com/langchain-ai/langchain) — Memory blocks and integrations (MIT)
- [LlamaIndex](https://github.com/run-llama/llama_index) — Context engineering (MIT)

### How we differ

Memory Meta doesn't replace these projects — it synthesizes them. Where mem0 chooses triple storage, Letta chooses hierarchy, and Zep chooses temporal reasoning, Memory Meta runs all approaches simultaneously in a unified system designed for both development and autonomous operation.

### Research references
- MemGPT: Towards LLMs as Operating Systems ([Packer et al., 2023](https://arxiv.org/abs/2310.08560))
- SimpleMem: Efficient Lifelong Memory for LLM Agents ([arXiv:2601.02553](https://arxiv.org/html/2601.02553v1))
- ZEP: A Temporal Knowledge Graph Architecture for Agent Memory ([Rasmussen, 2025](https://arxiv.org/html/2501.13956v1))
- Ebbinghaus Forgetting Curve (foundational human memory research)

```

---

## Next steps

1. **Create INSPIRATION.md** in Memory Meta repo
   - Extended version of above
   - Link to each project's specific techniques used
   - Cite all research papers

2. **Update README.md**
   - Add "Standing on the shoulders of giants" section
   - Link to INSPIRATION.md
   - Position as "synthesis" not "competitor"

3. **Create ARCHITECTURE-COMPARISON.md**
   - Side-by-side feature comparison (101 Memory Meta features vs. other systems)
   - Philosophy comparison (CSS table or matrix)
   - Performance comparison (where data available)

4. **GitHub discussions**
   - Reach out to mem0, Letta, Zep authors with rebranding announcement
   - Mention synthesis approach, link to INSPIRATION.md
   - Invite collaboration on overlapping research interests

5. **License audit**
   - Memory Meta: Apache 2.0 (current)
   - Verify no GPL dependencies that would require relicensing
   - Consider dual-licensing MIT for compatibility with Letta/Zep ecosystem

---

## Competitive positioning (one-liner for marketing)

> **Memory Meta is the kitchen sink of memory systems: every proven approach in one place, running simultaneously, intelligently managed.**

Or more formally:

> **Memory Meta synthesizes semantic vectors, knowledge graphs, temporal reasoning, compression, consolidation, and cognitive psychology into a unified, autonomous memory system for AI agents.**

---

## Key sources cited

1. [mem0ai/mem0 GitHub](https://github.com/mem0ai/mem0)
2. [letta-ai/letta GitHub](https://github.com/letta-ai/letta)
3. [getzep/zep GitHub](https://github.com/getzep/zep)
4. [getzep/graphiti GitHub](https://github.com/getzep/graphiti)
5. [kingjulio8238/Memary GitHub](https://github.com/kingjulio8238/Memary)
6. [aiming-lab/SimpleMem GitHub](https://github.com/aiming-lab/SimpleMem)
7. [Zep Blog: Temporal Knowledge Graph Architecture](https://blog.getzep.com/)
8. [Letta Website: MemGPT framework](https://www.letta.com/)
9. [MemGPT Research Paper (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560)
10. [SimpleMem Research (arXiv:2601.02553)](https://arxiv.org/html/2601.02553v1)
11. [LangChain Memory Documentation](https://python.langchain.com/docs/modules/memory/)
12. [LlamaIndex Memory Documentation](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/memory/)
