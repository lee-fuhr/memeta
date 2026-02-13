#!/usr/bin/env python3
"""
Demo script for Features 33-42 (Wild Features)

Run this to see all features in action.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wild.sentiment_tracker import analyze_sentiment, get_sentiment_trends
from wild.learning_velocity import calculate_velocity_metrics
from wild.personality_drift import record_personality_snapshot
from wild.conflict_predictor import predict_conflicts
from wild.lifespan_integration import analyze_memory_lifespans
from wild.integrations import export_to_roam, learn_email_pattern


def demo_sentiment():
    """Feature 33: Sentiment Tracking"""
    print("\n=== Feature 33: Sentiment Tracking ===")

    examples = [
        "This is annoying and doesn't work",
        "Perfect! Exactly what I wanted, thanks",
        "The system processes the data"
    ]

    for text in examples:
        sentiment, triggers = analyze_sentiment(text)
        print(f"Text: {text}")
        print(f"  → Sentiment: {sentiment}")
        print(f"  → Triggers: {triggers}\n")

    # Get trends (will be empty without database)
    trends = get_sentiment_trends(days=30)
    print(f"Trend status: {trends['trend']}")


def demo_velocity():
    """Feature 34: Learning Velocity"""
    print("\n=== Feature 34: Learning Velocity ===")

    metrics = calculate_velocity_metrics(window_days=30)
    print(f"Velocity Score: {metrics['velocity_score']:.1f}/100")
    print(f"Status: {metrics['status']}")
    print(f"Correction Rate: {metrics['correction_rate']:.1%}")


def demo_personality():
    """Feature 35: Personality Drift"""
    print("\n=== Feature 35: Personality Drift ===")

    snapshot = record_personality_snapshot(window_days=30)
    print(f"Directness: {snapshot['directness']:.2f}")
    print(f"Verbosity: {snapshot['verbosity']:.2f}")
    print(f"Formality: {snapshot['formality']:.2f}")
    print(f"Sample size: {snapshot['sample_size']}")


def demo_conflict():
    """Feature 37: Conflict Prediction"""
    print("\n=== Feature 37: Conflict Prediction ===")

    new_memory = "User prefers afternoon meetings"
    prediction = predict_conflicts(new_memory)

    print(f"New memory: {new_memory}")
    print(f"Conflict predicted: {prediction['conflict_predicted']}")
    print(f"Confidence: {prediction['confidence']:.1%}")
    print(f"Action: {prediction['action']}")


def demo_lifespan():
    """Feature 36: Lifespan Prediction"""
    print("\n=== Feature 36: Lifespan Prediction ===")

    analysis = analyze_memory_lifespans()
    print(f"Total memories: {analysis['total_memories']}")
    print(f"Evergreen: {analysis['evergreen_percent']:.1f}%")
    print(f"Needs review: {analysis['needs_review_count']}")


def demo_integrations():
    """Features 38-42: Integrations"""
    print("\n=== Features 38-42: Integrations ===")

    # Roam export
    print("\nRoam export format:")
    roam_text = export_to_roam()
    print(roam_text[:200] + "..." if len(roam_text) > 200 else roam_text)

    # Email pattern learning
    print("\nEmail pattern learning:")
    pattern_id = learn_email_pattern(
        "categorization",
        "from:client@example.com → Important",
        confidence=0.9
    )
    print(f"Learned pattern ID: {pattern_id}")


def main():
    """Run all demos"""
    print("=" * 60)
    print("Wild Features (33-42) Demo")
    print("=" * 60)

    try:
        demo_sentiment()
        demo_velocity()
        demo_personality()
        demo_conflict()
        demo_lifespan()
        demo_integrations()

        print("\n" + "=" * 60)
        print("✅ Demo complete!")
        print("\nFor full API docs, see: docs/wild-features-api.md")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("Note: Some features require initialized database and memories")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
