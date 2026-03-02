"""Skill proposal engine — analyzes action patterns to propose new skills.

Evaluates recurring action patterns tracked by SkillActionTracker and generates
proposals for new skills when patterns exceed frequency thresholds. Checks against
the existing skill registry to avoid proposing skills that already exist.

Also evaluates frustration patterns from sentiment_patterns to propose skills
that address recurring pain points.

Trigger rules:
- Daily burst: 3+ occurrences in a single day -> confidence 0.6
- Sustained pattern: 7+ distinct days -> confidence 0.7
- Frustration pattern: 5+ occurrences across 3+ sessions -> confidence 0.7
- When both triggers are met, sustained_pattern wins (higher confidence)

Usage:
    from memory_system.wild.skill_proposal_engine import SkillProposalEngine

    engine = SkillProposalEngine()
    proposals = engine.evaluate_patterns()
    for p in proposals:
        print(f"Proposed: {p.proposed_name} ({p.trigger_reason}, conf={p.confidence})")
        engine.create_proposal(p)

    # Frustration-based proposals
    frustration_proposals = engine.evaluate_frustration_patterns()
    for p in frustration_proposals:
        engine.create_proposal(p)
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from memory_system.config import cfg
from memory_system.wild.intelligence_db import IntelligenceDB
from memory_system.wild.skill_action_tracker import SkillActionTracker


DAILY_BURST_THRESHOLD = 3
SUSTAINED_DAYS_THRESHOLD = 7
DAILY_BURST_CONFIDENCE = 0.6
SUSTAINED_CONFIDENCE = 0.7
FRUSTRATION_CONFIDENCE = 0.7
COVERAGE_OVERLAP_THRESHOLD = 0.6

VALID_STATUSES = {"approved", "rejected", "implemented"}


@dataclass
class SkillProposal:
    """A proposed new skill."""
    proposed_name: str
    action_signature: str
    trigger_reason: str  # 'daily_burst', 'sustained_pattern', or 'frustration_pattern'
    confidence: float
    status: str = "pending"  # pending/approved/rejected/implemented
    mapped_pattern_id: Optional[str] = None


@dataclass
class FrustrationAggregate:
    """Aggregated frustration data for a single topic."""
    topic: str
    occurrence_count: int
    session_count: int
    latest_timestamp: str
    sample_evidence: list[str]  # up to 3 sample trigger_words/contexts


class SkillProposalEngine:
    """Analyzes action patterns to propose new skills."""

    def __init__(self, db_path=None, state_path=None):
        self.db = IntelligenceDB(db_path)
        self.tracker = SkillActionTracker(state_path=state_path, db_path=db_path)
        self._migrate_frustration_trigger()

    def evaluate_patterns(self) -> list[SkillProposal]:
        """Evaluate all action patterns and generate proposals.

        Trigger rules:
        - Daily burst: 3+ occurrences in a single day -> confidence starts 0.6
        - Sustained pattern: 7+ distinct days -> confidence starts 0.7

        Before proposing:
        - Check if existing skill already covers it (keyword_overlap > 0.6)
        - Check if proposal already exists (same action_signature, status pending)
        - If covered by existing skill, skip proposal
        """
        patterns = self.tracker.get_patterns()
        if not patterns:
            return []

        proposals: list[SkillProposal] = []

        for pattern in patterns:
            daily = pattern.daily_occurrences
            distinct_days = len(daily)
            max_daily = max(daily.values()) if daily else 0

            # Determine trigger
            is_sustained = distinct_days >= SUSTAINED_DAYS_THRESHOLD
            is_burst = max_daily >= DAILY_BURST_THRESHOLD

            if not is_sustained and not is_burst:
                continue

            # Sustained wins when both triggers met
            if is_sustained:
                trigger_reason = "sustained_pattern"
                confidence = SUSTAINED_CONFIDENCE
            else:
                trigger_reason = "daily_burst"
                confidence = DAILY_BURST_CONFIDENCE

            # Check existing skill coverage
            is_covered, _ = self.check_existing_coverage(pattern.action_signature)
            if is_covered:
                continue

            # Check for existing pending proposal with same action_signature
            if self._has_pending_proposal(pattern.action_signature):
                continue

            proposed_name = self._generate_proposed_name(pattern.canonical_form)

            proposals.append(SkillProposal(
                proposed_name=proposed_name,
                action_signature=pattern.action_signature,
                trigger_reason=trigger_reason,
                confidence=confidence,
                mapped_pattern_id=pattern.id,
            ))

        return proposals

    def keyword_overlap(self, action_signature: str, skill_keywords: list[str]) -> float:
        """Compute keyword overlap between an action signature and a skill's keywords.

        Extracts words from action_signature (lowered, split on spaces),
        compares against skill_keywords (also lowered).
        Returns Jaccard coefficient: |intersection| / |union|.
        Returns 0.0 if both are empty.
        """
        action_words = set(action_signature.lower().split()) if action_signature.strip() else set()
        kw_words = {kw.lower() for kw in skill_keywords} if skill_keywords else set()

        if not action_words and not kw_words:
            return 0.0
        if not action_words or not kw_words:
            return 0.0

        intersection = action_words & kw_words
        union = action_words | kw_words
        return len(intersection) / len(union)

    def check_existing_coverage(self, action_signature: str) -> tuple[bool, Optional[str]]:
        """Check if any existing skill covers this action.

        Checks all skills in skill_registry, computes keyword_overlap.
        Returns (is_covered, skill_name) where is_covered is True if any
        skill has overlap > 0.6.
        """
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT skill_name, keywords FROM skill_registry"
        ).fetchall()

        best_overlap = 0.0
        best_skill: Optional[str] = None

        for row in rows:
            keywords_raw = row["keywords"]
            if keywords_raw is None:
                continue
            try:
                keywords = json.loads(keywords_raw)
            except (json.JSONDecodeError, TypeError):
                continue

            if not isinstance(keywords, list):
                continue

            overlap = self.keyword_overlap(action_signature, keywords)
            if overlap > best_overlap:
                best_overlap = overlap
                best_skill = row["skill_name"]

        if best_overlap > COVERAGE_OVERLAP_THRESHOLD:
            return True, best_skill

        return False, None

    def create_proposal(self, proposal: SkillProposal) -> int:
        """Insert a proposal into skill_proposals table. Returns the row ID."""
        cursor = self.db.conn.cursor()
        cursor.execute(
            "INSERT INTO skill_proposals "
            "(proposed_name, action_signature, trigger_reason, confidence, status, mapped_pattern_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                proposal.proposed_name,
                proposal.action_signature,
                proposal.trigger_reason,
                proposal.confidence,
                proposal.status,
                proposal.mapped_pattern_id,
            ),
        )
        self.db.conn.commit()
        return cursor.lastrowid

    def get_pending_proposals(self) -> list[dict]:
        """Get all proposals with status='pending'."""
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT * FROM skill_proposals WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def update_proposal_status(self, proposal_id: int, status: str) -> bool:
        """Update proposal status. Valid: approved, rejected, implemented.

        Sets resolved_at timestamp when moving out of pending.
        Returns True if found and updated.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )

        now = datetime.now().isoformat()
        cursor = self.db.conn.cursor()
        cursor.execute(
            "UPDATE skill_proposals SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now, proposal_id),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def get_proposal(self, proposal_id: int) -> Optional[dict]:
        """Get a single proposal by ID."""
        cursor = self.db.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM skill_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        return dict(row) if row else None

    def _has_pending_proposal(self, action_signature: str) -> bool:
        """Check if a pending proposal already exists for this action signature."""
        cursor = self.db.conn.cursor()
        row = cursor.execute(
            "SELECT id FROM skill_proposals WHERE action_signature = ? AND status = 'pending'",
            (action_signature,),
        ).fetchone()
        return row is not None

    def _generate_proposed_name(self, canonical_form: str) -> str:
        """Generate a proposed skill name from the canonical form.

        Replaces underscores with hyphens to match skill naming convention.
        Prefix with 'auto-' to indicate it was auto-proposed.
        """
        return f"auto-{canonical_form.replace('_', '-')}"

    # --- Frustration-to-skill pipeline ---

    def _migrate_frustration_trigger(self):
        """Migrate skill_proposals table to allow 'frustration_pattern' trigger_reason.

        SQLite doesn't support ALTER TABLE for CHECK constraints, so we recreate
        the table if the constraint doesn't already include frustration_pattern.
        """
        cursor = self.db.conn.cursor()
        # Check current table schema
        row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='skill_proposals'"
        ).fetchone()
        if row is None:
            return
        schema_sql = row[0] if isinstance(row, (tuple, list)) else row["sql"]
        if "frustration_pattern" in schema_sql:
            return  # Already migrated

        cursor.execute("ALTER TABLE skill_proposals RENAME TO skill_proposals_old")
        cursor.execute("""
            CREATE TABLE skill_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposed_name TEXT NOT NULL,
                action_signature TEXT NOT NULL,
                trigger_reason TEXT NOT NULL CHECK(trigger_reason IN ('daily_burst', 'sustained_pattern', 'frustration_pattern')),
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'implemented')),
                mapped_pattern_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO skill_proposals (id, proposed_name, action_signature, trigger_reason,
                                        confidence, status, mapped_pattern_id, created_at, resolved_at)
            SELECT id, proposed_name, action_signature, trigger_reason,
                   confidence, status, mapped_pattern_id, created_at, resolved_at
            FROM skill_proposals_old
        """)
        cursor.execute("DROP TABLE skill_proposals_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_proposals_status ON skill_proposals(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_proposals_name ON skill_proposals(proposed_name)")
        self.db.conn.commit()

    def evaluate_frustration_patterns(
        self, min_occurrences: int = 5, min_sessions: int = 3
    ) -> list[SkillProposal]:
        """Evaluate frustration patterns and propose skills.

        1. Aggregate frustration topics from sentiment_patterns table
        2. Filter by thresholds (min_occurrences AND min_sessions)
        3. Check for existing proposals (dedup)
        4. Create SkillProposals with trigger_reason='frustration_pattern'
        """
        aggregated = self._aggregate_frustration_topics()
        proposals: list[SkillProposal] = []

        for topic, agg in aggregated.items():
            if agg.occurrence_count < min_occurrences:
                continue
            if agg.session_count < min_sessions:
                continue
            if self._has_frustration_proposal(topic):
                continue

            action_sig = f"frustration:{topic}"
            proposed_name = f"auto-fix-{topic.replace(' ', '-').lower()}"

            proposals.append(SkillProposal(
                proposed_name=proposed_name,
                action_signature=action_sig,
                trigger_reason="frustration_pattern",
                confidence=FRUSTRATION_CONFIDENCE,
            ))

        return proposals

    def _aggregate_frustration_topics(self, days_back: int = 90) -> dict[str, FrustrationAggregate]:
        """Aggregate frustration records by topic/trigger_words.

        Queries sentiment_patterns WHERE sentiment='frustrated'.
        Groups by trigger_words (or context if trigger_words is NULL).
        Returns dict mapping topic -> FrustrationAggregate.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        cursor = self.db.conn.cursor()
        rows = cursor.execute(
            "SELECT session_id, timestamp, trigger_words, context "
            "FROM sentiment_patterns "
            "WHERE sentiment = 'frustrated' AND timestamp >= ? "
            "ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()

        topics: dict[str, dict] = {}
        for row in rows:
            topic = row["trigger_words"] or row["context"]
            if not topic:
                continue

            if topic not in topics:
                topics[topic] = {
                    "sessions": set(),
                    "count": 0,
                    "latest": row["timestamp"],
                    "evidence": [],
                }

            topics[topic]["sessions"].add(row["session_id"])
            topics[topic]["count"] += 1

            evidence_item = row["context"] or row["trigger_words"]
            if evidence_item and len(topics[topic]["evidence"]) < 3:
                topics[topic]["evidence"].append(evidence_item)

        return {
            topic: FrustrationAggregate(
                topic=topic,
                occurrence_count=data["count"],
                session_count=len(data["sessions"]),
                latest_timestamp=data["latest"],
                sample_evidence=data["evidence"],
            )
            for topic, data in topics.items()
        }

    def _has_frustration_proposal(self, topic: str) -> bool:
        """Check if a pending proposal already exists for this frustration topic.

        Uses action_signature matching with 'frustration:' prefix.
        """
        action_sig = f"frustration:{topic}"
        return self._has_pending_proposal(action_sig)
