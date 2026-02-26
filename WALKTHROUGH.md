# Memory System v1 - Architecture Walkthrough

**Purpose:** Understand how the Memory System extracts, stores, searches, and synthesizes knowledge from Claude Code sessions.

**Reading time:** ~20 minutes
**Codebase:** 122 source modules, 2023 passing tests

---

## Table of contents

1. [System overview](#system-overview)
2. [Entry point: Session end hook](#entry-point-session-end-hook)
3. [Core pipeline: Session consolidation](#core-pipeline-session-consolidation)
4. [Storage layer: Memory files + databases](#storage-layer-memory-files--databases)
5. [Search layer: Hybrid semantic + keyword](#search-layer-hybrid-semantic--keyword)
6. [Intelligence layer: Clustering + orchestrator](#intelligence-layer-clustering--orchestrator)
7. [Access layer: Dashboard + API](#access-layer-dashboard--api)
8. [Configuration](#configuration)

---

## System overview

The Memory System is a four-layer architecture that transforms Claude Code sessions into searchable, analyzable knowledge:

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPTURE LAYER                                                   │
│  hooks/session-memory-consolidation-async.py                    │
│  → Triggers on session end, queues consolidation job            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  CORE PIPELINE                                                   │
│  session_consolidator.py + memory_ts_client.py                  │
│  → Reads JSONL → Extracts patterns → Scores importance → Saves  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STORAGE LAYER                                                   │
│  • YAML files: ~/.local/share/memory/LFI/memories/*.md          │
│  • intelligence.db: Clusters, relationships, analytics          │
│  • FAISS vectors: Semantic search index                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  INTELLIGENCE LAYER                                              │
│  intelligence/clustering.py + intelligence_orchestrator.py      │
│  → K-means topic clusters → Daily briefings → Insights          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  ACCESS LAYER                                                    │
│  dashboard/server.py (Flask) → http://localhost:8766            │
│  → Search, browse clusters, view analytics                      │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight:** The system is a **write-once, read-many** architecture. Memories are extracted once after a session, then queried, searched, clustered, and analyzed repeatedly.

---

## Entry point: Session end hook

**File:** `hooks/session-memory-consolidation-async.py`

When a Claude Code session ends, this hook automatically triggers. It's fast (<100ms) because it just adds the session to a background queue.

**What it does:**
1. Reads session ID and project path from stdin (Claude Code provides this)
2. Constructs path to the session JSONL file
3. Adds job to `async_consolidation.py` queue
4. Returns immediately (doesn't block session end)

**Key code from hook:**
```python
def main():
    """Fast SessionEnd hook - just adds to queue"""
    hook_input = json.load(sys.stdin)
    session_id = hook_input.get('sessionId')
    project_path = hook_input.get('projectPath')

    # Construct session path
    session_file = Path(project_path) / f"{session_id}.jsonl"

    # Add to background queue
    queue = ConsolidationQueue()
    queue.add(session_file, project_id="LFI")
```

**Why async?** Previous versions blocked for 10-30 seconds during LLM extraction, making session end feel slow. The queue-based approach returns instantly.

**Background worker:** `async_consolidation.py` runs continuously, processing the queue every 30 seconds. Uses `fcntl` file locking to prevent concurrent processing.

---

## Core pipeline: Session consolidation

**File:** `src/session_consolidator.py` (729 lines - largest module in the system)

This is the heart of the system. It reads session JSONL files and extracts learnings using regex patterns + LLM analysis.

### Step 1: Read session JSONL

```python
def read_session(self, session_file: Path) -> List[Dict[str, Any]]:
    """Read session JSONL file"""
    messages = []
    with open(session_file, 'r') as f:
        for line in f:
            msg = json.loads(line)
            messages.append({
                'role': msg.get('role'),
                'content': msg.get('content', [])
            })
    return messages
```

**JSONL format:** Each line is a JSON object with `role` (user/assistant) and `content` (text or tool calls). The consolidator extracts text from this structure.

### Step 2: Extract patterns

The system uses **pre-compiled regex patterns** to find learnings without LLM calls:

```python
_LEARNING_PATTERNS = [
    re.compile(r"(?:learned|discovered|realized|found out|noticed) that ([^.!?]+[.!?])"),
    re.compile(r"(?:key insight|important to note|worth remembering):? ([^.!?]+[.!?])"),
    re.compile(r"(?:pattern|trend) (?:I noticed|observed|saw):? ([^.!?]+[.!?])"),
]

_CORRECTION_PATTERNS = [
    re.compile(r"user:.*?(?:actually|correction|no,|wrong|mistake|should be) ([^.!?]+[.!?])"),
]

_PROBLEM_SOLUTION_PATTERN = re.compile(
    r"(?:problem|issue|challenge):.*?([^.!?]+[.!?]).*?(?:solution|fix|approach):.*?([^.!?]+[.!?])",
)
```

**Why regex first?** Fast, deterministic, no API costs. Catches 60-70% of learnings without LLM.

### Step 3: Garbage detection

Not all extracted text is useful. The system filters out:

```python
_META_KEYWORDS = (
    'memory system', 'memory extraction', 'session consolidat',
    'embedding', 'fsrs', 'semantic search', 'hybrid search',
)

def _is_garbage_content(text: str) -> bool:
    """Check if extracted content is garbage"""
    # Too short
    if len(text.strip()) < 30:
        return True

    # Meta-memories (about the memory system itself)
    if any(keyword in text.lower() for keyword in _META_KEYWORDS):
        return True

    # Tool call artifacts (toolu_, JSON structures)
    if 'toolu_' in text or "'input': {" in text:
        return True

    # Line number dumps (file content from Read tool)
    if re.search(r'\d+[→\t].*\d+[→\t].*\d+[→\t]', text):
        return True

    return False
```

**Critical filter:** Meta-memories (memories about the memory system itself) are auto-rejected. This prevents the system from filling up with self-referential noise.

### Step 4: Score importance

Each extracted memory gets an importance score (0.0-1.0):

```python
from .importance_engine import calculate_importance

importance = calculate_importance(
    content=memory_text,
    context_hints={
        'is_correction': True,  # Higher importance
        'has_code_example': True,  # Higher importance
        'session_quality': 0.8,  # Session-level quality boost
    }
)
```

**Factors:**
- Corrections from user: +0.2
- Code examples: +0.15
- Problem-solution pairs: +0.15
- Vague language ("maybe", "probably"): -0.1
- First-person discoveries ("I learned"): +0.1

### Step 5: Deduplicate

Before saving, check if this memory already exists:

```python
def _deduplicate_memories(
    self,
    new_memories: List[SessionMemory],
    existing_memories: List[Memory]
) -> List[SessionMemory]:
    """Remove memories that are too similar to existing ones"""

    # Normalize text (lowercase, remove punctuation)
    normalized_existing = {
        self._normalize_content(mem.content): mem.id
        for mem in existing_memories
    }

    deduplicated = []
    for new_mem in new_memories:
        normalized_new = self._normalize_content(new_mem.content)

        # Exact match after normalization
        if normalized_new in normalized_existing:
            continue

        # Semantic similarity check (if embeddings available)
        if self._is_semantically_similar(new_mem, existing_memories):
            continue

        deduplicated.append(new_mem)

    return deduplicated
```

**Why deduplicate?** Lee often discusses the same topics across multiple sessions. Without dedup, the system fills with near-duplicates.

### Step 6: Save to memory-ts

```python
result = self.memory_client.create(
    content=memory.content,
    importance=memory.importance,
    tags=memory.tags,
    project_id=self.project_id,
    session_id=session_id,
)
memory.id = result['id']
```

This creates a YAML file at `~/.local/share/memory/LFI/memories/{id}.md`.

---

## Storage layer: Memory files + databases

The system uses **three storage mechanisms**, each optimized for different access patterns:

### 1. YAML memory files (source of truth)

**Location:** `~/.local/share/memory/LFI/memories/`

Each memory is a markdown file with YAML frontmatter:

```markdown
---
id: mem_2026-02-25_abc123
content: "Lee's depression correlates with sensitivity (0.781) but NOT with sleep, steps, RHR, or HRV"
importance: 0.95
tags:
  - "#health"
  - "#data-analysis"
project_id: LFI
scope: project
session_id: 2822a3f0-465a-44af-a277-1cb1c989d340
created: 2026-02-25T18:15:00
updated: 2026-02-25T18:15:00
reasoning: "Critical health insight from quantitative analysis"
confidence_score: 0.9
context_type: knowledge
temporal_relevance: persistent
knowledge_domain: health
status: active
confirmations: 0
contradictions: 0
retrieval_weight: 0.95
schema_version: 2
---

Lee's depression correlates with sensitivity (0.781) but NOT with sleep, steps, RHR, or HRV - "just exercise more" is NOT backed by his data.
```

**Why YAML + markdown?** Human-readable, git-friendly, easy to edit manually, works with standard text tools.

**File:** `src/memory_ts_client.py` (643 lines)

```python
class MemoryTSClient:
    """Client for memory-ts file-based storage"""

    def create(self, content: str, importance: float, **kwargs) -> dict:
        """Create new memory file"""
        memory_id = self._generate_id()
        memory_path = self.memory_dir / f"{memory_id}.md"

        # Write YAML frontmatter + content
        with open(memory_path, 'w') as f:
            f.write('---\n')
            yaml.dump(frontmatter, f)
            f.write('---\n\n')
            f.write(content)

        return {'id': memory_id, 'path': str(memory_path)}

    def search(self, query: str, limit: int = 20) -> List[Memory]:
        """Simple grep-based search through all memory files"""
        results = []
        for memory_file in self.memory_dir.glob('*.md'):
            memory = self._parse_memory_file(memory_file)
            if query.lower() in memory.content.lower():
                results.append(memory)
        return results[:limit]
```

### 2. Intelligence database (SQLite)

**Location:** `intelligence.db` (created at runtime, gitignored)

Stores derived data that's expensive to compute:

**Tables:**
- `memory_clusters` - K-means topic clusters
- `cluster_memberships` - Which memories belong to which clusters
- `memory_relationships` - Links between related memories
- `memory_summaries` - LLM-generated summaries of memory groups
- `daily_briefings` - Orchestrator outputs
- `memory_access_log` - Temporal access patterns (for wild/temporal_predictor.py)

**Why SQLite?** Fast aggregations, joins, indexes. Perfect for analytics queries like "show me all memories in the 'health' cluster from last week".

**File:** `src/db_pool.py` + `src/intelligence_db.py`

```python
# Connection pool (prevents "database is locked" errors)
from memory_system.db_pool import get_connection

with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT cluster_id, topic_label, COUNT(*) as member_count
        FROM memory_clusters c
        JOIN cluster_memberships m USING (cluster_id)
        GROUP BY cluster_id
    ''')
    clusters = cursor.fetchall()
```

### 3. FAISS vector index (semantic search)

**Location:** Computed on-demand, cached in memory

Used by `hybrid_search.py` for semantic similarity:

```python
import faiss
import numpy as np

# Load embeddings
embeddings = [mem.embedding for mem in memories]
embedding_matrix = np.array(embeddings).astype('float32')

# Create FAISS index (inner product = cosine similarity)
index = faiss.IndexFlatIP(embedding_matrix.shape[1])
index.add(embedding_matrix)

# Search
query_vector = embed_query(query_text)
distances, indices = index.search(query_vector, k=20)
```

**Why FAISS?** Blazingly fast vector similarity search. Can handle 10k+ memories with <50ms query time.

---

## Search layer: Hybrid semantic + keyword

**File:** `src/hybrid_search.py`

The system combines two search approaches:

### Semantic search (70% weight)

Finds memories by **meaning**, not exact words:

- Query: "office setup"
- Finds: "workspace configuration", "desk arrangement", "home office layout"

Uses sentence embeddings + FAISS cosine similarity.

### BM25 keyword search (30% weight)

Finds memories with **exact term matches**:

- Query: "office setup"
- Finds: Memories containing "office" (scored by term frequency + rarity)

BM25 formula:
```python
def bm25_score(query: str, document: str, avg_doc_length: float,
               k1: float = 1.5, b: float = 0.75) -> float:
    """
    BM25 = IDF(term) * (TF * (k1 + 1)) / (TF + k1 * (1 - b + b * doc_len/avg_len))

    Where:
    - IDF = how rare is this term across all documents
    - TF = how often does it appear in THIS document
    - k1, b = tuning parameters
    """
```

### Hybrid combination

```python
def hybrid_search(query: str, memories: List[Memory],
                 semantic_weight: float = 0.7) -> List[Memory]:
    """70% semantic + 30% keyword"""

    # Get both result sets
    semantic_results = semantic_search(query, memories)
    bm25_results = bm25_search(query, memories)

    # Normalize scores to [0, 1]
    semantic_scores = normalize_scores([r.score for r in semantic_results])
    bm25_scores = normalize_scores([r.score for r in bm25_results])

    # Combine with weights
    final_scores = {}
    for mem_id, score in semantic_scores.items():
        final_scores[mem_id] = score * semantic_weight

    for mem_id, score in bm25_scores.items():
        final_scores[mem_id] += score * (1 - semantic_weight)

    # Sort by combined score
    ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    return [memories_by_id[mem_id] for mem_id, score in ranked]
```

**Why 70/30?** Tested empirically. Semantic search is better for vague queries, but BM25 catches exact technical terms that embeddings sometimes miss.

---

## Intelligence layer: Clustering + orchestrator

### Feature 24: Memory clustering

**File:** `src/intelligence/clustering.py` (501 lines)

Auto-groups related memories into topics using K-means:

```python
class MemoryClustering:
    def cluster_memories(self, k: Optional[int] = None) -> List[Cluster]:
        """
        Cluster all memories by semantic similarity

        Steps:
        1. Load all memory embeddings
        2. Determine optimal k (if not specified) using elbow method
        3. Run K-means clustering
        4. Generate topic labels via LLM
        5. Store clusters in intelligence.db
        """

        # Load embeddings
        embeddings, memory_ids = self._load_embeddings()

        # Auto-select k (number of clusters)
        if k is None:
            k = self._find_optimal_k(embeddings)  # Elbow method

        # K-means clustering
        kmeans = KMeans(n_clusters=k, random_state=42)
        labels = kmeans.fit_predict(embeddings)

        # Generate topic labels via LLM
        clusters = []
        for cluster_id in range(k):
            member_indices = np.where(labels == cluster_id)[0]
            member_ids = [memory_ids[i] for i in member_indices]

            # Get representative memories (closest to centroid)
            representative = self._get_representatives(
                cluster_id, member_ids, embeddings, kmeans.cluster_centers_
            )

            # Ask LLM to label this cluster
            topic_label = self._generate_topic_label(representative)

            # Save to database
            self._save_cluster(cluster_id, topic_label, member_ids)

            clusters.append(Cluster(
                cluster_id=cluster_id,
                topic_label=topic_label,
                member_count=len(member_ids),
            ))

        return clusters
```

**Example output:**
```
Cluster 1: "Health data analysis" (47 memories)
Cluster 2: "Client project patterns" (83 memories)
Cluster 3: "System automation" (62 memories)
Cluster 4: "Meeting intelligence" (31 memories)
```

**Why clustering?** Lee has 2000+ memories. Browsing by topic is much more useful than a flat list.

### Intelligence orchestrator

**File:** `src/intelligence_orchestrator.py`

The "memory brain stem" - synthesizes signals from multiple analysis modules:

```python
class IntelligenceOrchestrator:
    """
    Collects signals from:
    - Dream synthesizer (cross-project insights)
    - Frustration detector (emotional friction)
    - Regret detector (decision patterns to avoid)
    - Energy scheduler (optimal task timing)
    - Momentum tracker (session progress)

    Produces daily briefing: 3-5 high-priority signals
    """

    def generate_briefing(self) -> DailyBriefing:
        """Generate daily intelligence briefing"""

        # Collect signals from all modules
        signals = collect_signals()

        # Sort by priority (high > medium > low)
        signals_by_priority = {
            'high': [s for s in signals if s.priority == 'high'],
            'medium': [s for s in signals if s.priority == 'medium'],
            'low': [s for s in signals if s.priority == 'low'],
        }

        # Take top 5 signals (prioritize high)
        final_signals = (
            signals_by_priority['high'][:3] +
            signals_by_priority['medium'][:2]
        )

        # Store briefing
        briefing = DailyBriefing(
            signals=final_signals,
            generated_at=datetime.now()
        )
        self._store_briefing(briefing)

        return briefing
```

**Example briefing:**
```
🧠 Daily Intelligence Briefing - February 25, 2026

⚠️  HIGH PRIORITY
• [ALERT] Frustration spike detected in last 3 sessions
  → Pattern: Repeated debugging of same hook issue
  → Suggestion: Step back, document problem, ask for help

• [INSIGHT] Cross-project pattern: "questioning protocol" mentioned in 8 sessions
  → This is becoming a core practice worth formalizing

🔍 MEDIUM PRIORITY
• [STATUS] Session momentum: 6/10 (below recent average)
  → Consider shorter, focused sessions instead of marathon coding
```

---

## Access layer: Dashboard + API

**File:** `dashboard/server.py` (Flask app, 350 lines)

The dashboard runs at `http://localhost:8766` and provides:

### API endpoints

```python
@app.route('/api/search', methods=['GET'])
def api_search():
    """Hybrid search endpoint"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 20))

    results = hybrid_search(query, limit=limit)
    return jsonify([r.to_dict() for r in results])

@app.route('/api/clusters', methods=['GET'])
def api_clusters():
    """List all clusters with member counts"""
    clustering = MemoryClustering()
    clusters = clustering.get_all_clusters()
    return jsonify([c.to_dict() for c in clusters])

@app.route('/api/cluster/<int:cluster_id>/members', methods=['GET'])
def api_cluster_members(cluster_id):
    """Get all memories in a cluster"""
    clustering = MemoryClustering()
    members = clustering.get_cluster_members(cluster_id)
    return jsonify([m.to_dict() for m in members])

@app.route('/api/briefing', methods=['GET'])
def api_briefing():
    """Today's intelligence briefing"""
    orch = IntelligenceOrchestrator()
    briefing = orch.get_formatted_briefing()
    return jsonify({'text': briefing})
```

### UI (single-page HTML)

**File:** `dashboard/index.html` (100KB)

Features:
- **Search bar** - Real-time hybrid search as you type
- **Cluster browser** - Navigate memories by topic
- **Analytics** - Memory count over time, importance distribution
- **Briefing** - Daily intelligence summary

Built with vanilla JavaScript (no framework), uses Fetch API to hit Flask endpoints.

---

## Configuration

**File:** `src/config.py`

All paths and settings in one frozen dataclass:

```python
@dataclass(frozen=True)
class MemorySystemConfig:
    """Frozen configuration — load once at import time."""

    # Base directories
    memory_dir: Path = Path.home() / ".local/share/memory"
    session_dir: Path = Path.home() / ".claude/projects"

    # Project
    project_id: str = "LFI"

    # Intelligence
    intelligence_db: Path = Path(__file__).parent / "intelligence.db"

    # Search
    semantic_weight: float = 0.7  # 70% semantic, 30% keyword

    # Clustering
    min_cluster_size: int = 5
    max_clusters: int = 20

    # LLM
    llm_timeout: int = 30  # seconds

# Global config instance
cfg = MemorySystemConfig()
```

**Environment overrides:**
```bash
export MEMORY_SYSTEM_MEMORY_DIR="/custom/path"
export MEMORY_SYSTEM_PROJECT_ID="Health"
```

The config reads env vars and falls back to defaults.

---

## Summary: How it all fits together

**When a session ends:**

1. **Hook** (`session-memory-consolidation-async.py`) adds session to queue
2. **Queue processor** (`async_consolidation.py`) picks it up within 30s
3. **Consolidator** (`session_consolidator.py`) extracts memories via regex + LLM
4. **Storage** (`memory_ts_client.py`) writes YAML files
5. **Embeddings** (`embedding_manager.py`) generates vectors for semantic search
6. **Clustering** (`intelligence/clustering.py`) groups memories by topic (runs periodically)
7. **Orchestrator** (`intelligence_orchestrator.py`) generates daily briefing

**When you search:**

1. **Dashboard** sends query to Flask API
2. **Hybrid search** (`hybrid_search.py`) runs semantic + BM25
3. Results returned, sorted by combined score

**Key architectural decisions:**

- **YAML files = source of truth** - Everything else is derived/cached
- **Async processing** - Don't block session end
- **Hybrid search** - Combine semantic understanding + keyword precision
- **Regex first, LLM second** - Fast pattern detection before expensive API calls
- **Garbage filtering** - Prevent self-referential noise
- **Deduplication** - Normalize + semantic similarity checks

**Files to start reading:**

1. `hooks/session-memory-consolidation-async.py` - Entry point
2. `src/session_consolidator.py` - Core extraction logic
3. `src/memory_ts_client.py` - Storage interface
4. `src/hybrid_search.py` - Search algorithm
5. `src/intelligence_orchestrator.py` - Daily briefing synthesis

---

*Generated: 2026-02-25*
*Codebase version: 0.19.1*
*See CRUSADE-AUDIT-REPORT.md for code quality assessment*
