"""Memory interview — periodic review of stale, contradicted, and unrated memories.

Generates interview questions from three sources:
1. Stale high-importance memories (not updated in 90+ days)
2. Low-confidence / contradicted memories
3. Un-rated decisions from the decision journal

Processes user responses to confirm, archive, update, or rate memories.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import uuid

from .memory_ts_client import MemoryTSClient, Memory
from .intelligence_db import IntelligenceDB


@dataclass
class InterviewQuestion:
    """A single interview question for memory review."""
    id: str                    # Unique question ID
    category: str              # 'stale_review' | 'contradiction' | 'decision_rating'
    question_text: str
    context: str               # The memory content or decision text
    memory_ids: List[str]      # Related memory/decision IDs
    created_at: str


class MemoryInterviewer:
    """Generates and processes memory interview sessions."""

    STALE_DAYS = 90            # Memories not updated in 90 days
    MIN_IMPORTANCE = 0.5       # Only review memories worth keeping
    MAX_QUESTIONS = 5

    def __init__(self, memory_dir: Optional[Path] = None, db_path: Optional[str] = None):
        """Initialize interviewer with memory storage and intelligence DB.

        Args:
            memory_dir: Path to memory files directory (for MemoryTSClient)
            db_path: Path to intelligence.db (for IntelligenceDB)
        """
        self.client = MemoryTSClient(memory_dir=memory_dir)
        self.db = IntelligenceDB(db_path=db_path)
        self._pending_questions: Dict[str, InterviewQuestion] = {}

    def generate_interview(self) -> List[InterviewQuestion]:
        """Generate up to MAX_QUESTIONS interview questions from 3 sources.

        Allocation target: 2 stale, 2 contradictions, 1 decision.
        If any category has 0 candidates, redistribute slots to others.

        Returns:
            List of InterviewQuestion (up to MAX_QUESTIONS)
        """
        all_memories = self.client.list()
        stale = self._get_stale_memories(all_memories)
        contradicted = self._get_contradicted_memories(all_memories)
        unrated = self._get_unrated_decisions()

        # Determine slot allocation
        slots = self._allocate_slots(
            len(stale), len(contradicted), len(unrated)
        )

        questions: List[InterviewQuestion] = []

        # Build stale review questions
        for memory in stale[:slots['stale']]:
            created_date = self._format_date(memory.created)
            q = InterviewQuestion(
                id=str(uuid.uuid4()),
                category='stale_review',
                question_text=f"You noted '{self._truncate(memory.content)}' on {created_date}. Is this still true?",
                context=memory.content,
                memory_ids=[memory.id],
                created_at=datetime.now().isoformat(),
            )
            questions.append(q)
            self._pending_questions[q.id] = q

        # Build contradiction questions
        for memory in contradicted[:slots['contradiction']]:
            q = InterviewQuestion(
                id=str(uuid.uuid4()),
                category='contradiction',
                question_text=f"This memory has been contradicted: '{self._truncate(memory.content)}'. Should we keep, update, or archive it?",
                context=memory.content,
                memory_ids=[memory.id],
                created_at=datetime.now().isoformat(),
            )
            questions.append(q)
            self._pending_questions[q.id] = q

        # Build decision rating questions
        for decision in unrated[:slots['decision']]:
            decided_date = self._format_date(decision['decided_at'])
            q = InterviewQuestion(
                id=str(uuid.uuid4()),
                category='decision_rating',
                question_text=f"On {decided_date} you decided: '{self._truncate(decision['decision'])}'. What was the outcome?",
                context=decision['decision'],
                memory_ids=[str(decision['id'])],
                created_at=datetime.now().isoformat(),
            )
            questions.append(q)
            self._pending_questions[q.id] = q

        return questions[:self.MAX_QUESTIONS]

    def process_response(self, question_id: str, response: str) -> Dict:
        """Process a user's response to an interview question.

        For stale_review:
          - "yes"/"still true" -> confirm (update timestamp)
          - "no"/"outdated" -> archive the memory
          - Other -> update the memory content with the new text

        For contradiction:
          - "keep" -> confirm
          - "archive"/"remove" -> archive the memory
          - Other -> update content

        For decision_rating:
          - Extract outcome sentiment and update decision_journal

        Args:
            question_id: ID of the question being answered
            response: User's text response

        Returns:
            Dict with 'action', 'memory_id', 'details'
        """
        question = self._pending_questions.get(question_id)
        if question is None:
            return {'action': 'error', 'memory_id': '', 'details': 'Question not found'}

        response_lower = response.strip().lower()
        memory_id = question.memory_ids[0] if question.memory_ids else ''

        if question.category == 'stale_review':
            return self._process_stale_response(memory_id, response_lower, response)

        elif question.category == 'contradiction':
            return self._process_contradiction_response(memory_id, response_lower, response)

        elif question.category == 'decision_rating':
            return self._process_decision_response(memory_id, response_lower, response)

        return {'action': 'error', 'memory_id': memory_id, 'details': 'Unknown category'}

    def save_interview(self, questions: List[InterviewQuestion]) -> Path:
        """Write interview to {memory_dir}/interviews/YYYY-MM-DD.md

        Args:
            questions: List of interview questions to save

        Returns:
            Path to the saved interview file
        """
        interviews_dir = self.client.memory_dir / "interviews"
        interviews_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        filepath = interviews_dir / f"{today}.md"

        lines = [
            f"# Memory interview - {today}",
            "",
            f"Generated: {datetime.now().isoformat()}",
            f"Questions: {len(questions)}",
            "",
        ]

        for i, q in enumerate(questions, 1):
            lines.append(f"## Question {i} [{q.category}]")
            lines.append("")
            lines.append(q.question_text)
            lines.append("")
            lines.append(f"Context: {q.context}")
            lines.append(f"Memory IDs: {', '.join(q.memory_ids)}")
            lines.append("")

        filepath.write_text("\n".join(lines))
        return filepath

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_stale_memories(self, memories: Optional[List[Memory]] = None) -> List[Memory]:
        """Get memories not updated in STALE_DAYS with importance >= MIN_IMPORTANCE.

        Args:
            memories: Pre-fetched memory list. If None, fetches from disk.
        """
        cutoff = datetime.now() - timedelta(days=self.STALE_DAYS)
        if memories is None:
            memories = self.client.list()
        stale = []

        for m in memories:
            if m.status != 'active':
                continue
            if m.importance < self.MIN_IMPORTANCE:
                continue

            updated_dt = self._parse_date(m.updated)
            if updated_dt is not None and updated_dt < cutoff:
                stale.append(m)

        # Sort by oldest first
        stale.sort(key=lambda m: self._parse_date(m.updated) or datetime.min)
        return stale

    def _get_contradicted_memories(self, memories: Optional[List[Memory]] = None) -> List[Memory]:
        """Get memories with confidence_score < 0.5 (contradicted or uncertain).

        Args:
            memories: Pre-fetched memory list. If None, fetches from disk.
        """
        if memories is None:
            memories = self.client.list()
        contradicted = []

        for m in memories:
            if m.status != 'active':
                continue
            if m.confidence_score < 0.5:
                contradicted.append(m)

        # Sort by lowest confidence first
        contradicted.sort(key=lambda m: m.confidence_score)
        return contradicted

    def _get_unrated_decisions(self) -> List[Dict]:
        """Get decisions from decision_journal where outcome IS NULL."""
        cursor = self.db.conn.execute(
            "SELECT id, decision, options_considered, chosen_option, rationale, "
            "context, project_id, session_id, decided_at "
            "FROM decision_journal WHERE outcome IS NULL "
            "ORDER BY decided_at ASC"
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _process_stale_response(self, memory_id: str, response_lower: str, response_raw: str) -> Dict:
        """Process response to a stale memory review question."""
        if response_lower in ('yes', 'still true', 'y', 'true'):
            # Confirm: update timestamp to mark as reviewed
            try:
                self.client.update(memory_id)  # Updates timestamp
                return {
                    'action': 'confirmed',
                    'memory_id': memory_id,
                    'details': 'Memory confirmed as still relevant, timestamp updated',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

        elif response_lower in ('no', 'outdated', 'n', 'false'):
            # Archive
            try:
                self.client.archive(memory_id, reason='user_reviewed_stale')
                return {
                    'action': 'archived',
                    'memory_id': memory_id,
                    'details': 'Memory archived as outdated',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

        else:
            # Update with new content
            try:
                self.client.update(memory_id, content=response_raw.strip())
                return {
                    'action': 'updated',
                    'memory_id': memory_id,
                    'details': f'Memory content updated to: {response_raw.strip()}',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

    def _process_contradiction_response(self, memory_id: str, response_lower: str, response_raw: str) -> Dict:
        """Process response to a contradiction review question."""
        if response_lower in ('keep', 'confirm', 'yes'):
            try:
                self.client.update(memory_id)  # Confirm by touching timestamp
                return {
                    'action': 'confirmed',
                    'memory_id': memory_id,
                    'details': 'Contradicted memory confirmed as correct',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

        elif response_lower in ('archive', 'remove', 'delete'):
            try:
                self.client.archive(memory_id, reason='user_resolved_contradiction')
                return {
                    'action': 'archived',
                    'memory_id': memory_id,
                    'details': 'Contradicted memory archived',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

        else:
            try:
                self.client.update(memory_id, content=response_raw.strip())
                return {
                    'action': 'updated',
                    'memory_id': memory_id,
                    'details': f'Memory content updated to: {response_raw.strip()}',
                }
            except Exception as e:
                return {'action': 'error', 'memory_id': memory_id, 'details': str(e)}

    def _process_decision_response(self, decision_id: str, response_lower: str, response_raw: str) -> Dict:
        """Process response to a decision rating question."""
        # Determine outcome success from response
        positive_signals = ('good', 'great', 'success', 'positive', 'worked', 'right call', 'yes')
        negative_signals = ('bad', 'wrong', 'failure', 'negative', 'mistake', 'regret', 'no')

        outcome_success = None
        for signal in positive_signals:
            if signal in response_lower:
                outcome_success = True
                break
        if outcome_success is None:
            for signal in negative_signals:
                if signal in response_lower:
                    outcome_success = False
                    break

        try:
            self.db.conn.execute(
                "UPDATE decision_journal SET outcome = ?, outcome_success = ?, "
                "outcome_recorded_at = ? WHERE id = ?",
                (response_raw.strip(), outcome_success, datetime.now().isoformat(), int(decision_id))
            )
            self.db.conn.commit()
            return {
                'action': 'rated',
                'memory_id': decision_id,
                'details': f'Decision outcome recorded: {response_raw.strip()}',
            }
        except Exception as e:
            return {'action': 'error', 'memory_id': decision_id, 'details': str(e)}

    def _allocate_slots(self, n_stale: int, n_contradicted: int, n_decisions: int) -> Dict[str, int]:
        """Allocate question slots across categories.

        Target: 2 stale, 2 contradictions, 1 decision.
        Redistributes empty category slots to others.
        """
        targets = {'stale': 2, 'contradiction': 2, 'decision': 1}
        available = {'stale': n_stale, 'contradiction': n_contradicted, 'decision': n_decisions}

        # First pass: cap at available
        allocated = {}
        surplus = 0
        for cat in ('stale', 'contradiction', 'decision'):
            actual = min(targets[cat], available[cat])
            allocated[cat] = actual
            surplus += targets[cat] - actual

        # Second pass: distribute surplus to categories that have more candidates
        if surplus > 0:
            # Priority order for redistribution
            for cat in ('stale', 'contradiction', 'decision'):
                room = available[cat] - allocated[cat]
                if room > 0 and surplus > 0:
                    add = min(room, surplus)
                    allocated[cat] += add
                    surplus -= add

        return allocated

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date from various formats (ISO, epoch ms, epoch s)."""
        if not date_str:
            return None
        try:
            # Try ISO format
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
        try:
            ts = float(date_str)
            if ts > 1e12:
                # Epoch milliseconds
                return datetime.fromtimestamp(ts / 1000)
            else:
                # Epoch seconds
                return datetime.fromtimestamp(ts)
        except (ValueError, TypeError):
            return None

    def _format_date(self, date_str: str) -> str:
        """Format a date string for display."""
        dt = self._parse_date(date_str)
        if dt:
            return dt.strftime("%Y-%m-%d")
        return "unknown date"

    def _truncate(self, text: str, max_len: int = 100) -> str:
        """Truncate text for question display."""
        text = text.replace('\n', ' ').strip()
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."
