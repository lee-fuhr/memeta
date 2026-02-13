# F28: Memory Search Optimization - Implementation Plan

**Status:** Planning
**Priority:** Tier 1 (High - performance critical at scale)
**Estimated effort:** 10 hours (4h code, 3h tests, 3h benchmarking)

---

## Goals

**Primary:**
- Cache frequently-searched terms
- Pre-compute popular query embeddings
- Rank results by relevance + recency + importance
- Learn from user selections (click-through)

**Secondary:**
- A/B test ranking algorithms
- Query analytics
- Search autocomplete

---

## Database Schema

```sql
CREATE TABLE search_cache (
    query_hash TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    results TEXT NOT NULL,  -- JSON array of memory IDs
    hits INTEGER DEFAULT 0,
    last_hit INTEGER,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE INDEX idx_cache_hits ON search_cache(hits DESC);
CREATE INDEX idx_cache_expires ON search_cache(expires_at);

CREATE TABLE search_analytics (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    result_count INTEGER,
    selected_memory_id TEXT,  -- Which result user chose
    position INTEGER,          -- Position in results (1-based)
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_analytics_query ON search_analytics(query);
CREATE INDEX idx_analytics_created ON search_analytics(created_at DESC);

CREATE TABLE query_embeddings (
    query_hash TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    embedding BLOB NOT NULL,  -- 384-dim float32 array
    hits INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_qembed_hits ON query_embeddings(hits DESC);
```

---

## Caching Strategy

### When to cache:

**Cache if:**
- Query repeated ≥2 times
- Results stable (no new memories matching)
- TTL: 24 hours

**Don't cache if:**
- First-time query
- Results change frequently (real-time context)
- User-specific filters (project_id)

### Cache invalidation:

**Invalidate on:**
- New memory created matching cached query
- Memory updated that was in cached results
- TTL expires (24h)

**Implementation:**
```python
def search_with_cache(query: str, use_cache: bool = True) -> List[Memory]:
    if not use_cache:
        return self._search_no_cache(query)

    # Check cache
    query_hash = hashlib.md5(query.encode()).hexdigest()

    cached = self._get_cached_results(query_hash)
    if cached and cached['expires_at'] > time.time():
        # Hit! Update stats and return
        self._record_cache_hit(query_hash)
        return self._load_memories(cached['results'])

    # Miss - search and cache
    results = self._search_no_cache(query)

    # Cache if worthwhile (>3 results, not too many)
    if 3 <= len(results) <= 100:
        self._cache_results(query_hash, query, results)

    return results
```

---

## Ranking Algorithm

### Current ranking (baseline):

```
score = semantic_similarity * 0.7 + keyword_match * 0.3
```

**Problems:**
- No recency component (old memories rank high)
- No importance weighting
- No personalization (all users see same ranking)

### Improved ranking (v2):

```
score = semantic_sim * 0.4
      + keyword_match * 0.2
      + recency_score * 0.2
      + importance * 0.1
      + click_through_rate * 0.1

Where:
- semantic_sim: cosine similarity (0-1)
- keyword_match: BM25 score normalized (0-1)
- recency_score: 1.0 - (days_old / 365)  # Linear decay over 1 year
- importance: memory.importance (0-1)
- click_through_rate: % of times clicked when shown for this query (0-1)
```

**Why these weights:**
- Semantic (0.4): Most important - what the query is about
- Keyword (0.2): Exact matches matter
- Recency (0.2): Recent context more relevant
- Importance (0.1): High-quality memories surface
- CTR (0.1): Learn from user behavior

### Personalization:

**Future:** Per-user/per-project ranking weights
```python
# User A: Prioritizes recency (0.4) over semantic (0.3)
# User B: Prioritizes semantic (0.5) over recency (0.1)

weights = get_user_weights(user_id)  # Load from profile
score = calculate_weighted_score(weights, features)
```

---

## Click-Through Learning

### Track what users click:

```python
def record_selection(
    query: str,
    memory_id: str,
    position: int,
    result_count: int
):
    """
    Record that user selected memory_id at position in results.

    Args:
        query: Search query
        memory_id: Which memory user clicked
        position: 1-based position in results (1=top)
        result_count: Total results shown
    """
    analytics_id = f"{int(time.time())}-{hashlib.md5(query.encode()).hexdigest()[:8]}"

    with get_connection(self.db_path) as conn:
        conn.execute("""
            INSERT INTO search_analytics
            (id, query, result_count, selected_memory_id, position, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            analytics_id,
            query,
            result_count,
            memory_id,
            position,
            int(time.time())
        ))
        conn.commit()
```

### Learn from selections:

```python
def calculate_ctr(query: str, memory_id: str) -> float:
    """
    Click-through rate for this memory on this query.

    CTR = clicks / impressions

    Where:
    - clicks: Times user selected this memory for this query
    - impressions: Times this memory appeared in results for this query
    """
    with get_connection(self.db_path) as conn:
        # Count clicks
        clicks = conn.execute("""
            SELECT COUNT(*)
            FROM search_analytics
            WHERE query = ? AND selected_memory_id = ?
        """, (query, memory_id)).fetchone()[0]

        # Count impressions (approximate: times query run and memory in top 10)
        # For now, use clicks as proxy (refinement later)
        impressions = max(clicks, 1)

        return clicks / impressions
```

---

## Query Embedding Pre-computation

### Why pre-compute:

**Problem:** Embedding generation is slow (~50ms per query)

**Solution:** Cache embeddings for popular queries

### When to pre-compute:

**Criteria:**
- Query repeated ≥3 times
- Not already cached
- High click-through (user finds it useful)

### Implementation:

```python
def get_query_embedding(query: str, cache: bool = True) -> np.ndarray:
    """
    Get embedding for query.

    Args:
        query: Search query
        cache: If True, check cache first

    Returns:
        384-dim embedding vector
    """
    if not cache:
        return self._compute_embedding(query)

    query_hash = hashlib.md5(query.encode()).hexdigest()

    # Check cache
    with get_connection(self.db_path) as conn:
        row = conn.execute("""
            SELECT embedding
            FROM query_embeddings
            WHERE query_hash = ?
        """, (query_hash,)).fetchone()

        if row:
            # Cache hit!
            self._record_embedding_hit(query_hash)
            return np.frombuffer(row[0], dtype=np.float32)

    # Cache miss - compute and cache
    embedding = self._compute_embedding(query)

    # Cache if query is popular (≥3 hits)
    query_count = self._get_query_count(query)
    if query_count >= 3:
        self._cache_embedding(query_hash, query, embedding)

    return embedding
```

---

## Integration Points

### With MemoryTSClient (src/memory_ts_client.py)

**Problem:** Current search doesn't use caching or ranking.

**Solution:**
```python
# In MemoryTSClient.search()
from intelligence.search_optimizer import SearchOptimizer

def search(self, content: str = None, **kwargs) -> List[Memory]:
    # Existing search logic
    results = self._hybrid_search(content, **kwargs)

    # NEW: Use search optimizer for ranking
    if content:
        optimizer = SearchOptimizer()
        results = optimizer.rank_results(
            query=content,
            results=results,
            use_ctr=True
        )

    return results
```

### With Dashboard (src/dashboard_export.py)

**Problem:** No search analytics visible.

**Solution:** Add search analytics section to dashboard

```python
def export_dashboard():
    # ... existing sections ...

    # NEW: Search analytics
    optimizer = SearchOptimizer()
    analytics = optimizer.get_search_analytics(days=7)

    html += f"""
    <section>
        <h2>Search Analytics (Last 7 Days)</h2>
        <ul>
            <li>Total searches: {analytics['total_searches']}</li>
            <li>Avg results per search: {analytics['avg_results']:.1f}</li>
            <li>Cache hit rate: {analytics['cache_hit_rate']:.1%}</li>
            <li>Top queries: {', '.join(analytics['top_queries'][:5])}</li>
        </ul>
    </section>
    """
```

---

## Test Strategy

### Unit Tests (tests/intelligence/test_search_optimizer.py)

**Test coverage:** 15 tests

1. **Caching**
   - `test_cache_miss_first_search`: First search not cached
   - `test_cache_hit_second_search`: Second search uses cache
   - `test_cache_expiry`: Expired cache not used
   - `test_cache_invalidation_on_new_memory`: New memory invalidates cache

2. **Ranking**
   - `test_ranking_baseline`: Semantic + keyword baseline
   - `test_ranking_with_recency`: Recent memories ranked higher
   - `test_ranking_with_importance`: Important memories surface
   - `test_ranking_with_ctr`: High-CTR memories rank higher

3. **Click-Through**
   - `test_record_selection`: Selection recorded
   - `test_calculate_ctr`: CTR calculated correctly
   - `test_ctr_affects_ranking`: CTR influences rank

4. **Query Embeddings**
   - `test_embedding_cache_miss`: First query computes embedding
   - `test_embedding_cache_hit`: Popular query uses cached embedding
   - `test_embedding_cache_popular_only`: Only popular queries cached

5. **Analytics**
   - `test_get_search_analytics`: Analytics aggregation
   - `test_top_queries`: Most frequent queries identified

### Integration Tests (tests/integration/test_search_integration.py)

**Test coverage:** 5 tests

1. `test_memory_client_uses_optimizer`: MemoryTSClient integration
2. `test_dashboard_shows_analytics`: Dashboard integration
3. `test_end_to_end_search_workflow`: Search → select → learn → rank
4. `test_cache_performance`: Cache provides speedup
5. `test_ranking_improves_relevance`: Better ranking = better results

---

## Performance Benchmarks

### Target metrics:

**Without optimization:**
- Search latency: 200-500ms
- Embedding computation: ~50ms per query
- No caching

**With optimization:**
- Search latency: <100ms (cache hit)
- Search latency: <200ms (cache miss)
- Embedding computation: <5ms (cached)
- Cache hit rate: >60% for popular queries

### Benchmark tests:

```python
def test_search_performance():
    """Benchmark search performance with/without optimization"""
    optimizer = SearchOptimizer()

    # Cold search (no cache)
    start = time.time()
    results = optimizer.search("my query", use_cache=False)
    cold_time = time.time() - start

    # Warm search (with cache)
    start = time.time()
    results = optimizer.search("my query", use_cache=True)
    warm_time = time.time() - start

    assert cold_time > warm_time * 2  # Cache should be ≥2x faster
    assert warm_time < 0.1  # Cache hit <100ms
```

---

## Edge Cases

1. **Cache stampede:** Many queries for uncached term
   - Use lock to prevent duplicate computations
   - First query computes, others wait

2. **Stale cache:** Results change but cache not invalidated
   - TTL (24h) handles this
   - Manual invalidation on memory create/update

3. **Query variations:** "my home office" vs "home office setup"
   - Treat as separate queries (no fuzzy matching yet)
   - Click-through learning handles this organically

4. **Zero results:** Query returns nothing
   - Don't cache (no value)
   - Analytics tracks for query expansion (future)

---

## Future Enhancements

1. **Query expansion:** "office" → also search "workspace", "desk"
2. **Typo correction:** "hom office" → "home office"
3. **Semantic caching:** Cache similar queries together
4. **Personalized ranking:** Per-user weight tuning
5. **A/B testing framework:** Test ranking algorithms
6. **Search suggestions:** Autocomplete based on popular queries

---

## Success Criteria

**Minimum viable:**
- ✅ Cache frequently-searched queries
- ✅ Rank results by relevance + recency + importance
- ✅ Track click-through for learning
- ✅ 15+ unit tests passing
- ✅ <100ms search latency (cached)
- ✅ >60% cache hit rate

**Nice to have:**
- Integration with MemoryTSClient
- Dashboard analytics section
- Benchmark tests showing improvement

---

## Implementation Checklist

- [ ] Define schema
- [ ] Design API
- [ ] Implement SearchOptimizer class
- [ ] Implement caching logic
- [ ] Implement improved ranking
- [ ] Implement click-through tracking
- [ ] Write unit tests (15)
- [ ] Write integration tests (5)
- [ ] Write benchmark tests
- [ ] Integrate with MemoryTSClient
- [ ] Document API
- [ ] Update CHANGELOG.md
- [ ] Commit with tests passing
