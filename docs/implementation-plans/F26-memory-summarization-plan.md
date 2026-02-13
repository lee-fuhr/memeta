# F26: Memory Summarization - Implementation Plan

**Status:** Planning Complete
**Estimated Time:** 6 hours
**Test Count:** 12 tests planned

---

## Problem Statement

Users have too many memories to review individually. Without summarization:
- Hard to get overview of what's been captured
- Can't quickly understand cluster themes
- Difficult to review time periods (weekly/monthly)
- Project retrospectives require manual review

---

## Goals

1. Generate summaries of memory clusters (what's this cluster about?)
2. Generate project summaries (what happened this month?)
3. Generate period summaries (weekly/monthly digests)
4. Store summaries with metadata (type, target, date range)
5. LLM-powered synthesis of memory contents

---

## Database Schema

Already added to IntelligenceDB:

```sql
CREATE TABLE memory_summaries (
    id TEXT PRIMARY KEY,
    summary_type TEXT NOT NULL,  -- cluster, project, period
    target_id TEXT,               -- cluster_id or project_id
    period_start INTEGER,
    period_end INTEGER,
    summary TEXT NOT NULL,
    memory_count INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_summary_type ON memory_summaries(summary_type);
CREATE INDEX idx_summary_target ON memory_summaries(target_id);
CREATE INDEX idx_summary_period ON memory_summaries(period_start, period_end);
```

---

## API Design

### Core Methods

```python
class MemorySummarizer:
    """
    LLM-powered summarization of memories.

    Generates three types of summaries:
    - Cluster summaries: What's this group of related memories about?
    - Project summaries: What happened in this project over time period?
    - Period summaries: What was captured this week/month?
    """

    def __init__(self, db_path: Optional[Path] = None, memory_client: Optional[MemoryTSClient] = None):
        """Initialize summarizer with intelligence.db"""

    def summarize_cluster(self, cluster_id: str) -> Summary:
        """
        Generate summary of a memory cluster.

        Algorithm:
        1. Get all memories in cluster (from clustering.py)
        2. Sample up to 20 memories (or all if < 20)
        3. LLM synthesizes: theme, key points, patterns
        4. Store summary with cluster_id reference

        Returns: Summary object
        """

    def summarize_project(
        self,
        project_id: str,
        days: int = 30,
        min_memories: int = 5
    ) -> Optional[Summary]:
        """
        Generate summary of project activity over time period.

        Algorithm:
        1. Get all memories for project in date range
        2. Group by week if >50 memories (hierarchical summary)
        3. LLM synthesizes: progress, decisions, blockers, insights
        4. Store summary with project_id + date range

        Returns: Summary or None if insufficient memories
        """

    def summarize_period(
        self,
        start: datetime,
        end: datetime,
        project_id: Optional[str] = None
    ) -> Optional[Summary]:
        """
        Generate summary of memories captured in time period.

        Algorithm:
        1. Get all memories in date range (optionally filtered by project)
        2. Group by theme/cluster if available
        3. LLM synthesizes: highlights, patterns, insights
        4. Store summary with date range

        Returns: Summary or None if no memories
        """

    def get_summary(self, summary_id: str) -> Optional[Summary]:
        """Retrieve summary by ID"""

    def get_summaries(
        self,
        summary_type: Optional[str] = None,
        target_id: Optional[str] = None,
        after: Optional[datetime] = None
    ) -> List[Summary]:
        """
        Get summaries filtered by type, target, or date.

        Args:
            summary_type: Filter by cluster/project/period
            target_id: Filter by cluster_id or project_id
            after: Only summaries created after this date

        Returns: List of matching summaries
        """

    def delete_summary(self, summary_id: str) -> bool:
        """Delete a summary (memories remain unchanged)"""

    def regenerate_summary(self, summary_id: str) -> Summary:
        """
        Regenerate an existing summary.
        Useful when memories have been added since last summary.
        """

    def get_summary_statistics(self) -> dict:
        """
        Return summary statistics:
        - Total summaries by type
        - Average memory count per summary
        - Most summarized cluster/project
        """
```

### Data Structures

```python
@dataclass
class Summary:
    """A generated summary of memories"""
    id: str
    summary_type: str  # cluster, project, period
    target_id: Optional[str]  # cluster_id or project_id
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    summary: str  # The actual summary text
    memory_count: int
    created_at: datetime
```

---

## LLM Prompts

### Cluster Summary Prompt

```
Analyze these related memories and generate a summary that captures:
1. The overarching theme (what connects these memories?)
2. Key insights or patterns
3. Notable details or decisions

Memories:
- [memory 1 content]
- [memory 2 content]
...

Generate a 2-3 paragraph summary. Be concise but insightful.
```

### Project Summary Prompt

```
Summarize progress on project "[project_name]" over [date_range]:

Memories captured:
- [memory 1 content with date]
- [memory 2 content with date]
...

Generate a summary covering:
1. What was accomplished
2. Key decisions made
3. Open questions or blockers
4. Insights or learnings

Format: 3-4 paragraphs, chronological flow where relevant.
```

### Period Summary Prompt

```
Generate a digest of memories captured from [start] to [end]:

Memories:
- [memory 1 content]
- [memory 2 content]
...

Organize the summary by themes/topics. Include:
1. Highlights (most important captures)
2. Patterns or trends
3. Notable insights

Format: 3-5 bullet points per theme, conversational tone.
```

---

## Integration Points

### Dependencies
- **IntelligenceDB**: Stores summaries
- **MemoryTSClient**: Retrieves memories to summarize
- **clustering.py**: Gets cluster memberships for cluster summaries
- **LLM (Sonnet 4.5)**: Generates summary text

### Consumers
- **Memory Browser UI**: Display summaries alongside clusters
- **Project Dashboard**: Show project activity summary
- **Weekly Review**: Auto-generate weekly digests
- **Session Consolidation**: Summarize session memories

---

## Test Plan

### Initialization Tests (2 tests)
1. `test_summarizer_initialization` - Database schema exists
2. `test_summarizer_with_custom_db` - Custom db_path works

### Cluster Summary Tests (3 tests)
3. `test_summarize_cluster` - Basic cluster summary generation
4. `test_summarize_cluster_not_found` - Invalid cluster_id → None
5. `test_summarize_large_cluster` - Sampling logic for >20 memories

### Project Summary Tests (3 tests)
6. `test_summarize_project` - Project summary for 30-day period
7. `test_summarize_project_insufficient_memories` - <5 memories → None
8. `test_summarize_project_hierarchical` - >50 memories uses weekly grouping

### Period Summary Tests (2 tests)
9. `test_summarize_period` - Basic period summary
10. `test_summarize_period_no_memories` - Empty date range → None

### Summary Operations Tests (2 tests)
11. `test_get_summaries_filtered` - Filter by type, target, date
12. `test_regenerate_summary` - Re-summarize with updated memories

---

## Edge Cases & Error Handling

1. **Empty cluster** → Return "No memories in cluster" summary
2. **LLM timeout** → Return "Summary unavailable (timeout)" with memory count
3. **Invalid cluster_id** → Return None
4. **Invalid date range** → Swap start/end if reversed
5. **No memories in period** → Return None
6. **Very long memories** → Truncate to first 500 chars each before LLM
7. **Memory deleted** → Skip deleted memories in regeneration
8. **Duplicate summary request** → Return existing summary if <24h old

---

## Performance Considerations

**At 10K memories:**
- Cluster summaries: 10-20 LLM calls (one per cluster)
- Project summaries: 1 LLM call per project per month
- Period summaries: 1 LLM call per week/month

**Cost estimate:**
- Cluster summary: ~1K input tokens + 300 output tokens = $0.0035
- 100 summaries/day = $0.35/day

**Caching:**
- Don't regenerate summaries <24h old unless explicitly requested
- Cache summaries by hash of memory IDs (detect if memories changed)

**Sampling:**
- >20 memories → sample random 20 for summary
- >50 memories → use hierarchical summarization (weekly batches)

---

## Success Criteria

1. ✅ Cluster summaries capture theme accurately
2. ✅ Project summaries show chronological progress
3. ✅ Period summaries group by themes/topics
4. ✅ All 12 tests passing
5. ✅ Summaries generated in <30 seconds each
6. ✅ LLM costs <$0.01 per summary

---

## Future Enhancements

- **Incremental summarization:** Update summary when new memories added to cluster
- **Multi-level summaries:** Summary of summaries for large date ranges
- **Summary chaining:** Week summaries → month summary → quarter summary
- **Interactive refinement:** User feedback to improve summary quality
- **Summary versioning:** Track changes to summaries over time
- **Cross-project summaries:** "What happened across all projects this month?"
- **Summary search:** Full-text search across summary text

---

## Implementation Checklist

- [ ] Create `src/intelligence/summarization.py`
- [ ] Schema already added to IntelligenceDB ✓
- [ ] Implement MemorySummarizer class
- [ ] Add cluster summarization logic
- [ ] Add project summarization logic
- [ ] Add period summarization logic
- [ ] Implement LLM prompts and synthesis
- [ ] Create `tests/intelligence/test_summarization.py`
- [ ] Write all 12 tests
- [ ] Run and verify tests passing
- [ ] Update CHANGELOG.md
- [ ] Update SHOWCASE.md
- [ ] Update PLAN.md
- [ ] Commit changes
