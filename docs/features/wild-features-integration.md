# Wild Features Integration Guide

**Quick start guide for integrating wild features into memory-system-v1**

---

## Installation

Wild features are already integrated into the codebase. No external dependencies required.

```bash
cd /Users/lee/CC/LFI/_\ Operations/memory-system-v1

# Verify installation
python3 -c "from src.wild import FrustrationDetector; print('✅ Wild features ready')"

# Run tests
pytest tests/wild/ -v
```

---

## Integration Points

### 1. Session Consolidation Hook (Post-session)

**File:** `hooks/session-memory-consolidation.py`

Add wild features to the existing consolidation flow:

```python
from src.wild import FrustrationDetector, MemoryQualityGrader, WritingStyleAnalyzer

def consolidate_session(session_id):
    """Enhanced session consolidation with wild features"""

    # Existing consolidation
    messages = load_session_messages(session_id)
    memories = extract_memories(messages)
    memories = deduplicate_memories(memories)

    # === WILD FEATURES ===

    # 1. Frustration detection
    frustration_detector = FrustrationDetector()
    event = frustration_detector.analyze_session(session_id, messages)

    if event and event.intervention_suggested:
        # Log intervention for next session start
        with open(f'/tmp/frustration_alert_{session_id}.txt', 'w') as f:
            f.write(event.intervention_text)

    # 2. Quality grading
    quality_grader = MemoryQualityGrader()
    for memory in memories:
        grade = quality_grader.grade_memory(
            memory_id=memory.id,
            content=memory.content,
            importance=memory.importance
        )
        # Store grade in memory metadata
        memory.metadata['quality_grade'] = grade.grade
        memory.metadata['quality_score'] = grade.score

    # 3. Writing style analysis
    writing_analyzer = WritingStyleAnalyzer()

    # Extract user text
    user_text = ' '.join(
        msg['content'] for msg in messages
        if msg.get('role') == 'user'
    )

    if user_text:
        snapshot = writing_analyzer.analyze_text(
            session_id=session_id,
            text=user_text,
            content_type='body'
        )

        # Check for significant trends (weekly)
        import datetime
        if datetime.datetime.now().weekday() == 4:  # Friday
            trends = writing_analyzer.detect_trends(days=30)
            significant_trends = [t for t in trends if t.is_significant]

            if significant_trends:
                # Log for weekly review
                with open('/tmp/writing_trends.txt', 'w') as f:
                    for trend in significant_trends:
                        f.write(f"{trend.interpretation}\n")

    # Continue with existing flow
    save_memories(memories)
    trigger_fsrs_scheduler(memories)
```

---

### 2. Nightly Processes (3am LaunchAgent)

**File:** `run_nightly_wild_features.py` (create new)

```python
#!/usr/bin/env python3
"""
Nightly wild features processes

Run at 3am via LaunchAgent: com.lfi.wild-features-nightly
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.wild import DreamSynthesizer, ExtractionPromptEvolver


def main():
    print(f"🌙 Starting nightly wild features: {datetime.now()}")

    # 1. Dream synthesis (nightly)
    print("\n💭 Running dream synthesis...")
    synthesizer = DreamSynthesizer()
    syntheses = synthesizer.run_nightly_synthesis()

    print(f"   Generated {len(syntheses)} syntheses")
    high_novelty = [s for s in syntheses if s.novelty_score >= 0.5]
    print(f"   {len(high_novelty)} queued for morning review")

    # 2. Prompt evolution (weekly - Fridays only)
    if datetime.now().weekday() == 4:
        print("\n🧬 Running weekly prompt evolution...")
        evolver = ExtractionPromptEvolver()

        # Check if needs initialization
        active_prompts = evolver._get_active_prompts()
        if not active_prompts:
            print("   Initializing first generation...")
            evolver.initialize_population()

        # Evolve generation
        next_gen = evolver.evolve_generation()
        print(f"   Evolved to generation {next_gen}")

        best = evolver.get_best_prompt()
        print(f"   Best fitness: {best.fitness_score:.2f}")

        if best.fitness_score >= 0.80:
            print(f"   ✨ High-performing prompt available for adoption")

    print(f"\n✅ Nightly wild features complete: {datetime.now()}")


if __name__ == '__main__':
    main()
```

**LaunchAgent plist:** `~/Library/LaunchAgents/com.lfi.wild-features-nightly.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lfi.wild-features-nightly</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/lee/CC/LFI/_ Operations/memory-system-v1/run_nightly_wild_features.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/lee/Library/Logs/wild-features-nightly.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/lee/Library/Logs/wild-features-nightly-error.log</string>
</dict>
</plist>
```

Install:
```bash
launchctl load ~/Library/LaunchAgents/com.lfi.wild-features-nightly.plist
```

---

### 3. Morning Triage Integration

**File:** `_ Operations/triage_data.py`

Add dream synthesis briefing:

```python
from src.wild import DreamSynthesizer

def get_morning_briefing():
    """Get morning briefing including dream syntheses"""

    briefing = {
        'calendar': get_calendar_events(),
        'tasks': get_todoist_tasks(),
        'email': get_unread_emails(),
        # ... existing sections
    }

    # Add dream syntheses
    synthesizer = DreamSynthesizer()
    syntheses = synthesizer.get_morning_briefing(limit=5)

    if syntheses:
        briefing['dream_syntheses'] = [
            {
                'title': syn.title,
                'insight': syn.insight,
                'projects': syn.projects_spanned,
                'novelty': syn.novelty_score,
                'confidence': syn.confidence
            }
            for syn in syntheses
        ]

        # Mark as presented
        for syn in syntheses:
            synthesizer.mark_presented(syn.id)

    return briefing
```

**Display in triage:**

```
## 💡 Overnight Insights (Dream Synthesis)

While you slept, I found these connections:

**Synchronized Evolution** (Novelty: 72%, Confidence: 85%)
→ 4 themes emerged simultaneously across projects
   Projects: Connection Lab, Cogent, Russell Hamilton

**Cross-project Pattern Detection** (Novelty: 68%, Confidence: 90%)
→ Found 7 semantic parallels across 3 projects
   Common pattern: "verification before deployment"

**Context-dependent Patterns** (Novelty: 65%, Confidence: 75%)
→ 3 apparent contradictions need context resolution
   About: client communication cadence
```

---

### 4. A/B Testing Integration (Weekly)

**File:** `run_weekly_ab_tests.py` (create new)

```python
#!/usr/bin/env python3
"""
Weekly A/B tests for memory strategies

Run Friday evenings via LaunchAgent
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.wild import MemoryStrategyTester, Strategy


def main():
    tester = MemoryStrategyTester()

    # Get recent sessions for testing
    sample_sessions = load_recent_sessions(days=7, limit=50)

    # Experiment 1: Deduplication threshold
    exp1 = tester.create_experiment(
        name="Dedup Threshold 70 vs 80",
        description="Test if 70% or 80% word overlap is better for deduplication",
        strategy_a=Strategy(
            id='dedup_70',
            name='70% Threshold',
            description='More aggressive deduplication',
            parameters={'dedup_threshold': 0.70}
        ),
        strategy_b=Strategy(
            id='dedup_80',
            name='80% Threshold',
            description='More permissive deduplication',
            parameters={'dedup_threshold': 0.80}
        ),
        success_metric='uniqueness_rate',
        target_samples=50
    )

    # Run and analyze
    tester.run_experiment(
        experiment_id=exp1.id,
        test_function=run_deduplication_test,
        test_sessions=sample_sessions
    )

    results = tester.analyze_results(exp1.id)

    print(f"Winner: {results['winning_strategy']}")
    print(f"Improvement: +{results['improvement_pct']:.1f}%")

    if results['adopted']:
        print("✨ Auto-adopted for production use")


if __name__ == '__main__':
    main()
```

---

### 5. Real-time Frustration Alerts (Optional)

For immediate frustration detection during sessions (not just post-session):

**File:** Add to session hook (UserPromptSubmit)

```python
from src.wild import FrustrationDetector

# In UserPromptSubmit hook
def check_frustration_realtime(session_id, recent_messages):
    """Check frustration on every 10th user message"""

    detector = FrustrationDetector()

    # Analyze last 20 messages
    event = detector.analyze_session(session_id, recent_messages[-20:])

    if event and event.combined_score >= 0.6:  # Lower threshold for early warning
        # Create notification
        notify_user(f"⚠️ Early frustration signal detected: {event.signals[0].intervention}")
```

---

## Monitoring

### Check Wild Features Status

```bash
# View frustration events
sqlite3 intelligence.db "SELECT session_id, combined_score, intervention_text FROM frustration_events ORDER BY created_at DESC LIMIT 5"

# View quality grade distribution
sqlite3 intelligence.db "SELECT grade, COUNT(*) FROM memory_quality_grades GROUP BY grade"

# View recent style trends
sqlite3 intelligence.db "SELECT metric, direction, interpretation FROM style_trends ORDER BY detected_at DESC LIMIT 5"

# View queued syntheses
sqlite3 intelligence.db "SELECT title, novelty_score, confidence FROM dream_syntheses WHERE reviewed = 0 ORDER BY created_at DESC"

# View A/B test results
sqlite3 intelligence.db "SELECT name, winner, confidence FROM ab_experiments WHERE status = 'completed' ORDER BY completed_at DESC"
```

### Logs

```bash
# Nightly processes
tail -f ~/Library/Logs/wild-features-nightly.log

# Integration errors
tail -f ~/Library/Logs/wild-features-nightly-error.log
```

---

## Configuration

### Thresholds (adjust in source files)

**Frustration Detection:**
```python
# src/wild/frustration_detector.py
SIGNAL_THRESHOLD = 0.6          # Individual signal threshold
INTERVENTION_THRESHOLD = 0.7    # Combined threshold for intervention
CORRECTION_COUNT_THRESHOLD = 3  # Corrections to trigger signal
```

**Quality Grading:**
```python
# src/wild/quality_grader.py
GRADE_A_MIN = 0.85  # Minimum score for A grade
GRADE_B_MIN = 0.65  # Minimum score for B grade
GRADE_C_MIN = 0.40  # Minimum score for C grade
```

**Prompt Evolution:**
```python
# src/wild/prompt_evolver.py
POPULATION_SIZE = 10         # Number of prompt variants
TOP_PERFORMERS = 4           # How many breed to next generation
MUTATION_RATE = 0.3          # 30% chance of mutation
ADOPTION_CONFIDENCE = 0.95   # Confidence required for auto-adoption
```

**Writing Analysis:**
```python
# src/wild/writing_analyzer.py
SIGNIFICANT_CHANGE_THRESHOLD = 0.20  # 20% change is significant
TREND_WINDOW_DAYS = 30               # Look back period
MIN_SAMPLES = 10                     # Minimum sessions for trend
```

**Dream Synthesis:**
```python
# src/wild/dream_synthesizer.py
SEMANTIC_THRESHOLD = 0.6      # Minimum similarity for connection
TEMPORAL_WINDOW = timedelta(days=7)  # Co-occurrence window
NOVELTY_THRESHOLD = 0.5       # Minimum novelty to queue
```

---

## Troubleshooting

### Database not found

```bash
# Wild features DB auto-creates on first use
python3 -c "from src.wild import FrustrationDetector; FrustrationDetector()"

# Check it exists
ls -lh intelligence.db
```

### Import errors

```bash
# Verify Python path
python3 -c "import sys; print('\n'.join(sys.path))"

# Check src directory structure
tree src/wild/
```

### No syntheses in morning briefing

```bash
# Check if nightly synthesis ran
tail -f ~/Library/Logs/wild-features-nightly.log

# Check queue
sqlite3 intelligence.db "SELECT COUNT(*) FROM synthesis_queue WHERE presented = 0"

# Run manually to debug
python3 -c "from src.wild import DreamSynthesizer; s = DreamSynthesizer(); s.run_nightly_synthesis()"
```

### LaunchAgent not running

```bash
# Check if loaded
launchctl list | grep wild

# Load it
launchctl load ~/Library/LaunchAgents/com.lfi.wild-features-nightly.plist

# Force run now (for testing)
launchctl start com.lfi.wild-features-nightly
```

---

## Performance

**Database size growth:**
- Frustration signals: ~500 bytes/signal
- Quality grades: ~200 bytes/memory
- Writing snapshots: ~400 bytes/session
- Dream connections: ~300 bytes/connection
- Expected: ~2-5 MB/month with typical usage

**Query performance:**
- All tables indexed on key columns
- FTS not needed (wild features use simple queries)
- Expected: <10ms for all queries

**Integration overhead:**
- Session consolidation: +50-100ms
- Nightly synthesis: ~5-10 seconds (runs at 3am)
- Prompt evolution: ~30 seconds/week (Friday evenings)

---

## Rollback Plan

If wild features cause issues:

1. **Disable nightly processes:**
```bash
launchctl unload ~/Library/LaunchAgents/com.lfi.wild-features-nightly.plist
```

2. **Remove from consolidation hook:**
Comment out wild features section in `hooks/session-memory-consolidation.py`

3. **Preserve data:**
Database remains intact for future re-enable

4. **Re-enable when ready:**
```bash
launchctl load ~/Library/LaunchAgents/com.lfi.wild-features-nightly.plist
```

---

## Next Steps

**After integration:**
1. Monitor frustration alerts for 1 week
2. Review quality grade distribution
3. Check dream synthesis morning briefings
4. Review first A/B test results
5. Analyze writing style trends

**Future enhancements:**
- Export wild features data to dashboard
- Add Pushover notifications for high-priority interventions
- Integrate with session-index for better context
- Create visual charts for writing evolution

---

**Status:** Ready for integration
**Estimated integration time:** 30 minutes
**Testing period:** 1 week minimum before auto-adoption
