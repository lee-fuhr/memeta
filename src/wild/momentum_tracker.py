"""F52: Conversation Momentum Tracking

Tracks conversation momentum score (0-100) to detect progress patterns:
- "on_roll": New insights, decisions made, forward progress
- "steady": Consistent progress
- "stuck": Repeated questions, no new info
- "spinning": Topic cycling, no progress

Usage:
    from wild.momentum_tracker import MomentumTracker

    tracker = MomentumTracker()

    # Track momentum for a session
    score = tracker.track_momentum(
        session_id="abc123",
        new_insights=3,
        decisions_made=2,
        repeated_questions=0,
        topic_cycles=0
    )

    # Get momentum history
    history = tracker.get_momentum_history("abc123")

    # Get intervention suggestion when stuck
    intervention = tracker.suggest_intervention("abc123")
"""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


@dataclass
class MomentumScore:
    """Momentum score data"""
    id: str
    session_id: str
    timestamp: int
    momentum_score: float  # 0-100
    indicators: Dict[str, int]
    state: str  # on_roll, steady, stuck, spinning
    intervention_suggested: Optional[str] = None


class MomentumTracker:
    """Tracks conversation momentum to detect progress or stagnation"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize momentum tracker

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def track_momentum(
        self,
        session_id: str,
        new_insights: int = 0,
        decisions_made: int = 0,
        repeated_questions: int = 0,
        topic_cycles: int = 0
    ) -> MomentumScore:
        """Track momentum for a session

        Args:
            session_id: Session identifier
            new_insights: Count of new insights discovered
            decisions_made: Count of decisions made
            repeated_questions: Count of repeated questions
            topic_cycles: Count of topic cycles (returning to same topic)

        Returns:
            MomentumScore with current score and state
        """
        # Calculate momentum score (0-100)
        # Positive indicators: +20 per insight, +15 per decision
        # Negative indicators: -10 per repeated question, -15 per cycle
        positive = (new_insights * 20) + (decisions_made * 15)
        negative = (repeated_questions * 10) + (topic_cycles * 15)

        # Base score of 50, clamped to 0-100
        score = max(0, min(100, 50 + positive - negative))

        # Determine state
        if score >= 75:
            state = "on_roll"
        elif score >= 50:
            state = "steady"
        elif score >= 25:
            state = "stuck"
        else:
            state = "spinning"

        # Build indicators dict
        indicators = {
            "new_insights": new_insights,
            "decisions_made": decisions_made,
            "repeated_questions": repeated_questions,
            "topic_cycles": topic_cycles
        }

        # Suggest intervention if needed
        intervention = None
        if state in ("stuck", "spinning"):
            intervention = self._generate_intervention(state, indicators)

        # Save to database
        momentum_id = str(uuid.uuid4())
        timestamp = int(time.time())

        self.db.conn.execute(
            """
            INSERT INTO momentum_tracking
            (id, session_id, timestamp, momentum_score, indicators, state, intervention_suggested)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (momentum_id, session_id, timestamp, score, json.dumps(indicators), state, intervention)
        )
        self.db.conn.commit()

        return MomentumScore(
            id=momentum_id,
            session_id=session_id,
            timestamp=timestamp,
            momentum_score=score,
            indicators=indicators,
            state=state,
            intervention_suggested=intervention
        )

    def get_momentum_history(self, session_id: str, limit: int = 10) -> List[MomentumScore]:
        """Get momentum history for a session

        Args:
            session_id: Session identifier
            limit: Maximum number of records to return

        Returns:
            List of MomentumScore objects, newest first
        """
        rows = self.db.conn.execute(
            """
            SELECT id, session_id, timestamp, momentum_score, indicators, state, intervention_suggested
            FROM momentum_tracking
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (session_id, limit)
        ).fetchall()

        return [
            MomentumScore(
                id=row["id"],
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                momentum_score=row["momentum_score"],
                indicators=json.loads(row["indicators"]),
                state=row["state"],
                intervention_suggested=row["intervention_suggested"]
            )
            for row in rows
        ]

    def suggest_intervention(self, session_id: str) -> Optional[str]:
        """Get intervention suggestion for current session state

        Args:
            session_id: Session identifier

        Returns:
            Intervention suggestion or None if not stuck
        """
        # Get most recent momentum score
        history = self.get_momentum_history(session_id, limit=1)
        if not history:
            return None

        latest = history[0]
        if latest.state not in ("stuck", "spinning"):
            return None

        return latest.intervention_suggested

    def _generate_intervention(self, state: str, indicators: Dict[str, int]) -> str:
        """Generate intervention suggestion based on state

        Args:
            state: Current momentum state
            indicators: Momentum indicators

        Returns:
            Intervention suggestion text
        """
        if state == "spinning":
            return "Consider: Take a break, step back and reframe the problem, or try a different approach entirely."

        # state == "stuck"
        if indicators["repeated_questions"] > 2:
            return "You're asking the same questions. Try: Review what you already know, look for missing context, or redefine the question."

        if indicators["topic_cycles"] > 2:
            return "You're cycling through topics. Try: Pick one topic and go deep, or make a decision to move forward."

        return "Progress is slow. Try: Break the problem into smaller pieces, or ask for help with a specific blocker."

    def get_session_statistics(self, session_id: str) -> Dict:
        """Get statistics for a session

        Args:
            session_id: Session identifier

        Returns:
            Dict with statistics
        """
        # Get all scores for session
        rows = self.db.conn.execute(
            """
            SELECT momentum_score, state
            FROM momentum_tracking
            WHERE session_id = ?
            ORDER BY timestamp ASC
            """,
            (session_id,)
        ).fetchall()

        if not rows:
            return {
                "total_checks": 0,
                "avg_momentum": 0.0,
                "state_distribution": {},
                "trend": "unknown"
            }

        scores = [row["momentum_score"] for row in rows]
        states = [row["state"] for row in rows]

        # Calculate state distribution
        state_counts = {}
        for state in states:
            state_counts[state] = state_counts.get(state, 0) + 1

        # Determine trend (comparing first half vs second half)
        mid = len(scores) // 2
        if mid > 0:
            first_half_avg = sum(scores[:mid]) / mid
            second_half_avg = sum(scores[mid:]) / (len(scores) - mid)

            if second_half_avg > first_half_avg + 10:
                trend = "improving"
            elif second_half_avg < first_half_avg - 10:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "total_checks": len(scores),
            "avg_momentum": sum(scores) / len(scores),
            "state_distribution": state_counts,
            "trend": trend
        }
