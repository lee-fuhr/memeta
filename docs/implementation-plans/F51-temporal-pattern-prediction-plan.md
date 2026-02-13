# F51: Temporal Pattern Prediction - Implementation Plan

**Feature:** F51: Temporal Pattern Prediction
**Estimated Complexity:** High (20+ tests)
**Dependencies:** intelligence.db, MemoryTSClient, hybrid_search, hooks system
**Created:** 2026-02-13

---

## Overview

**Problem:** Users ask for the same context at predictable times but have to manually search each time.

**Solution:** Learn temporal patterns from memory access behavior, predict needs proactively, and auto-surface relevant context when users reference past discussions.

**Key behaviors:**
1. **Passive learning:** Track when memories are accessed (time/day/context)
2. **Pattern detection:** Identify recurring temporal patterns (min 3 occurrences)
3. **Proactive prediction:** Surface predictions before user asks
4. **Topic resumption detection:** Auto-search when user says "we discussed this before"

---

## Critical Requirement: topic_resumption_detector Hook

**THE defining feature** - This is what makes the system intelligent vs. "glorified search engine".

### Hook Specification

**Hook type:** `UserPromptSubmit`
**File location:** `/Users/lee/CC/LFI/_ Operations/memory-system-v1/hooks/topic-resumption-detector.py`
**Trigger:** Every user message before Claude sees it
**Timeout:** 3000ms (consistent with other UserPromptSubmit hooks)

### Detection Patterns

Triggers on phrases indicating past discussion:
- "we discussed this before"
- "didn't we talk about this"
- "we had some back and forth"
- "previously"
- "remember when we"
- "last time we discussed"
- "we already covered"
- "as I mentioned before"
- "I think we talked about"
- "didn't I tell you"

### Algorithm

```python
def detect_topic_resumption(user_message: str) -> Optional[Dict]:
    """
    Detect if user is referencing past discussion.

    Returns:
        {
            'detected': True,
            'trigger_phrase': "we discussed this before",
            'context_keywords': ["messaging", "framework", "Connection Lab"],
            'search_query': "messaging framework Connection Lab"
        }
    """
    # 1. Check for trigger phrases (regex)
    trigger_phrases = [
        r"\bwe discussed this before\b",
        r"\bdidn't we talk about\b",
        r"\bpreviously\b",
        # ... etc
    ]

    matched_phrase = None
    for pattern in trigger_phrases:
        if re.search(pattern, user_message, re.IGNORECASE):
            matched_phrase = pattern
            break

    if not matched_phrase:
        return None

    # 2. Extract topic keywords from surrounding message
    # Use simple stopword removal + noun extraction
    words = user_message.lower().split()
    stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'we', 'this', ...}
    keywords = [w for w in words if w not in stopwords and len(w) > 3]

    # 3. Build search query
    search_query = " ".join(keywords[:5])  # Top 5 keywords

    return {
        'detected': True,
        'trigger_phrase': matched_phrase,
        'context_keywords': keywords,
        'search_query': search_query
    }
```

### Memory Search Integration

```python
def search_relevant_memories(query: str, limit: int = 5) -> List[Memory]:
    """
    Search memories using MemoryTSClient.
    """
    from memory_ts_client import MemoryTSClient

    # MemoryTSClient() takes memory_dir, not project_id
    # search() takes project_id but no limit parameter
    client = MemoryTSClient()
    results = client.search(content=query, project_id="LFI")

    # Manually slice to limit since search() doesn't have limit parameter
    return results[:limit]
```

### Output Format

```python
def format_hook_output(memories: List[Memory]) -> str:
    """
    Format memories for injection into Claude's context.
    """
    if not memories:
        return ""

    output = "\n## Relevant Context from Past Discussions\n\n"

    for i, mem in enumerate(memories, 1):
        output += f"{i}. **{mem.created[:10]}** (importance: {mem.importance:.1f})\n"
        output += f"   {mem.content}\n"
        if mem.session_id:
            output += f"   [Resume session: `claude --resume {mem.session_id}`]\n"
        output += "\n"

    return output
```

### Hook Entry Point

```python
#!/usr/bin/env python3
"""
Topic Resumption Detector Hook

Triggers when user references past discussions.
Auto-searches memories and surfaces relevant context.
"""

import sys
import json
import os

# Skip hook if disabled
if os.getenv('SKIP_HOOK_TOPIC_RESUMPTION'):
    sys.exit(0)

def main():
    # Read user message from stdin
    input_data = json.loads(sys.stdin.read())

    # Extract message text
    if 'message' in input_data:
        user_message = input_data['message']
    elif 'content' in input_data:
        content_blocks = input_data['content']
        user_message = " ".join(
            block['text'] for block in content_blocks
            if block.get('type') == 'text'
        )
    else:
        sys.exit(0)

    # Detect topic resumption
    detection = detect_topic_resumption(user_message)

    if not detection:
        sys.exit(0)  # No trigger

    # Search memories
    memories = search_relevant_memories(
        detection['search_query'],
        limit=5
    )

    if not memories:
        sys.exit(0)  # No relevant memories

    # Output context for Claude
    output = format_hook_output(memories)
    print(output)

    sys.exit(0)

if __name__ == '__main__':
    main()
```

### Settings.json Configuration

**Add to existing `~/.claude/settings.json` in the `UserPromptSubmit[0].hooks` array:**

```json
{
  "type": "command",
  "command": "/Users/lee/CC/LFI/_ Operations/memory-system-v1/hooks/topic-resumption-detector.py",
  "timeout": 3000,
  "description": "Auto-surfaces relevant memories when user references past discussions"
}
```

**Full context (don't replace entire file, just add to the hooks array):**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          // ... existing hooks ...
          {
            "type": "command",
            "command": "/Users/lee/CC/LFI/_ Operations/memory-system-v1/hooks/topic-resumption-detector.py",
            "timeout": 3000
          }
        ]
      }
    ]
  }
}
```

---

## Database Schema

### temporal_patterns Table

```sql
CREATE TABLE IF NOT EXISTS temporal_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,  -- 'daily', 'weekly', 'monthly', 'event_based'
    trigger_condition TEXT NOT NULL,  -- 'Monday 9am', 'before client meetings'
    predicted_need TEXT NOT NULL,  -- 'Connection Lab context', 'pricing framework'
    memory_ids TEXT,  -- JSON array of typically-needed memories
    confidence REAL DEFAULT 0.5,
    occurrence_count INTEGER DEFAULT 0,
    dismissed_count INTEGER DEFAULT 0,
    last_confirmed INTEGER,
    last_dismissed INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_temporal_pattern_type
    ON temporal_patterns(pattern_type);

CREATE INDEX IF NOT EXISTS idx_temporal_trigger
    ON temporal_patterns(trigger_condition);

CREATE INDEX IF NOT EXISTS idx_temporal_confidence
    ON temporal_patterns(confidence DESC);
```

**Indexes justified:**
- `pattern_type`: Filter by daily/weekly/monthly patterns
- `trigger_condition`: Lookup pattern by time/event trigger
- `confidence`: Sort predictions by confidence for prioritization

### memory_access_log Table

```sql
CREATE TABLE IF NOT EXISTS memory_access_log (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    accessed_at INTEGER NOT NULL,
    access_type TEXT NOT NULL,  -- 'search', 'direct', 'predicted', 'hook'
    day_of_week INTEGER,  -- 0=Monday, 6=Sunday (Python weekday())
    hour_of_day INTEGER,  -- 0-23
    session_id TEXT,
    context_keywords TEXT,  -- JSON array
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_access_memory
    ON memory_access_log(memory_id, accessed_at DESC);

CREATE INDEX IF NOT EXISTS idx_access_temporal
    ON memory_access_log(day_of_week, hour_of_day);

CREATE INDEX IF NOT EXISTS idx_access_session
    ON memory_access_log(session_id);
```

**Purpose:** Raw data feeding pattern detection algorithm.

---

## Class Design

### TemporalPatternPredictor

```python
class TemporalPatternPredictor:
    """
    Learns temporal patterns from memory access behavior.
    Predicts likely-needed memories based on time/context.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize predictor with database.

        Args:
            db_path: Path to intelligence.db (default: project root)
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"

        self.db_path = str(db_path)
        self._init_schema()

    def _init_schema(self):
        """Create tables if not exist."""
        # Create temporal_patterns table
        # Create memory_access_log table

    def log_memory_access(
        self,
        memory_id: str,
        access_type: str,
        context_keywords: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        Log a memory access event.

        Args:
            memory_id: Memory that was accessed
            access_type: How it was accessed (search/direct/predicted/hook)
            context_keywords: Surrounding context words
            session_id: Current session

        Returns:
            Log entry ID
        """
        now = int(datetime.now().timestamp())
        dt = datetime.now()

        log_id = hashlib.md5(f"{memory_id}-{now}".encode()).hexdigest()[:16]

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO memory_access_log
                (id, memory_id, accessed_at, access_type, day_of_week,
                 hour_of_day, session_id, context_keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id,
                memory_id,
                now,
                access_type,
                dt.weekday(),  # 0=Monday in Python
                dt.hour,
                session_id,
                json.dumps(context_keywords or []),
                now
            ))
            conn.commit()

        return log_id

    def detect_patterns(self, min_occurrences: int = 3) -> List[Dict]:
        """
        Detect recurring temporal patterns from access logs.

        Args:
            min_occurrences: Minimum occurrences to establish pattern

        Returns:
            List of detected patterns
        """
        with get_connection(self.db_path) as conn:
            # Query access logs grouped by memory_id + day_of_week + hour_of_day
            cursor = conn.execute("""
                SELECT
                    memory_id,
                    day_of_week,
                    hour_of_day,
                    COUNT(*) as occurrence_count
                FROM memory_access_log
                GROUP BY memory_id, day_of_week, hour_of_day
                HAVING COUNT(*) >= ?
            """, (min_occurrences,))

            patterns = []
            now = int(datetime.now().timestamp())

            for row in cursor:
                memory_id, dow, hour, count = row

                # Classify pattern_type
                if dow is not None and hour is not None:
                    pattern_type = 'weekly'  # Specific day + hour
                    trigger = f"{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][dow]} {hour}:00"
                elif hour is not None:
                    pattern_type = 'daily'  # Same hour every day
                    trigger = f"Daily {hour}:00"
                else:
                    pattern_type = 'monthly'  # Less specific
                    trigger = 'Monthly pattern'

                # Calculate confidence: min(1.0, count / (count + 2))
                confidence = min(1.0, count / (count + 2))

                # Generate pattern_id
                pattern_id = hashlib.md5(
                    f"{pattern_type}-{trigger}-{memory_id}".encode()
                ).hexdigest()[:16]

                # CREATE OR REPLACE pattern
                conn.execute("""
                    INSERT OR REPLACE INTO temporal_patterns
                    (id, pattern_type, trigger_condition, predicted_need,
                     memory_ids, confidence, occurrence_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pattern_id,
                    pattern_type,
                    trigger,
                    f"Memory {memory_id[:8]}...",  # Placeholder
                    json.dumps([memory_id]),
                    confidence,
                    count,
                    now,
                    now
                ))

                patterns.append({
                    'id': pattern_id,
                    'pattern_type': pattern_type,
                    'trigger_condition': trigger,
                    'memory_ids': [memory_id],
                    'confidence': confidence,
                    'occurrence_count': count
                })

            conn.commit()
            return patterns

    def predict_needs(
        self,
        current_time: Optional[datetime] = None,
        confidence_threshold: float = 0.7
    ) -> List[Dict]:
        """
        Predict likely-needed memories based on current time/context.

        Args:
            current_time: Time to predict for (default: now)
            confidence_threshold: Min confidence to surface prediction

        Returns:
            List of predictions: [
                {
                    'pattern_id': '...',
                    'predicted_need': 'Connection Lab context',
                    'memory_ids': ['mem1', 'mem2'],
                    'confidence': 0.85,
                    'trigger_condition': 'Monday 9am'
                }
            ]
        """
        if current_time is None:
            current_time = datetime.now()

        current_dow = current_time.weekday()  # 0=Monday
        current_hour = current_time.hour

        with get_connection(self.db_path) as conn:
            # Find patterns matching current day_of_week + hour_of_day
            cursor = conn.execute("""
                SELECT id, pattern_type, trigger_condition, predicted_need,
                       memory_ids, confidence
                FROM temporal_patterns
                WHERE confidence >= ?
            """, (confidence_threshold,))

            predictions = []
            for row in cursor:
                pattern_id, pattern_type, trigger, predicted_need, memory_ids_json, confidence = row

                # Parse trigger_condition and match against current time
                match = False
                if pattern_type == 'weekly':
                    # Extract day + hour from trigger like "Monday 9:00"
                    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    for i, day in enumerate(days):
                        if trigger.startswith(day):
                            trigger_hour = int(trigger.split()[1].split(':')[0])
                            if i == current_dow and trigger_hour == current_hour:
                                match = True
                elif pattern_type == 'daily':
                    # Extract hour from trigger like "Daily 9:00"
                    trigger_hour = int(trigger.split()[1].split(':')[0])
                    if trigger_hour == current_hour:
                        match = True

                if match:
                    predictions.append({
                        'pattern_id': pattern_id,
                        'predicted_need': predicted_need,
                        'memory_ids': json.loads(memory_ids_json),
                        'confidence': confidence,
                        'trigger_condition': trigger
                    })

            return predictions

    def confirm_prediction(self, pattern_id: str):
        """
        Record that prediction was correct.
        Increases confidence.
        """
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE temporal_patterns
                SET
                    occurrence_count = occurrence_count + 1,
                    last_confirmed = ?,
                    confidence = MIN(1.0, confidence + 0.05),
                    updated_at = ?
                WHERE id = ?
            """, (now, now, pattern_id))
            conn.commit()

    def dismiss_prediction(self, pattern_id: str):
        """
        Record that prediction was incorrect.
        Decreases confidence.
        """
        with get_connection(self.db_path) as conn:
            conn.execute("""
                UPDATE temporal_patterns
                SET
                    dismissed_count = dismissed_count + 1,
                    last_dismissed = ?,
                    confidence = MAX(0.0, confidence - 0.1),
                    updated_at = ?
                WHERE id = ?
            """, (now, now, pattern_id))
            conn.commit()

    def get_pattern_stats(self) -> Dict:
        """
        Get pattern detection statistics.

        Returns:
            {
                'total_patterns': 42,
                'active_patterns': 28,  # confidence > 0.7
                'total_accesses_logged': 1523,
                'patterns_by_type': {'daily': 10, 'weekly': 18, ...}
            }
        """
```

---

## Integration Points

### 1. IntelligenceDB Integration

Add tables to `src/intelligence_db.py`:

```python
def _init_schema(self):
    # ... existing tables ...

    # Add temporal_patterns table
    # Add memory_access_log table
```

### 2. MemoryTSClient Instrumentation

Instrument `src/memory_ts_client.py` to log accesses:

```python
from wild.temporal_predictor import TemporalPatternPredictor

class MemoryTSClient:
    def __init__(self, project_id: str):
        # ... existing init ...
        self.predictor = TemporalPatternPredictor()

    def get(self, memory_id: str) -> Memory:
        memory = # ... existing get logic ...

        # Log access
        self.predictor.log_memory_access(
            memory_id=memory_id,
            access_type='direct',
            session_id=os.getenv('CLAUDE_SESSION_ID')
        )

        return memory

    def search(self, content: str, **kwargs) -> List[Memory]:
        results = # ... existing search logic ...

        # Log all accessed memories
        for memory in results:
            self.predictor.log_memory_access(
                memory_id=memory.id,
                access_type='search',
                context_keywords=content.split(),
                session_id=os.getenv('CLAUDE_SESSION_ID')
            )

        return results
```

### 3. Hook System Integration

Install hook:
1. Copy `topic-resumption-detector.py` to hooks directory
2. Add entry to `~/.claude/settings.json` under `UserPromptSubmit`
3. Test with bypass: `SKIP_HOOK_TOPIC_RESUMPTION=1`

---

## Test Plan

### 22 Tests Total

**Hook Tests (8 tests):**
1. Phrase detection: Matches all trigger phrases
2. Phrase detection: Ignores non-trigger messages
3. Keyword extraction: Extracts relevant topic words
4. Keyword extraction: Removes stopwords
5. Memory search: Returns relevant results
6. Memory search: Falls back to MemoryTSClient
7. Output formatting: Includes session resume links
8. Performance: Completes within 3000ms timeout

**Pattern Detection Tests (6 tests):**
1. Detect daily pattern (same hour, multiple days)
2. Detect weekly pattern (same day+hour, multiple weeks)
3. No pattern when occurrences < threshold (min 3)
4. Pattern confidence calculated correctly
5. Overlapping patterns handled (Monday 9am AND meeting prep)
6. Stale patterns decay (no confirmation in 30 days)

**Prediction Tests (4 tests):**
1. Predict needs at correct time (Monday 9am → Connection Lab)
2. Filter by confidence threshold (only >0.7)
3. No predictions when no patterns exist
4. Predictions include correct memory_ids

**Feedback Loop Tests (4 tests):**
1. Confirm prediction increases confidence (+0.05)
2. Dismiss prediction decreases confidence (-0.1)
3. Confidence clamped to [0.0, 1.0]
4. Multiple dismissals disable pattern (confidence → 0)

---

## Edge Cases

1. **Cold start:** No access logs yet → no patterns detected
2. **Sparse data:** <3 occurrences → pattern not surfaced
3. **Behavior change:** User stops Monday 9am pattern → confidence decays
4. **False positives:** Hook triggers but no relevant memories → empty output
5. **Timeout:** Hook exceeds 3000ms → killed by system (no crash)
6. **Multiple patterns:** User has both daily and event-based patterns → all surfaced

---

## Performance Considerations

**At 10K scale:**
- memory_access_log: ~50K entries (10K memories × 5 accesses avg)
- temporal_patterns: ~500 entries
- Database size: ~5MB total

**Hook performance:**
- Phrase detection: <10ms (regex on single message)
- Keyword extraction: <50ms (stopword removal)
- Memory search: <500ms (hybrid_search with limit=5)
- Total budget: 3000ms (plenty of headroom)

**Query optimization:**
- Indexes on day_of_week, hour_of_day for temporal lookups
- memory_access_log cleanup: Delete entries >90 days old (nightly job)

---

## Success Criteria

1. **Hook works:** "We discussed this previously didn't we?" → auto-surfaces memories
2. **Pattern detection:** After 3 Monday 9am accesses → pattern detected
3. **Prediction quality:** Confidence >0.7 predictions are correct >80% of time
4. **Performance:** Hook completes <3000ms in 95th percentile
5. **Tests:** 22/22 passing
6. **Documentation:** CHANGELOG, SHOWCASE, PLAN updated

---

## Implementation Sequence

1. Create hook file (`topic-resumption-detector.py`)
2. Implement phrase detection and keyword extraction
3. Integrate with hybrid_search for memory lookup
4. Test hook in isolation (8 tests)
5. Add database tables to intelligence_db.py
6. Implement TemporalPatternPredictor class
7. Test pattern detection and prediction (10 tests)
8. Instrument MemoryTSClient for access logging
9. Test feedback loop (4 tests)
10. Update CHANGELOG, SHOWCASE, PLAN
11. Commit with comprehensive message

---

**Status:** READY FOR IMPLEMENTATION
