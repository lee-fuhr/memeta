"""Skill self-improver — captures invocation outcomes, accumulates learnings, proposes SKILL.md refinements.

Tracks how skills perform in real sessions, identifies patterns of success and failure,
and generates evidence-based proposals to improve skill documentation.

Usage:
    from memory_system.wild.skill_self_improver import SkillSelfImprover

    improver = SkillSelfImprover()

    # Record an outcome
    improver.record_outcome("test-skill", "session-123", "success", context_snippet="worked well")

    # Assess outcomes from session messages
    assessments = improver.assess_session_outcomes("session-123", messages)

    # Extract learnings from accumulated outcomes
    improver.run_learning_extraction()

    # Generate refinement proposals
    improver.run_proposal_generation()

    # Get health summary
    health = improver.get_skill_health("test-skill")
"""

import json
import logging
import difflib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from memory_system.config import cfg
from memory_system.wild.intelligence_db import IntelligenceDB

logger = logging.getLogger(__name__)

VALID_OUTCOMES = ("success", "partial", "failure", "unknown")

VALID_LEARNING_TYPES = (
    "common_mistake", "best_practice", "usage_pattern",
    "edge_case", "workaround", "context_tip",
)

# Thresholds for promoting learnings to proposals
PROPOSAL_THRESHOLDS = {
    "common_mistake": {"min_evidence": 3, "min_confidence": 0.6},
    "best_practice": {"min_evidence": 5, "min_confidence": 0.7},
    "usage_pattern": {"min_evidence": 5, "min_confidence": 0.7},
    "edge_case": {"min_evidence": 2, "min_confidence": 0.5},
    "workaround": {"min_evidence": 2, "min_confidence": 0.5},
    "context_tip": {"min_evidence": 3, "min_confidence": 0.6},
}

# Mapping from learning type to proposal type
LEARNING_TO_PROPOSAL = {
    "common_mistake": "add_mistake",
    "best_practice": "add_best_practice",
    "usage_pattern": "update_when_to_use",
    "edge_case": "add_edge_case",
    "workaround": "add_workaround",
    "context_tip": "refine_content",
}

# Signals for session assessment
FAILURE_SIGNALS = [
    "error", "failed", "traceback", "exception", "broken",
    "doesn't work", "not working", "bug", "issue",
]

USER_CORRECTION_SIGNALS = [
    "no", "wrong", "actually no", "that's not right",
    "incorrect", "not what i", "try again",
]

SUCCESS_SIGNALS = [
    "done", "looks good", "perfect", "thanks", "great",
    "that works", "nice", "exactly",
]


class SkillSelfImprover:
    """Captures skill invocation outcomes, accumulates learnings, and proposes SKILL.md refinements."""

    def __init__(self, db_path=None, skills_dir=None):
        self.db = IntelligenceDB(db_path or cfg.intelligence_db_path)
        self.skills_dir = Path(skills_dir) if skills_dir else cfg.skills_dir

    # ── Outcome capture ──────────────────────────────────────────────────

    def record_outcome(
        self,
        skill_name: str,
        session_id: str,
        outcome: str,
        context_snippet: Optional[str] = None,
        args_used: Optional[str] = None,
        outcome_signals: Optional[dict] = None,
    ) -> int:
        """Record a skill invocation outcome. Returns the row ID."""
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome '{outcome}'. Must be one of {VALID_OUTCOMES}")

        signals_json = json.dumps(outcome_signals) if outcome_signals else None
        args_json = json.dumps(args_used) if isinstance(args_used, dict) else args_used

        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT INTO skill_invocation_outcomes
            (skill_name, session_id, invoked_at, outcome, outcome_signals, context_snippet, args_used, assessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill_name, session_id, datetime.now().isoformat(),
            outcome, signals_json, context_snippet, args_json,
            datetime.now().isoformat(),
        ))
        self.db.conn.commit()
        return cursor.lastrowid

    def _load_jsonl_messages(self, session_id: str) -> list:
        """Load all messages from the JSONL session file.

        Reads ~/.claude/projects/-Users-lee-CC/{session_id}.jsonl.
        Preserves pre-compaction messages that are lost from in-memory session_messages.
        Filters out tool_result-only messages and compaction summary strings.
        """
        jsonl_path = (
            Path.home() / ".claude" / "projects" / "-Users-lee-CC" / f"{session_id}.jsonl"
        )
        if not jsonl_path.exists():
            return []

        messages = []
        try:
            with jsonl_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        role = msg.get("role", "")
                        if role not in ("user", "assistant", "human"):
                            continue
                        content = msg.get("content", "")
                        # Skip tool_result-only messages (no useful signal for outcome detection)
                        if isinstance(content, list):
                            has_text_or_skill = any(
                                isinstance(b, dict) and b.get("type") in ("text", "tool_use")
                                for b in content
                            )
                            if not has_text_or_skill:
                                continue
                        # Skip compaction summary strings
                        if isinstance(content, str) and "compacted" in content.lower():
                            continue
                        messages.append(msg)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            return []

        return messages

    def assess_session_outcomes(self, session_id: str, session_messages: list) -> list:
        """Scan session messages for skill invocations and assess their outcomes.

        Reads from the JSONL file directly to capture pre-compaction skill invocations.
        Falls back to session_messages if the JSONL file is unavailable.
        """
        # JSONL takes precedence — preserves full history including pre-compaction messages
        jsonl_messages = self._load_jsonl_messages(session_id)
        all_messages = jsonl_messages if jsonl_messages else session_messages
        assessment_method = "jsonl_scan" if jsonl_messages else "session_scan"

        assessments = []

        for i, msg in enumerate(all_messages):
            # Find Skill tool_use blocks
            skill_invocations = self._extract_skill_invocations(msg)
            if not skill_invocations:
                continue

            for skill_name, args in skill_invocations:
                outcome = self._assess_outcome(all_messages, i)
                context = self._extract_context(all_messages, i)

                row_id = self.record_outcome(
                    skill_name=skill_name,
                    session_id=session_id,
                    outcome=outcome,
                    context_snippet=context,
                    args_used=args,
                    outcome_signals={"assessment_method": assessment_method},
                )

                assessments.append({
                    "id": row_id,
                    "skill_name": skill_name,
                    "outcome": outcome,
                    "context_snippet": context,
                })

        return assessments

    def _extract_skill_invocations(self, message: dict) -> list:
        """Extract skill invocations from a message."""
        invocations = []
        content = message.get("content", [])
        if isinstance(content, str):
            return invocations

        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                inp = block.get("input", {})
                skill_name = inp.get("skill", "")
                args = inp.get("args", "")
                if skill_name:
                    invocations.append((skill_name, args))
        return invocations

    def _assess_outcome(self, messages: list, invocation_idx: int) -> str:
        """Assess outcome based on messages following the invocation."""
        following = messages[invocation_idx + 1: invocation_idx + 4]

        if not following:
            return "unknown"

        for msg in following:
            text = self._get_message_text(msg).lower()
            role = msg.get("role", "")

            # Check for user correction
            if role == "user":
                for signal in USER_CORRECTION_SIGNALS:
                    if signal in text:
                        return "failure"

            # Check for error signals in assistant messages
            if role == "assistant":
                for signal in FAILURE_SIGNALS:
                    if signal in text:
                        return "failure"

            # Check for same skill re-invoked (partial)
            if role == "assistant":
                reinvocations = self._extract_skill_invocations(msg)
                if reinvocations:
                    orig_skills = self._extract_skill_invocations(messages[invocation_idx])
                    orig_names = {s[0] for s in orig_skills}
                    for rname, _ in reinvocations:
                        if rname in orig_names:
                            return "partial"

        # Check for success signals
        for msg in following:
            text = self._get_message_text(msg).lower()
            role = msg.get("role", "")
            if role == "user":
                for signal in SUCCESS_SIGNALS:
                    if signal in text:
                        return "success"
            if role == "assistant":
                for signal in SUCCESS_SIGNALS:
                    if signal in text:
                        return "success"

        return "unknown"

    def _get_message_text(self, message: dict) -> str:
        """Extract plain text from a message."""
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts)

    def _extract_context(self, messages: list, invocation_idx: int) -> str:
        """Extract context snippet from around the invocation."""
        snippets = []
        for msg in messages[max(0, invocation_idx - 1): invocation_idx + 3]:
            text = self._get_message_text(msg)
            if text:
                snippets.append(text[:200])
        return " | ".join(snippets)[:500]

    def compute_success_rate(self, skill_name: str, days: int = 30) -> dict:
        """Compute success rate for a skill within date range."""
        cursor = self.db.conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        cursor.execute("""
            SELECT outcome, COUNT(*) as cnt
            FROM skill_invocation_outcomes
            WHERE skill_name = ? AND invoked_at >= ?
            GROUP BY outcome
        """, (skill_name, cutoff))

        counts = {"success": 0, "failure": 0, "partial": 0, "unknown": 0}
        for row in cursor.fetchall():
            counts[row["outcome"]] = row["cnt"]

        total = sum(counts.values())
        success_rate = counts["success"] / total if total > 0 else 0.0

        # Trend: compare last half vs first half
        midpoint = (datetime.now() - timedelta(days=days // 2)).isoformat()

        cursor.execute("""
            SELECT outcome FROM skill_invocation_outcomes
            WHERE skill_name = ? AND invoked_at >= ? AND invoked_at < ?
        """, (skill_name, cutoff, midpoint))
        first_half = [row["outcome"] for row in cursor.fetchall()]

        cursor.execute("""
            SELECT outcome FROM skill_invocation_outcomes
            WHERE skill_name = ? AND invoked_at >= ?
        """, (skill_name, midpoint))
        second_half = [row["outcome"] for row in cursor.fetchall()]

        first_rate = sum(1 for o in first_half if o == "success") / len(first_half) if first_half else 0.0
        second_rate = sum(1 for o in second_half if o == "success") / len(second_half) if second_half else 0.0

        diff = second_rate - first_rate
        if diff > 0.1:
            trend = "improving"
        elif diff < -0.1:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "total": total,
            "success": counts["success"],
            "failure": counts["failure"],
            "partial": counts["partial"],
            "unknown": counts["unknown"],
            "success_rate": round(success_rate, 3),
            "trend": trend,
        }

    # ── Learning accumulation ────────────────────────────────────────────

    def record_learning(
        self,
        skill_name: str,
        learning_type: str,
        content: str,
        session_id: Optional[str] = None,
        confidence: float = 0.5,
    ) -> int:
        """Record a learning, deduplicating by Jaccard similarity > 0.7."""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT id, content, evidence_count, confidence, source_sessions
            FROM skill_learnings
            WHERE skill_name = ? AND learning_type = ? AND status = 'active'
        """, (skill_name, learning_type))

        for row in cursor.fetchall():
            similarity = self._compute_similarity(content, row["content"])
            if similarity > 0.7:
                # Dedup: merge into existing learning
                new_evidence = row["evidence_count"] + 1
                avg_confidence = (row["confidence"] + confidence) / 2.0
                existing_sessions = json.loads(row["source_sessions"]) if row["source_sessions"] else []
                if session_id and session_id not in existing_sessions:
                    existing_sessions.append(session_id)

                cursor.execute("""
                    UPDATE skill_learnings
                    SET evidence_count = ?, last_observed = ?, confidence = ?, source_sessions = ?
                    WHERE id = ?
                """, (
                    new_evidence, datetime.now().isoformat(),
                    round(avg_confidence, 3),
                    json.dumps(existing_sessions),
                    row["id"],
                ))
                self.db.conn.commit()
                return row["id"]

        # No dedup match — insert new
        sessions_json = json.dumps([session_id]) if session_id else json.dumps([])
        cursor.execute("""
            INSERT INTO skill_learnings
            (skill_name, learning_type, content, evidence_count, source_sessions,
             first_observed, last_observed, confidence, status)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'active')
        """, (
            skill_name, learning_type, content, sessions_json,
            datetime.now().isoformat(), datetime.now().isoformat(),
            round(confidence, 3),
        ))
        self.db.conn.commit()
        return cursor.lastrowid

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        """Jaccard similarity on lowercased word tokens."""
        tokens_a = set(text_a.lower().split())
        tokens_b = set(text_b.lower().split())
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def extract_learnings_from_outcomes(self, skill_name: str) -> list:
        """Extract learnings from recent outcomes for a skill."""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT * FROM skill_invocation_outcomes
            WHERE skill_name = ?
            ORDER BY invoked_at DESC
            LIMIT 100
        """, (skill_name,))

        outcomes = [dict(row) for row in cursor.fetchall()]
        if not outcomes:
            return []

        learnings = []

        # Cluster failures by context
        failures = [o for o in outcomes if o["outcome"] == "failure"]
        if len(failures) >= 2:
            clusters = self._cluster_by_context(failures)
            for cluster in clusters:
                if len(cluster) >= 2:
                    representative = cluster[0].get("context_snippet", "")
                    if representative:
                        content = f"Common failure pattern: {representative[:200]}"
                        lid = self.record_learning(skill_name, "common_mistake", content)
                        learnings.append({"id": lid, "type": "common_mistake", "content": content})

        # Cluster successes
        successes = [o for o in outcomes if o["outcome"] == "success"]
        if len(successes) >= 2:
            clusters = self._cluster_by_context(successes)
            for cluster in clusters:
                if len(cluster) >= 2:
                    representative = cluster[0].get("context_snippet", "")
                    if representative:
                        content = f"Successful usage pattern: {representative[:200]}"
                        lid = self.record_learning(skill_name, "best_practice", content)
                        learnings.append({"id": lid, "type": "best_practice", "content": content})

        # Detect consistent args patterns with high success
        args_success = {}
        for o in outcomes:
            if o.get("args_used") and o["outcome"] == "success":
                args_key = o["args_used"]
                args_success.setdefault(args_key, 0)
                args_success[args_key] += 1

        for args_key, count in args_success.items():
            if count >= 3:
                content = f"Consistently successful with args: {args_key[:200]}"
                lid = self.record_learning(skill_name, "usage_pattern", content)
                learnings.append({"id": lid, "type": "usage_pattern", "content": content})

        return learnings

    def _cluster_by_context(self, outcomes: list) -> list:
        """Cluster outcomes by context_snippet similarity."""
        if not outcomes:
            return []

        clusters = []
        used = set()

        for i, o1 in enumerate(outcomes):
            if i in used:
                continue
            cluster = [o1]
            used.add(i)
            ctx1 = o1.get("context_snippet", "") or ""

            for j, o2 in enumerate(outcomes):
                if j in used:
                    continue
                ctx2 = o2.get("context_snippet", "") or ""
                if ctx1 and ctx2 and self._compute_similarity(ctx1, ctx2) > 0.4:
                    cluster.append(o2)
                    used.add(j)

            clusters.append(cluster)

        return clusters

    def run_learning_extraction(self) -> dict:
        """Run learning extraction for all skills with outcomes."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT DISTINCT skill_name FROM skill_invocation_outcomes")
        skill_names = [row["skill_name"] for row in cursor.fetchall()]

        total_learnings = 0
        for name in skill_names:
            learnings = self.extract_learnings_from_outcomes(name)
            total_learnings += len(learnings)

        return {
            "skills_processed": len(skill_names),
            "learnings_created": total_learnings,
        }

    # ── SKILL.md refinement ──────────────────────────────────────────────

    def generate_refinement_proposals(self, skill_name: str) -> list:
        """Generate refinement proposals for a skill based on active learnings."""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT * FROM skill_learnings
            WHERE skill_name = ? AND status = 'active'
        """, (skill_name,))
        learnings = [dict(row) for row in cursor.fetchall()]

        if not learnings:
            return []

        # Read existing SKILL.md if available
        skill_md_content = self._read_skill_md(skill_name)

        # Get pending proposals to check for duplicates
        pending = self.get_pending_proposals(skill_name)
        pending_contents = [p["proposed_content"] for p in pending]

        proposals = []

        for learning in learnings:
            lt = learning["learning_type"]
            thresholds = PROPOSAL_THRESHOLDS.get(lt)
            if not thresholds:
                continue

            # Check thresholds
            if learning["evidence_count"] < thresholds["min_evidence"]:
                continue
            if learning["confidence"] < thresholds["min_confidence"]:
                continue

            # Check if already in SKILL.md
            if skill_md_content and self._compute_similarity(learning["content"], skill_md_content) > 0.6:
                continue

            # Check duplicate pending proposals
            is_dup = False
            for pc in pending_contents:
                if self._compute_similarity(learning["content"], pc) > 0.6:
                    is_dup = True
                    break
            if is_dup:
                continue

            proposal_type = LEARNING_TO_PROPOSAL.get(lt, "refine_content")
            section = self._section_for_type(proposal_type)

            proposal = {
                "skill_name": skill_name,
                "proposal_type": proposal_type,
                "section_target": section,
                "proposed_content": learning["content"],
                "rationale": f"Based on {learning['evidence_count']} observations with {learning['confidence']:.1%} confidence",
                "supporting_learning_ids": json.dumps([learning["id"]]),
                "evidence_strength": learning["confidence"] * min(learning["evidence_count"] / 10, 1.0),
            }
            proposals.append(proposal)

        return proposals

    def _section_for_type(self, proposal_type: str) -> str:
        """Map proposal type to SKILL.md section."""
        return {
            "add_mistake": "## Common mistakes",
            "add_best_practice": "## Best practices",
            "update_when_to_use": "## When to use",
            "add_edge_case": "## Edge cases",
            "add_workaround": "## Workarounds",
            "refine_content": "## Notes",
        }.get(proposal_type, "## Notes")

    def _read_skill_md(self, skill_name: str) -> str:
        """Read SKILL.md content for a skill. Returns empty string if not found."""
        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def create_proposal(self, proposal_dict: dict) -> int:
        """Insert a refinement proposal into the database. Returns row ID."""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT INTO skill_refinement_proposals
            (skill_name, proposal_type, section_target, proposed_content,
             rationale, supporting_learning_ids, evidence_strength, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            proposal_dict["skill_name"],
            proposal_dict["proposal_type"],
            proposal_dict.get("section_target"),
            proposal_dict["proposed_content"],
            proposal_dict.get("rationale"),
            proposal_dict.get("supporting_learning_ids"),
            proposal_dict.get("evidence_strength", 0.0),
            datetime.now().isoformat(),
        ))
        self.db.conn.commit()
        return cursor.lastrowid

    def get_pending_proposals(self, skill_name: Optional[str] = None) -> list:
        """Get pending refinement proposals, optionally filtered by skill."""
        cursor = self.db.conn.cursor()
        if skill_name:
            cursor.execute("""
                SELECT * FROM skill_refinement_proposals
                WHERE status = 'pending' AND skill_name = ?
                ORDER BY evidence_strength DESC
            """, (skill_name,))
        else:
            cursor.execute("""
                SELECT * FROM skill_refinement_proposals
                WHERE status = 'pending'
                ORDER BY evidence_strength DESC
            """)
        return [dict(row) for row in cursor.fetchall()]

    def update_proposal_status(self, proposal_id: int, status: str) -> bool:
        """Update a proposal's status. Sets resolved_at for terminal statuses."""
        cursor = self.db.conn.cursor()
        resolved_at = datetime.now().isoformat() if status in ("approved", "rejected", "applied") else None
        cursor.execute("""
            UPDATE skill_refinement_proposals
            SET status = ?, resolved_at = ?
            WHERE id = ?
        """, (status, resolved_at, proposal_id))
        self.db.conn.commit()
        return cursor.rowcount > 0

    def apply_proposal(self, proposal_id: int) -> str:
        """Generate a unified diff showing where proposed content would be added to SKILL.md.

        Does NOT write to disk. Returns the diff string.
        """
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT * FROM skill_refinement_proposals WHERE id = ?", (proposal_id,))
        row = cursor.fetchone()
        if not row:
            return ""

        proposal = dict(row)
        skill_md = self._read_skill_md(proposal["skill_name"])
        if not skill_md:
            # No SKILL.md — show what would be created
            new_content = f"{proposal.get('section_target', '## Notes')}\n\n- {proposal['proposed_content']}\n"
            return "\n".join(difflib.unified_diff(
                [], new_content.splitlines(keepends=True),
                fromfile="SKILL.md (new)",
                tofile="SKILL.md (proposed)",
            ))

        # Find the section and add content
        lines = skill_md.splitlines(keepends=True)
        section = proposal.get("section_target", "## Notes")
        new_line = f"- {proposal['proposed_content']}\n"

        new_lines = list(lines)
        insert_idx = None

        for i, line in enumerate(lines):
            if line.strip().lower() == section.lower():
                # Find end of section (next heading or EOF)
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("## "):
                        insert_idx = j
                        break
                if insert_idx is None:
                    insert_idx = len(lines)
                break

        if insert_idx is not None:
            new_lines.insert(insert_idx, new_line)
        else:
            # Section not found — append at end
            new_lines.append(f"\n{section}\n\n{new_line}")

        diff = difflib.unified_diff(
            lines, new_lines,
            fromfile="SKILL.md",
            tofile="SKILL.md (proposed)",
        )
        return "".join(diff)

    def run_proposal_generation(self) -> dict:
        """Generate proposals for all skills with active learnings."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT DISTINCT skill_name FROM skill_learnings WHERE status = 'active'")
        skill_names = [row["skill_name"] for row in cursor.fetchall()]

        total_proposals = 0
        for name in skill_names:
            proposals = self.generate_refinement_proposals(name)
            for p in proposals:
                self.create_proposal(p)
                total_proposals += 1

        return {
            "skills_evaluated": len(skill_names),
            "proposals_created": total_proposals,
        }

    # ── Health summary ───────────────────────────────────────────────────

    def get_skill_health(self, skill_name: str) -> dict:
        """Get comprehensive health summary for a skill."""
        rate = self.compute_success_rate(skill_name)

        cursor = self.db.conn.cursor()

        # Active learnings
        cursor.execute("""
            SELECT * FROM skill_learnings
            WHERE skill_name = ? AND status = 'active'
            ORDER BY evidence_count DESC
        """, (skill_name,))
        learnings = [dict(row) for row in cursor.fetchall()]

        # Pending proposals
        pending = self.get_pending_proposals(skill_name)

        # Recent failures
        cursor.execute("""
            SELECT context_snippet, invoked_at FROM skill_invocation_outcomes
            WHERE skill_name = ? AND outcome = 'failure'
            ORDER BY invoked_at DESC
            LIMIT 5
        """, (skill_name,))
        recent_failures = [dict(row) for row in cursor.fetchall()]

        return {
            "total_invocations": rate["total"],
            "success_rate": rate["success_rate"],
            "trend": rate["trend"],
            "active_learnings": len(learnings),
            "pending_proposals": len(pending),
            "top_learnings": learnings[:5],
            "recent_failures": recent_failures,
        }

    def get_all_skills_health(self) -> list:
        """Get lightweight health summary for all skills with outcomes."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT DISTINCT skill_name FROM skill_invocation_outcomes")
        skill_names = [row["skill_name"] for row in cursor.fetchall()]

        results = []
        for name in skill_names:
            rate = self.compute_success_rate(name)

            cursor.execute("""
                SELECT COUNT(*) as cnt FROM skill_learnings
                WHERE skill_name = ? AND status = 'active'
            """, (name,))
            active_learnings = cursor.fetchone()["cnt"]

            pending = self.get_pending_proposals(name)

            results.append({
                "skill_name": name,
                "total_invocations": rate["total"],
                "success_rate": rate["success_rate"],
                "active_learnings": active_learnings,
                "pending_proposals": len(pending),
            })

        return results
