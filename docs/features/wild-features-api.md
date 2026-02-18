# Features 33-42 API Documentation

Complete API reference and usage examples for wild features (AI Analysis + Integrations).

---

## Feature 33: Sentiment Tracking

**Purpose:** Detect frustration/satisfaction trends to trigger proactive optimizations.

### API

```python
from src.wild.sentiment_tracker import (
    analyze_sentiment,
    track_memory_sentiment,
    get_sentiment_trends,
    should_trigger_optimization
)

# Analyze single piece of content
sentiment, triggers = analyze_sentiment("This is frustrating and broken")
# Returns: ('frustrated', 'frustrating, broken')

# Track memory sentiment
track_memory_sentiment(
    memory={'id': 'mem_123', 'content': 'User correction...'},
    session_id='session_456'
)

# Get 30-day trends
trends = get_sentiment_trends(days=30)
# Returns: {
#     'total': 150,
#     'frustrated': 25,
#     'satisfied': 80,
#     'neutral': 45,
#     'frustration_rate': 0.167,
#     'trend': 'improving',
#     'common_triggers': [{'trigger': 'mistake', 'count': 8}, ...]
# }

# Check if optimization needed
trigger = should_trigger_optimization(threshold=0.3, days=7)
# Returns: {
#     'should_optimize': True,
#     'reason': 'Frustration rate 35% exceeds threshold 30%',
#     'common_issues': [...],
#     'recommendation': 'Review recent corrections...'
# }
```

### Use Cases
- **Daily monitoring:** Run `get_sentiment_trends(days=7)` in morning automation
- **Optimization triggers:** Call `should_trigger_optimization()` after each session
- **Root cause analysis:** Review `common_triggers` to identify pain points

---

## Feature 34: Learning Velocity

**Purpose:** Measure system improvement rate via correction frequency tracking.

### API

```python
from src.wild.learning_velocity import (
    calculate_velocity_metrics,
    get_velocity_trend,
    get_correction_breakdown,
    get_roi_estimate
)

# Calculate current velocity (30-day window)
metrics = calculate_velocity_metrics(window_days=30)
# Returns: {
#     'total_memories': 120,
#     'corrections': 18,
#     'correction_rate': 0.15,
#     'velocity_score': 85.0,  # 0-100 scale
#     'status': 'good'  # excellent | good | fair | needs_improvement
# }

# Analyze 90-day trend
trend = get_velocity_trend(days=90)
# Returns: {
#     'trend': 'improving',  # accelerating | improving | stable | declining
#     'acceleration': 12.5,  # Velocity point change
#     'improvement_percent': 14.7,
#     'recent_velocity': 92.0,
#     'older_velocity': 79.5
# }

# Break down corrections by category
breakdown = get_correction_breakdown(window_days=30)
# Returns: {
#     'total': 18,
#     'by_category': {'tools': 8, 'preferences': 6, 'technical': 4},
#     'common_patterns': [{'term': 'missed', 'count': 5}, ...]
# }

# Estimate ROI
roi = get_roi_estimate(days=90)
# Returns: {
#     'velocity_improvement': '14.7%',
#     'estimated_time_savings': '7.4%',
#     'hours_saved_per_week': '2.9h',
#     'trend': 'improving'
# }
```

### Use Cases
- **Weekly reports:** Show velocity trends to stakeholders
- **System health:** Monitor correction rates for degradation
- **ROI tracking:** Justify memory system investment

---

## Feature 35: Personality Drift

**Purpose:** Detect communication style evolution (directness/verbosity/formality).

### API

```python
from src.wild.personality_drift import (
    record_personality_snapshot,
    detect_drift,
    analyze_communication_style
)

# Take daily snapshot
snapshot = record_personality_snapshot(window_days=30)
# Returns: {
#     'directness': 0.75,  # 0.0 = indirect, 1.0 = very direct
#     'verbosity': 0.35,   # 0.0 = concise, 1.0 = verbose
#     'formality': 0.20,   # 0.0 = casual, 1.0 = formal
#     'sample_size': 100,
#     'date': '2026-02-12'
# }

# Detect drift over 6 months
drift = detect_drift(days=180)
# Returns: {
#     'drift_detected': True,
#     'magnitude': 0.23,
#     'is_intentional': True,  # Steady progression vs erratic
#     'directness_change': +0.15,
#     'verbosity_change': -0.10,
#     'formality_change': -0.05,
#     'baseline_date': '2025-08-12',
#     'recent_date': '2026-02-12'
# }
```

### Use Cases
- **Style consistency:** Alert if unintentional drift detected
- **Intentional evolution:** Track deliberate style changes
- **User profiling:** Build communication preference model

---

## Feature 36: Lifespan Prediction

**Purpose:** Predict when memories become stale and flag for review.

### API

```python
from src.wild.lifespan_integration import (
    analyze_memory_lifespans,
    flag_expiring_memories,
    predict_lifespan_category
)

# Analyze all memories
analysis = analyze_memory_lifespans()
# Returns: {
#     'total_memories': 500,
#     'by_category': {
#         'evergreen': 250,
#         'short_term': 100,
#         'medium_term': 100,
#         'long_term': 50
#     },
#     'evergreen_percent': 50.0,
#     'needs_review_count': 5,
#     'needs_review': [...]  # Memories expiring in 7 days
# }

# Get memories expiring soon
expiring = flag_expiring_memories(days_threshold=7)
# Returns: [
#     {
#         'id': 'mem_123',
#         'content': 'Q1 deadline for...',
#         'expires_in_days': 3,
#         'expiration_date': '2026-02-15'
#     }
# ]

# Predict category for new memory
category = predict_lifespan_category("Always prefer morning meetings")
# Returns: 'evergreen'
```

### Use Cases
- **Weekly review:** Run `flag_expiring_memories()` to surface stale data
- **Cleanup automation:** Archive expired memories automatically
- **Importance weighting:** Decay importance for time-bound memories after expiration

---

## Feature 37: Conflict Prediction

**Purpose:** Prevent contradictions by flagging conflicts BEFORE saving.

### API

```python
from src.wild.conflict_predictor import predict_conflicts

# Before saving new memory
prediction = predict_conflicts(
    "User prefers afternoon meetings at 2pm",
    confidence_threshold=0.6
)
# Returns: {
#     'conflict_predicted': True,
#     'confidence': 0.82,
#     'conflicting_memory_id': 'mem_45',
#     'conflicting_content': 'User prefers morning meetings at 9am',
#     'reasoning': 'Detected contradiction with existing memory',
#     'action': 'replace',  # or 'merge' or 'skip'
#     'similar_memories_count': 5
# }

# If conflict detected, prompt user:
if prediction['conflict_predicted']:
    print(f"⚠️  Conflict detected (confidence: {prediction['confidence']:.0%})")
    print(f"Existing: {prediction['conflicting_content']}")
    # User chooses: save_anyway | skip | merge | replace
```

### Use Cases
- **Pre-save validation:** Check all new memories before committing
- **User prompts:** Show conflicts and let user decide action
- **Accuracy tracking:** Learn from user decisions to improve predictions

---

## Feature 38: Obsidian Sync

**Purpose:** Bidirectional markdown sync with Obsidian vaults.

### API

```python
from src.wild.integrations import export_to_obsidian, import_from_obsidian
from pathlib import Path

vault_path = Path.home() / "Documents/ObsidianVault"

# Export memories to Obsidian
count = export_to_obsidian(vault_path)
print(f"Exported {count} memories to {vault_path}/Memories/")

# Import Obsidian notes as memories
imported = import_from_obsidian(vault_path)
print(f"Imported {imported} notes from Obsidian")

# Bidirectional sync (manual for now)
export_to_obsidian(vault_path)  # Push changes
import_from_obsidian(vault_path)  # Pull changes
```

### File Format
```markdown
# Memory content preview

Full memory content here...

---
Tags: #preference #clients #meetings
Importance: 0.85
Project: [[Connection Lab]]
Created: 2026-02-12T10:30:00
```

---

## Feature 39: Notion Integration

**Purpose:** Sync memories to Notion databases.

### API

```python
from src.wild.integrations import export_to_notion

# Export to Notion database
database_id = "abc123..."
pages = export_to_notion(database_id)

# Returns Notion API-ready page objects
# Use with Notion API client (lfi_integrations.notion):
from lfi_integrations import notion
for page in pages:
    notion.create_page(database_id, page['properties'])
```

### Notion Schema
```
Name: Title (from memory content)
Content: Long text
Importance: Number (0-1)
Tags: Multi-select
Project: Text
Created: Date
```

---

## Feature 40: Roam Research Integration

**Purpose:** Export as Roam daily notes.

### API

```python
from src.wild.integrations import export_to_roam

# Generate Roam-formatted output
roam_text = export_to_roam()

# Save to file
with open("roam-export.md", "w") as f:
    f.write(roam_text)

# Or copy to clipboard for pasting into Roam
```

### Output Format
```markdown
## 2026-02-12
- Memory content here #memory #LFI
  - Importance:: 0.85
  - Tags:: #preference, #clients

## 2026-02-11
- Another memory #memory #ConnectionLab
  - Importance:: 0.75
  - Tags:: #technical
```

---

## Feature 41: Email Intelligence v2

**Purpose:** Learn email categorization patterns from user corrections.

### API

```python
from src.wild.integrations import learn_email_pattern, get_email_recommendations

# When user corrects email categorization
learn_email_pattern(
    correction_type="categorization",
    pattern_rule="from:client@example.com → Important",
    confidence=0.9
)

# Get recommendations for new email
recommendations = get_email_recommendations("Email from client@example.com...")
# Returns: {
#     'category': 'Important',
#     'priority': None,
#     'confidence': 0.9
# }
```

### Pattern Types
- **categorization:** "from:X → category"
- **threading:** "subject:Y → thread_with:Z"
- **priority:** "keyword:urgent → high_priority"

---

## Feature 42: Meeting Intelligence

**Purpose:** Link memories to meeting transcripts for context.

### API

```python
from src.wild.integrations import (
    link_memory_to_meeting,
    extract_memories_from_meeting
)

# Link existing memory to meeting
link_id = link_memory_to_meeting(
    memory_id="mem_123",
    meeting_title="Russell Hamilton sync"
)

# Extract insights from meeting transcript
memories = extract_memories_from_meeting(meeting_id=456)
# Creates memories tagged with meeting context
# Returns: [Memory(content='Decided to...', tags=['meeting', ...]), ...]
```

### Integration with Transcripts DB
```python
# The system automatically connects to:
# ~/CC/LFI/_ Operations/meeting-intelligence/transcripts.db
# Which contains 1,900+ indexed meeting transcripts

# Memories are linked with:
# - meeting_id (references transcripts.db)
# - meeting_date
# - participants
# - relevance_score
```

---

## Database Schema

All features use shared `intelligence.db`:

```sql
-- Feature 33
CREATE TABLE sentiment_patterns (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    sentiment TEXT CHECK(sentiment IN ('frustrated', 'satisfied', 'neutral')),
    trigger_words TEXT,
    context TEXT
);

-- Feature 34
CREATE TABLE learning_velocity (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    total_memories INTEGER,
    corrections INTEGER,
    correction_rate REAL,
    velocity_score REAL
);

-- Feature 35
CREATE TABLE personality_drift (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    directness_score REAL,
    verbosity_score REAL,
    formality_score REAL,
    sample_size INTEGER
);

-- Feature 37
CREATE TABLE conflict_predictions (
    id INTEGER PRIMARY KEY,
    new_memory_hash TEXT,
    predicted_conflict_id TEXT,
    confidence_score REAL,
    reasoning TEXT,
    was_accurate BOOLEAN
);

-- Features 38-40 (sync state tables)
CREATE TABLE obsidian_sync_state (...);
CREATE TABLE notion_sync_state (...);
CREATE TABLE roam_sync_state (...);

-- Feature 41
CREATE TABLE email_patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT,
    pattern_rule TEXT,
    confidence REAL,
    learned_from_corrections INTEGER
);

-- Feature 42
CREATE TABLE meeting_memories (
    id INTEGER PRIMARY KEY,
    memory_id TEXT,
    meeting_id TEXT,
    meeting_date TEXT,
    participants TEXT,
    relevance_score REAL
);
```

---

## CLI Tools

### Sentiment Monitor
```bash
# Daily sentiment check
python3 -m src.wild.sentiment_tracker --days 7

# Output:
# Sentiment Trends (7 days)
# ========================
# Total: 45 memories
# Frustrated: 8 (18%)
# Satisfied: 28 (62%)
# Neutral: 9 (20%)
# Trend: IMPROVING
#
# ⚠️  Top frustration triggers:
# 1. mistake (5 occurrences)
# 2. wrong (3 occurrences)
```

### Velocity Dashboard
```bash
# Weekly velocity report
python3 -m src.wild.learning_velocity --report weekly

# Output:
# Learning Velocity Report
# ========================
# Current velocity: 87.5/100 (GOOD)
# Trend: IMPROVING (+12.3% vs 4 weeks ago)
# Correction rate: 12.5% (down from 20%)
# ROI estimate: 6.2% time savings (2.5h/week)
```

### Expiring Memories Alert
```bash
# Flag memories expiring soon
python3 -m src.wild.lifespan_integration --expiring 7

# Output:
# Memories Expiring Soon
# ======================
# 5 memories expire in next 7 days:
#
# 1. [3 days] Q1 deadline for Connection Lab proposal
# 2. [5 days] Russell prefers meetings before 3pm (this week only)
# 3. [7 days] Temporary workaround for API rate limiting
```

---

## Automation Hooks

### Daily Tasks (LaunchAgent)
```bash
# Run at 7am daily
python3 -m src.wild.daily_intelligence

# Actions:
# - Calculate sentiment trends
# - Record velocity metrics
# - Take personality snapshot
# - Flag expiring memories
# - Generate dashboard data
```

### Session End Hook
```bash
# After each Claude Code session
python3 -m src.wild.session_analyzer

# Actions:
# - Track sentiment for new memories
# - Check for conflicts before saving
# - Update velocity calculations
```

---

## Integration Examples

### Morning Triage Integration
```python
# Add to triage_data.py

from src.wild.sentiment_tracker import should_trigger_optimization
from src.wild.lifespan_integration import flag_expiring_memories

# Check if system needs attention
optimization = should_trigger_optimization(threshold=0.3, days=7)
if optimization['should_optimize']:
    print(f"⚠️  SYSTEM HEALTH: {optimization['reason']}")
    print(f"   → {optimization['recommendation']}")

# Show expiring memories
expiring = flag_expiring_memories(days_threshold=7)
if expiring:
    print(f"\n📅 {len(expiring)} memories expiring soon:")
    for mem in expiring[:3]:
        print(f"   [{mem['expires_in_days']}d] {mem['content'][:60]}...")
```

### Weekly Review Integration
```python
# Add to weekly_synthesis.py

from src.wild.learning_velocity import get_velocity_trend, get_roi_estimate

trend = get_velocity_trend(days=90)
roi = get_roi_estimate(days=90)

print(f"""
## System Performance

**Learning Velocity:** {trend['trend'].upper()}
- Current: {trend['recent_velocity']:.1f}/100
- 90-day change: {trend['improvement_percent']:+.1f}%
- Time savings: {roi['hours_saved_per_week']} per week
- Correction rate trending: {'↓ DOWN' if trend['acceleration'] > 0 else '↑ UP'}
""")
```

---

## Production Checklist

**Before deploying:**

- [ ] Run full test suite: `pytest tests/wild/ -v`
- [ ] Initialize intelligence.db: `python3 -m src.wild.intelligence_db`
- [ ] Configure daily automation (LaunchAgent)
- [ ] Set up Obsidian vault path (if using)
- [ ] Configure Notion database ID (if using)
- [ ] Test transcripts.db connection (Feature 42)
- [ ] Set sentiment optimization threshold (default: 0.3)
- [ ] Configure expiring memory alerts (default: 7 days)

**Post-deployment monitoring:**

- Week 1: Review sentiment trends daily
- Week 2-4: Validate velocity calculations
- Month 2: Check personality drift detection
- Month 3: Evaluate ROI estimates vs actual time savings

---

## Support

**Issues:**
- Check `/Users/lee/CC/LFI/_ Operations/memory-system-v1/intelligence.db` exists
- Verify transcripts.db at `_ Operations/meeting-intelligence/transcripts.db`
- Run `pytest tests/wild/` to validate installation

**Performance:**
- Sentiment analysis: <10ms per memory
- Velocity calculation: ~50ms for 1000 memories
- Conflict prediction: ~100ms (depends on memory count)
- Database queries: <5ms (indexed)

**Limitations:**
- Email intelligence: Requires manual pattern addition (no auto-learning yet)
- Obsidian sync: One-way for now (manual bidirectional)
- Meeting extraction: Simple keyword-based (LLM integration planned)
