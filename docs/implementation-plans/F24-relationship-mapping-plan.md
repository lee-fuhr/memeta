# F24: Memory Relationship Mapping - Implementation Plan

**Status:** Planning
**Priority:** Tier 1 (High - enables many other features)
**Estimated effort:** 8 hours (3h code, 3h tests, 2h integration)

---

## Goals

**Primary:**
- Build explicit relationship graph between memories
- Enable causal chain discovery (A→B→C)
- Detect contradictions automatically
- Support dependency tracking

**Secondary:**
- Visualize memory relationships (future)
- Graph-based search (future)
- Relationship-aware clustering (future)

---

## Database Schema

```sql
CREATE TABLE memory_relationships (
    id TEXT PRIMARY KEY,
    from_memory_id TEXT NOT NULL,
    to_memory_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('causal', 'contradicts', 'supports', 'requires', 'related')),
    strength REAL DEFAULT 0.5 CHECK(strength >= 0.0 AND strength <= 1.0),
    evidence TEXT,
    created_at INTEGER NOT NULL,
    created_by TEXT,  -- user, system, agent_name
    UNIQUE(from_memory_id, to_memory_id, relationship_type)
);

CREATE INDEX idx_rel_from ON memory_relationships(from_memory_id);
CREATE INDEX idx_rel_to ON memory_relationships(to_memory_id);
CREATE INDEX idx_rel_type ON memory_relationships(relationship_type);
CREATE INDEX idx_rel_strength ON memory_relationships(strength DESC);
```

**Why these indices:**
- `idx_rel_from`: Fast lookup of outgoing relationships
- `idx_rel_to`: Fast lookup of incoming relationships
- `idx_rel_type`: Filter by relationship type
- `idx_rel_strength`: Sort by confidence

---

## API Design

### Core Operations

```python
class RelationshipMapper:
    def link_memories(
        from_id: str,
        to_id: str,
        type: str,
        evidence: str,
        strength: float = 0.5,
        created_by: str = "system"
    ) -> str
    """
    Create relationship. Returns relationship ID.
    Raises ValueError if type invalid or IDs don't exist.
    """

    def get_related_memories(
        memory_id: str,
        type: Optional[str] = None,
        direction: str = "both",  # from, to, both
        min_strength: float = 0.0
    ) -> List[Tuple[str, MemoryRelationship]]
    """
    Find related memories.
    Returns [(related_memory_id, relationship), ...]
    """

    def find_causal_chain(
        start_id: str,
        end_id: str,
        max_depth: int = 5
    ) -> Optional[List[str]]
    """
    Find shortest causal path using BFS.
    Returns [id1, id2, id3] or None if no path.
    """

    def detect_contradictions(
        memory_id: str
    ) -> List[Tuple[str, MemoryRelationship]]
    """
    Find memories that contradict this one.
    Shortcut for get_related_memories(type="contradicts")
    """

    def remove_relationship(rel_id: str) -> bool
    """Remove relationship. Returns True if existed."""

    def update_strength(rel_id: str, new_strength: float)
    """Update relationship confidence."""
```

### Statistics & Analytics

```python
def get_relationship_stats() -> dict
"""
Returns:
{
    'total_relationships': 1234,
    'by_type': {'causal': 500, 'contradicts': 50, ...},
    'average_strength': 0.73,
    'most_connected_memories': [(memory_id, count), ...]
}
"""

def get_memory_graph_stats(memory_id: str) -> dict
"""
Returns:
{
    'outgoing_count': 5,
    'incoming_count': 3,
    'contradiction_count': 1,
    'centrality_score': 0.8  # How connected is this memory?
}
"""
```

---

## Integration Points

### With Contradiction Detector (src/contradiction_detector.py)

**Problem:** Current contradiction detector marks memories as contradicted but doesn't create relationship.

**Solution:**
```python
# In contradiction_detector.py
from intelligence.relationship_mapper import RelationshipMapper

def check_contradictions(new_content: str, existing_memories: List[dict]) -> ContradictionResult:
    # ... existing logic ...

    if contradiction.action == "replace":
        # NEW: Create relationship
        mapper = RelationshipMapper()
        mapper.link_memories(
            from_id=contradiction.contradicted_memory['id'],
            to_id=new_memory_id,  # Will be created
            type="contradicts",
            evidence=f"Confidence: {contradiction.confidence:.2f}. Old: {contradiction.contradicted_memory['content'][:100]}"
            strength=contradiction.confidence
        )

    return contradiction
```

### With Pattern Detector (src/pattern_detector.py)

**Problem:** Pattern reinforcement doesn't track what led to what.

**Solution:**
```python
# In pattern_detector.py
def record_reinforcement(memory_id: str, grade: str, context: str = None):
    # ... existing FSRS logic ...

    # NEW: If grade is GOOD/EASY and context provided, create causal link
    if grade in ["GOOD", "EASY"] and context:
        mapper = RelationshipMapper()
        # Context could be another memory ID that triggered recall
        if is_valid_memory_id(context):
            mapper.link_memories(
                from_id=context,
                to_id=memory_id,
                type="related",
                evidence=f"Reinforced together (grade: {grade})",
                strength=0.6 if grade == "GOOD" else 0.8
            )
```

### With Session Consolidator (src/session_consolidator.py)

**Problem:** Session consolidation extracts memories but doesn't link them.

**Solution:**
```python
# In consolidate_session()
def consolidate_session(session_file: Path) -> ConsolidationResult:
    # ... extract memories ...

    # NEW: Link memories from same session
    mapper = RelationshipMapper()

    # Link corrections → what they correct
    corrections = [m for m in extracted_memories if 'correction' in m.tags]
    for correction in corrections:
        # Find what it corrects (heuristic: similar content in older memories)
        candidates = memory_client.search(content=correction.content[:50])
        if candidates:
            oldest = min(candidates, key=lambda m: m.created)
            mapper.link_memories(
                from_id=oldest.id,
                to_id=correction.id,
                type="contradicts",
                evidence="Correction in same session",
                strength=0.7
            )

    # Link decisions → their context
    decisions = [m for m in extracted_memories if 'decision' in m.category]
    learnings = [m for m in extracted_memories if 'learning' in m.category]

    for decision in decisions:
        for learning in learnings:
            # If learning mentions decision keywords, link them
            if any(word in learning.content.lower() for word in decision.content.lower().split()[:5]):
                mapper.link_memories(
                    from_id=learning.id,
                    to_id=decision.id,
                    type="causal",
                    evidence="Learning led to decision",
                    strength=0.6
                )
```

---

## Test Strategy

### Unit Tests (tests/intelligence/test_relationship_mapper.py)

**Test coverage:** 15 tests minimum

1. **Initialization**
   - `test_mapper_initialization`: Database and schema creation
   - `test_schema_constraints`: Check UNIQUE and CHECK constraints work

2. **Link Creation**
   - `test_link_memories_basic`: Create simple relationship
   - `test_link_memories_duplicate`: UNIQUE constraint prevents duplicates
   - `test_link_memories_invalid_type`: ValueError on bad relationship_type
   - `test_link_memories_invalid_strength`: ValueError on strength <0 or >1
   - `test_link_bidirectional`: A→B and B→A can both exist

3. **Retrieval**
   - `test_get_related_from`: direction="from" only returns outgoing
   - `test_get_related_to`: direction="to" only returns incoming
   - `test_get_related_both`: direction="both" returns all
   - `test_get_related_filtered_by_type`: Filter by relationship_type
   - `test_get_related_min_strength`: Filter by strength threshold

4. **Causal Chains**
   - `test_find_causal_chain_direct`: A→B direct link
   - `test_find_causal_chain_multi_hop`: A→B→C chain
   - `test_find_causal_chain_not_found`: No path returns None
   - `test_find_causal_chain_max_depth`: Respects max_depth limit

5. **Contradictions**
   - `test_detect_contradictions`: Find contradicting memories
   - `test_detect_contradictions_bidirectional`: A contradicts B = B contradicts A

6. **Updates & Deletions**
   - `test_update_strength`: Modify relationship confidence
   - `test_remove_relationship`: Delete relationship

7. **Statistics**
   - `test_get_relationship_stats`: Total count, by type, avg strength
   - `test_get_memory_graph_stats`: Per-memory connectivity

### Integration Tests (tests/integration/test_relationship_integration.py)

**Test coverage:** 5 tests

1. `test_contradiction_creates_relationship`: contradiction_detector integration
2. `test_reinforcement_creates_relationship`: pattern_detector integration
3. `test_session_consolidation_links_memories`: session_consolidator integration
4. `test_causal_chain_across_sessions`: Multi-session causal chains
5. `test_relationship_aware_search`: Search using relationships (future)

---

## Edge Cases & Error Handling

### Edge Cases

1. **Circular references:** A→B→A
   - Allow (they're valid in memory graphs)
   - Causal chain finder handles with visited set

2. **Self-relationships:** A→A
   - Allow (e.g., "memory reinforces itself")
   - Not common but valid

3. **Orphaned relationships:** Relationship exists but memory deleted
   - Accept (don't cascade delete - relationships are historical)
   - Query returns empty if memory doesn't exist

4. **Duplicate types:** A→B exists as "causal" and "related"
   - Allow (UNIQUE constraint is on (from, to, type) triple)
   - Different relationship types can coexist

### Error Handling

```python
# Invalid memory IDs
try:
    mapper.link_memories("invalid1", "invalid2", "causal", "test")
except ValueError as e:
    # "Memory ID invalid1 not found"
    pass

# Invalid relationship type
try:
    mapper.link_memories(id1, id2, "invalid_type", "test")
except ValueError as e:
    # "Invalid relationship_type: invalid_type"
    pass

# Strength out of range
try:
    mapper.link_memories(id1, id2, "causal", "test", strength=1.5)
except ValueError as e:
    # "Strength must be 0.0-1.0, got 1.5"
    pass
```

---

## Performance Considerations

### At 10K memories:

**Worst case:** Every memory links to 10 others = 100K relationships

**Storage:** 100K rows × ~200 bytes = ~20MB (reasonable)

**Query performance:**
- `get_related_memories()`: O(1) with index, <10ms
- `find_causal_chain()`: O(n) BFS, worst case 10K nodes, ~100ms

**Optimization strategies:**
1. Limit max_depth in causal chain (default 5)
2. Cache popular queries (future)
3. Prune low-strength relationships (<0.3) after 90 days (future)

---

## Future Enhancements

**Not in initial implementation:**

1. **Relationship weights:** Track how often relationship is confirmed
2. **Temporal decay:** Relationships weaken over time
3. **Graph visualization:** D3.js graph of memory relationships
4. **Relationship-aware search:** "Find memories that led to X decision"
5. **Clustering by connectivity:** Group highly-connected memories
6. **Automatic relationship discovery:** LLM infers relationships from content

---

## Success Criteria

**Minimum viable:**
- ✅ Create relationships (5 types)
- ✅ Query relationships (3 directions)
- ✅ Find causal chains (BFS)
- ✅ Detect contradictions
- ✅ 15+ unit tests passing
- ✅ Integration with contradiction_detector

**Nice to have:**
- Integration with pattern_detector
- Integration with session_consolidator
- Relationship statistics dashboard
- Performance optimization (caching)

---

## Implementation Checklist

- [x] Define schema
- [x] Design API
- [ ] Implement RelationshipMapper class
- [ ] Write unit tests (15)
- [ ] Write integration tests (5)
- [ ] Integrate with contradiction_detector
- [ ] Document API
- [ ] Update CHANGELOG.md
- [ ] Commit with tests passing
