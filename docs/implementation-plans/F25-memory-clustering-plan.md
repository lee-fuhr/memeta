# F25: Memory Clustering - Implementation Plan

**Status:** Planning Complete
**Estimated Time:** 8 hours
**Test Count:** 15 tests planned

---

## Problem Statement

Users have difficulty seeing themes and patterns across many memories. Without clustering, memories exist in isolation, making it hard to:
- Identify recurring topics or themes
- See which memories are related by subject matter
- Get a high-level view of what's been captured
- Surface relevant groups of memories for review

---

## Goals

1. Auto-cluster memories by semantic similarity
2. Use DBSCAN algorithm (density-based clustering)
3. Update clusters incrementally as new memories arrive
4. Provide cluster cohesion metrics (how tight the cluster is)
5. Support project-scoped and global clustering
6. Store clusters in intelligence.db

---

## Database Schema

```sql
CREATE TABLE memory_clusters (
    id TEXT PRIMARY KEY,                  -- UUID
    name TEXT NOT NULL,                   -- Human-readable cluster name
    description TEXT,                     -- What this cluster is about
    memory_ids TEXT NOT NULL,             -- JSON array of memory IDs
    centroid_embedding BLOB,              -- Average embedding for cluster
    cohesion_score REAL,                  -- 0.0-1.0, how tight the cluster
    member_count INTEGER NOT NULL,        -- Number of memories in cluster
    project_id TEXT,                      -- Optional project scope
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_cluster_project ON memory_clusters(project_id);
CREATE INDEX idx_cluster_cohesion ON memory_clusters(cohesion_score DESC);
CREATE INDEX idx_cluster_size ON memory_clusters(member_count DESC);
```

---

## API Design

### Core Methods

```python
class MemoryClusterer:
    """
    DBSCAN-based clustering of memories by semantic similarity.

    Key parameters:
    - min_cluster_size: Minimum 3 memories per cluster (DBSCAN min_samples)
    - similarity_threshold: 0.7 (distance threshold 0.3)
    - max_cluster_size: 50 memories (prevent mega-clusters)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize clusterer with intelligence.db"""

    def cluster_memories(
        self,
        project_id: Optional[str] = None,
        min_size: int = 3,
        similarity_threshold: float = 0.7
    ) -> List[Cluster]:
        """
        Cluster all memories (or project-scoped memories).

        Algorithm:
        1. Fetch all memory embeddings from memory-ts
        2. Compute pairwise similarity matrix
        3. Run DBSCAN (sklearn) with eps=0.3, min_samples=3
        4. Generate cluster names via LLM (sample of 5 memories)
        5. Calculate cohesion scores
        6. Store in intelligence.db

        Returns: List of created clusters
        """

    def get_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """Retrieve cluster by ID with full details"""

    def get_all_clusters(
        self,
        project_id: Optional[str] = None,
        min_cohesion: Optional[float] = None
    ) -> List[Cluster]:
        """Get all clusters, optionally filtered by project/cohesion"""

    def add_to_cluster(self, cluster_id: str, memory_id: str) -> bool:
        """
        Manually add memory to existing cluster.
        Recalculates centroid and cohesion.
        """

    def remove_from_cluster(self, cluster_id: str, memory_id: str) -> bool:
        """
        Remove memory from cluster.
        If cluster drops below min_size, delete cluster.
        """

    def update_cluster(
        self,
        cluster_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """Update cluster metadata"""

    def delete_cluster(self, cluster_id: str) -> bool:
        """Delete cluster (memories remain in memory-ts)"""

    def get_memory_clusters(self, memory_id: str) -> List[Cluster]:
        """Find all clusters containing a specific memory"""

    def incremental_cluster(
        self,
        new_memory_ids: List[str],
        project_id: Optional[str] = None
    ) -> List[Cluster]:
        """
        Incrementally add new memories to existing clusters.

        Algorithm:
        1. For each new memory, compute similarity to existing cluster centroids
        2. If similarity > threshold, add to most similar cluster
        3. If no match, check if new memories form their own cluster
        4. Update affected cluster centroids and cohesion

        Returns: List of created/updated clusters
        """

    def recalculate_all_clusters(self, project_id: Optional[str] = None):
        """
        Rebuild all clusters from scratch.
        Useful when similarity threshold or min_size changes.
        """

    def get_cluster_statistics(self) -> dict:
        """
        Return clustering statistics:
        - Total clusters
        - Average cluster size
        - Average cohesion score
        - Largest cluster
        - Most cohesive cluster
        - Unclustered memories (noise)
        """
```

### Data Structures

```python
@dataclass
class Cluster:
    """A cluster of related memories"""
    id: str
    name: str
    description: Optional[str]
    memory_ids: List[str]
    centroid_embedding: Optional[bytes]
    cohesion_score: float
    member_count: int
    project_id: Optional[str]
    created_at: datetime
    updated_at: datetime
```

---

## DBSCAN Algorithm Details

**Why DBSCAN?**
- Handles arbitrary cluster shapes (not just spherical like K-means)
- Auto-determines number of clusters (no need to specify K)
- Labels outliers as "noise" (unclustered memories)
- Works well with semantic similarity metrics

**Parameters:**
- `eps=0.3`: Distance threshold (1.0 - 0.7 similarity = 0.3 distance)
- `min_samples=3`: Minimum cluster size
- `metric='precomputed'`: We provide similarity matrix, not raw vectors

**Distance Metric:**
Cosine distance = 1 - cosine_similarity(embedding_a, embedding_b)

**Cluster Naming:**
Sample 5 memories from cluster → LLM generates name based on content

**Cohesion Score:**
Average pairwise similarity within cluster (higher = tighter cluster)

---

## Integration Points

### Dependencies
- **memory-ts**: Source of embeddings (via get_memory_embeddings())
- **IntelligenceDB**: Stores cluster data
- **LLM (Sonnet 4.5)**: Generates cluster names

### Consumers
- **F26 (Memory Summarization)**: Summarizes clusters
- **Search UI**: Filter by cluster
- **Memory Browser**: Show cluster memberships

---

## Test Plan

### Initialization Tests (2 tests)
1. `test_clusterer_initialization` - Database schema created
2. `test_clusterer_with_custom_db` - Custom db_path works

### Basic Clustering Tests (5 tests)
3. `test_cluster_similar_memories` - 6 memories, 2 clear clusters
4. `test_minimum_cluster_size` - Below min_size → no cluster
5. `test_similarity_threshold` - Dissimilar memories → separate clusters
6. `test_noise_detection` - Outliers not clustered
7. `test_project_scoped_clustering` - Only cluster within project

### Cluster Operations Tests (4 tests)
8. `test_get_cluster` - Retrieve by ID
9. `test_get_all_clusters` - Filter by project/cohesion
10. `test_add_to_cluster` - Manual addition, centroid recalc
11. `test_remove_from_cluster` - Removal, cluster deletion if too small

### Incremental Clustering Tests (2 tests)
12. `test_incremental_add` - New memories join existing clusters
13. `test_incremental_new_cluster` - New memories form new cluster

### Statistics Tests (2 tests)
14. `test_cluster_statistics` - Counts, averages, extremes
15. `test_get_memory_clusters` - Find clusters for specific memory

---

## Edge Cases & Error Handling

1. **Empty database** → Return empty list, no error
2. **Single memory** → Cannot cluster (min_size=3)
3. **No embeddings** → Skip memories without embeddings
4. **Duplicate cluster names** → Append (1), (2), etc.
5. **Memory deleted from memory-ts** → Silently skip in cluster
6. **LLM timeout during naming** → Use generic name "Cluster N"
7. **Invalid cluster_id** → Return None
8. **Add memory already in cluster** → No-op, return True
9. **Cluster drops below min_size** → Auto-delete cluster

---

## Performance Considerations

**At 10K memories:**
- Pairwise similarity matrix: 10K × 10K = 100M comparisons (~10GB RAM)
- **Solution:** Batch processing (1K memories at a time)
- DBSCAN complexity: O(n²) with precomputed distances
- **Mitigation:** Only cluster within projects (typically <1K memories)

**Incremental updates:**
- Only compute new memory → centroid similarities (~10 comparisons)
- Update centroids for affected clusters only

**Caching:**
- Store centroids as embeddings (avoid recomputing average)
- Cohesion score cached, only recalc on membership change

---

## Success Criteria

1. ✅ Clusters semantically similar memories together
2. ✅ Cohesion scores accurately reflect cluster tightness
3. ✅ Incremental updates work without full reclustering
4. ✅ Project-scoped clustering isolates different contexts
5. ✅ LLM-generated names are descriptive
6. ✅ All 15 tests passing
7. ✅ No performance degradation up to 1K memories per cluster run

---

## Future Enhancements

- **Hierarchical clustering:** Sub-clusters within large clusters
- **Temporal clustering:** Cluster by time periods + similarity
- **Interactive refinement:** User feedback to merge/split clusters
- **Cluster visualization:** Force-directed graph of clusters
- **Cluster alerts:** Notify when new cluster emerges
- **Cross-project clusters:** Find themes across multiple projects

---

## Implementation Checklist

- [ ] Create `src/intelligence/clustering.py`
- [ ] Add schema to IntelligenceDB (memory_clusters table)
- [ ] Implement MemoryClusterer class
- [ ] Add DBSCAN clustering logic
- [ ] Implement LLM-based cluster naming
- [ ] Add cohesion score calculation
- [ ] Implement incremental clustering
- [ ] Create `tests/intelligence/test_clustering.py`
- [ ] Write all 15 tests
- [ ] Run and verify tests passing
- [ ] Update CHANGELOG.md
- [ ] Update SHOWCASE.md
- [ ] Update PLAN.md
- [ ] Commit changes
