"""
Feature 47: Decision journal - Track decisions and outcomes

Integrates with ea_brain/commitment_tracker.py for decision tracking.
Learn from decision patterns over time.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from ..intelligence_db import IntelligenceDB
from ..memory_ts_client import MemoryTSClient


# Try to import ea_brain commitment tracker (optional integration)
try:
    import sys
    ea_brain_path = Path(__file__).parent.parent.parent.parent / "ea_brain"
    if ea_brain_path.exists():
        sys.path.insert(0, str(ea_brain_path))
        from commitment_tracker import CommitmentTracker
        EA_BRAIN_AVAILABLE = True
    else:
        EA_BRAIN_AVAILABLE = False
except ImportError:
    EA_BRAIN_AVAILABLE = False


@dataclass
class Decision:
    """Decision record"""
    decision: str
    options_considered: List[str]
    chosen_option: str
    rationale: str
    context: Optional[str] = None
    project_id: str = "LFI"
    session_id: Optional[str] = None
    decided_at: str = None
    outcome: Optional[str] = None
    outcome_success: Optional[bool] = None
    outcome_recorded_at: Optional[str] = None
    commitment_id: Optional[str] = None  # Link to ea_brain
    tags: List[str] = field(default_factory=lambda: ['#decision'])

    def __post_init__(self):
        if self.decided_at is None:
            self.decided_at = datetime.now().isoformat()


class DecisionJournal:
    """
    Decision tracking and outcome learning

    Workflow:
    1. Record decision with options and rationale
    2. (Optional) Link to ea_brain commitment if applicable
    3. Track outcome later
    4. Learn from patterns: what decisions work?
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize decision journal

        Args:
            db_path: Intelligence database path
        """
        self.db = IntelligenceDB(db_path)
        self.memory_client = MemoryTSClient()

        # Optional ea_brain integration
        if EA_BRAIN_AVAILABLE:
            try:
                ea_brain_db = Path(__file__).parent.parent.parent.parent / "ea_brain" / "ea_brain.db"
                self.commitment_tracker = CommitmentTracker(str(ea_brain_db))
            except Exception as e:
                print(f"Warning: ea_brain integration unavailable: {e}")
                self.commitment_tracker = None
        else:
            self.commitment_tracker = None

    def record_decision(
        self,
        decision: str,
        options_considered: List[str],
        chosen_option: str,
        rationale: str,
        context: Optional[str] = None,
        project_id: str = "LFI",
        session_id: Optional[str] = None,
        save_to_memory_ts: bool = True,
        link_to_commitment: bool = False
    ) -> Decision:
        """
        Record a decision made

        Args:
            decision: The decision question/topic
            options_considered: List of options evaluated
            chosen_option: Which option was chosen
            rationale: Why this option was chosen
            context: Additional context
            project_id: Project scope
            session_id: Session where decision was made
            save_to_memory_ts: Also save to memory-ts
            link_to_commitment: Try to link to ea_brain commitment

        Returns:
            Decision object
        """
        if not decision or not chosen_option or not rationale:
            raise ValueError("Decision, chosen option, and rationale required")

        dec = Decision(
            decision=decision,
            options_considered=options_considered,
            chosen_option=chosen_option,
            rationale=rationale,
            context=context,
            project_id=project_id,
            session_id=session_id
        )

        # Try to link to ea_brain commitment
        commitment_id = None
        if link_to_commitment and self.commitment_tracker:
            try:
                # Create commitment in ea_brain
                commitment_id = self.commitment_tracker.record(
                    giver="you",
                    commitment=f"Decision: {chosen_option}",
                    recipient=None,  # Self-decision
                    context=f"{decision}\n\nRationale: {rationale}"
                )
                dec.commitment_id = commitment_id
            except Exception as e:
                print(f"Warning: Failed to link to ea_brain: {e}")

        # Save to intelligence DB
        cursor = self.db.conn.cursor()

        cursor.execute("""
            INSERT INTO decision_journal
            (decision, options_considered, chosen_option, rationale, context, project_id, session_id, decided_at, commitment_id, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision,
            json.dumps(options_considered),
            chosen_option,
            rationale,
            context,
            project_id,
            session_id,
            dec.decided_at,
            commitment_id,
            json.dumps(dec.tags)
        ))

        decision_id = cursor.lastrowid
        self.db.conn.commit()

        # Save to memory-ts
        if save_to_memory_ts:
            try:
                memory_content = f"""Decision: {decision}

Options considered:
{chr(10).join(f"- {opt}" for opt in options_considered)}

Chosen: {chosen_option}

Rationale: {rationale}
"""
                if context:
                    memory_content += f"\nContext: {context}"

                self.memory_client.create(
                    content=memory_content,
                    tags=['#decision', f'#project-{project_id.lower()}'],
                    project_id=project_id,
                    importance=0.7,  # Decisions are important
                    session_id=session_id
                )
            except Exception as e:
                print(f"Warning: Failed to save to memory-ts: {e}")

        return dec

    def track_outcome(
        self,
        decision_id: int,
        outcome: str,
        success: bool,
        update_memory_ts: bool = True
    ) -> Dict:
        """
        Track outcome of a previous decision

        Args:
            decision_id: Database ID of decision
            outcome: What happened
            success: Whether it worked out
            update_memory_ts: Update memory-ts with outcome

        Returns:
            Updated decision dict
        """
        cursor = self.db.conn.cursor()

        # Update decision record
        cursor.execute("""
            UPDATE decision_journal
            SET outcome = ?, outcome_success = ?, outcome_recorded_at = ?
            WHERE id = ?
        """, (outcome, success, datetime.now().isoformat(), decision_id))

        self.db.conn.commit()

        # Fetch updated record
        cursor.execute("SELECT * FROM decision_journal WHERE id = ?", (decision_id,))
        result = cursor.fetchone()

        if not result:
            raise ValueError(f"Decision {decision_id} not found")

        decision_dict = dict(result)

        # Update memory-ts if requested
        if update_memory_ts:
            try:
                outcome_memory = f"""Decision outcome recorded:

Decision: {decision_dict['decision']}
Chosen: {decision_dict['chosen_option']}
Outcome: {outcome}
Success: {"Yes" if success else "No"}

{"✅ This approach worked" if success else "❌ This approach didn't work - learn from it"}
"""
                self.memory_client.create(
                    content=outcome_memory,
                    tags=['#decision-outcome', f'#{"success" if success else "failure"}'],
                    project_id=decision_dict['project_id'],
                    importance=0.8,  # Outcomes are high value learning
                    session_id=decision_dict['session_id']
                )
            except Exception as e:
                print(f"Warning: Failed to save outcome to memory-ts: {e}")

        return decision_dict

    def learn_from_decisions(
        self,
        project_id: Optional[str] = None,
        min_decisions: int = 3
    ) -> Dict:
        """
        Analyze decision patterns

        Args:
            project_id: Optional project filter
            min_decisions: Minimum decisions needed for pattern

        Returns:
            Decision pattern analysis
        """
        cursor = self.db.conn.cursor()

        sql = """
            SELECT * FROM decision_journal
            WHERE outcome IS NOT NULL
        """
        params = []

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)

        cursor.execute(sql, params)
        decisions = [dict(row) for row in cursor.fetchall()]

        if len(decisions) < min_decisions:
            return {
                'total_decisions': len(decisions),
                'insufficient_data': True,
                'min_needed': min_decisions
            }

        # Calculate success rate
        successful = [d for d in decisions if d['outcome_success']]
        failed = [d for d in decisions if not d['outcome_success']]

        # Find patterns in successful vs failed decisions
        success_patterns = {}
        failure_patterns = {}

        for decision in successful:
            chosen = decision['chosen_option']
            success_patterns[chosen] = success_patterns.get(chosen, 0) + 1

        for decision in failed:
            chosen = decision['chosen_option']
            failure_patterns[chosen] = failure_patterns.get(chosen, 0) + 1

        return {
            'total_decisions': len(decisions),
            'successful': len(successful),
            'failed': len(failed),
            'success_rate': len(successful) / len(decisions) if decisions else 0,
            'success_patterns': success_patterns,
            'failure_patterns': failure_patterns,
            'top_successful_approaches': sorted(success_patterns.items(), key=lambda x: x[1], reverse=True)[:5],
            'approaches_to_avoid': sorted(failure_patterns.items(), key=lambda x: x[1], reverse=True)[:5]
        }

    def get_decision(self, decision_id: int) -> Optional[Dict]:
        """Get decision by ID"""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT * FROM decision_journal WHERE id = ?", (decision_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

    def get_recent_decisions(self, days: int = 30, limit: int = 20) -> List[Dict]:
        """Get recent decisions"""
        cursor = self.db.conn.cursor()

        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff.replace(day=cutoff.day - days)

        cursor.execute("""
            SELECT * FROM decision_journal
            WHERE decided_at >= ?
            ORDER BY decided_at DESC
            LIMIT ?
        """, (cutoff.isoformat(), limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_pending_outcomes(self, project_id: Optional[str] = None) -> List[Dict]:
        """Get decisions without recorded outcomes"""
        cursor = self.db.conn.cursor()

        sql = "SELECT * FROM decision_journal WHERE outcome IS NULL"
        params = []

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)

        sql += " ORDER BY decided_at DESC"

        cursor.execute(sql, params)

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        self.db.close()
        if self.commitment_tracker:
            self.commitment_tracker.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close on context exit"""
        self.close()
