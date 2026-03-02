"""
Commitment nudger — surfaces "don't let me forget" commitments at session
start, ranked by urgency.

Extends ProspectiveTriggerManager with additional commitment-intent patterns
and a scoring/ranking layer for session-start surfacing.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone

from memory_system.prospective_triggers import (
    ProspectiveTrigger,
    ProspectiveTriggerManager,
)


# ---------------------------------------------------------------------------
# Extended commitment patterns (beyond PTM's 6)
# ---------------------------------------------------------------------------

COMMITMENT_PATTERNS: list[str] = [
    r"I should (.+?)(?:\.|$)",
    r"(?:we |I )?need to (.+?)(?:\.|$)",
    r"let'?s make sure (.+?)(?:\.|$)",
    r"follow up on (.+?)(?:\.|$)",
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_trigger(trigger: ProspectiveTrigger, context: dict) -> float:
    """Score a trigger for priority ranking.

    Weights:
    - Time overdue: days_overdue * 0.1 (highest weight)
    - Topic match: keyword overlap with context keywords
    - Event relevance: bonus for matching trigger_type

    Memory importance multiplier from context if available.

    Args:
        trigger: A ProspectiveTrigger object.
        context: Dict with optional keys: current_date (str YYYY-MM-DD),
                 keywords (list[str]), importance_map (dict mapping
                 memory_id to float).

    Returns:
        Float score, higher = more urgent.
    """
    score = 0.0

    # --- Time overdue component ---
    if trigger.trigger_type == "time":
        after_date = trigger.condition.get("after_date")
        current_date = context.get("current_date")
        if after_date and current_date:
            try:
                due = datetime.strptime(after_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                now = datetime.strptime(current_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                days_overdue = (now - due).days
                if days_overdue > 0:
                    score += days_overdue * 0.1
            except ValueError:
                pass

    # --- Topic/event keyword overlap component ---
    cond_keywords = set(
        k.lower() for k in trigger.condition.get("keywords", [])
    )
    ctx_keywords = set(
        k.lower() for k in context.get("keywords", [])
    )
    if cond_keywords and ctx_keywords:
        overlap = len(cond_keywords & ctx_keywords)
        score += overlap * 0.5

    # --- Importance multiplier ---
    importance_map = context.get("importance_map", {})
    multiplier = importance_map.get(trigger.memory_id, 1.0)
    score *= multiplier

    return score


# ---------------------------------------------------------------------------
# Top commitments
# ---------------------------------------------------------------------------

def get_top_commitments(
    db_path: str, context: dict, limit: int = 3
) -> list[dict]:
    """Get top-N most urgent commitments.

    Uses PTM.get_pending_triggers(), scores each, deduplicates by memory_id
    (keep highest score), returns top-N.

    Returns:
        List of dicts with keys: trigger, score, reason (str explaining
        why ranked high).
    """
    ptm = ProspectiveTriggerManager(db_path)
    pending = ptm.get_pending_triggers()

    scored: list[dict] = []
    for trigger in pending:
        s = score_trigger(trigger, context)
        reason = _build_reason(trigger, s, context)
        scored.append({"trigger": trigger, "score": s, "reason": reason})

    # Deduplicate by memory_id — keep highest score
    best_by_memory: dict[str, dict] = {}
    for item in scored:
        mid = item["trigger"].memory_id
        if mid not in best_by_memory or item["score"] > best_by_memory[mid]["score"]:
            best_by_memory[mid] = item

    deduped = sorted(best_by_memory.values(), key=lambda x: x["score"], reverse=True)
    return deduped[:limit]


def _build_reason(trigger: ProspectiveTrigger, score: float, context: dict) -> str:
    """Build a human-readable reason for why a trigger ranked high."""
    parts: list[str] = []

    if trigger.trigger_type == "time":
        after_date = trigger.condition.get("after_date")
        current_date = context.get("current_date")
        if after_date and current_date:
            try:
                due = datetime.strptime(after_date, "%Y-%m-%d")
                now = datetime.strptime(current_date, "%Y-%m-%d")
                days = (now - due).days
                if days > 0:
                    parts.append(f"overdue by {days} day(s)")
            except ValueError:
                pass

    cond_keywords = set(k.lower() for k in trigger.condition.get("keywords", []))
    ctx_keywords = set(k.lower() for k in context.get("keywords", []))
    overlap = cond_keywords & ctx_keywords
    if overlap:
        parts.append(f"topic match: {', '.join(sorted(overlap))}")

    importance_map = context.get("importance_map", {})
    mult = importance_map.get(trigger.memory_id)
    if mult is not None and mult != 1.0:
        parts.append(f"importance x{mult:.1f}")

    if not parts:
        parts.append("pending commitment")

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_commitment_block(commitments: list[dict]) -> str:
    """Format commitments for display.

    Returns:
        "=== PENDING COMMITMENTS ===" header with numbered list,
        or empty string if no commitments.
    """
    if not commitments:
        return ""

    lines: list[str] = ["=== PENDING COMMITMENTS ==="]
    for i, item in enumerate(commitments, 1):
        trigger = item["trigger"]
        score = item["score"]
        reason = item["reason"]
        condition_summary = _summarize_condition(trigger)
        lines.append(
            f"{i}. [{score:.1f}] {condition_summary} ({reason})"
        )

    return "\n".join(lines)


def _summarize_condition(trigger: ProspectiveTrigger) -> str:
    """One-line summary of what the trigger is about."""
    if trigger.trigger_type == "time":
        date = trigger.condition.get("after_date", "?")
        return f"time trigger (after {date})"

    keywords = trigger.condition.get("keywords", [])
    if keywords:
        return ", ".join(keywords[:5])

    return f"{trigger.trigger_type} trigger"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_commitments(
    text: str, memory_id: str, db_path: str
) -> list[ProspectiveTrigger]:
    """Extract commitments using extended patterns + PTM trigger creation.

    Uses both COMMITMENT_PATTERNS (new) and PTM's existing patterns.
    Creates triggers via PTM for any matches.
    Returns list of created ProspectiveTrigger objects.
    """
    ptm = ProspectiveTriggerManager(db_path)

    # First, extract via PTM's built-in patterns
    ptm_triggers = ptm.extract_triggers(text, memory_id)

    # Track what was already captured (by normalized keyword set) to avoid dupes
    seen: set[tuple[str, ...]] = set()
    for t in ptm_triggers:
        kw_key = tuple(sorted(k.lower() for k in t.condition.get("keywords", [])))
        if kw_key:
            seen.add(kw_key)

    # Now extract via extended commitment patterns
    now = datetime.now(timezone.utc).isoformat()
    extra_triggers: list[ProspectiveTrigger] = []

    for pattern in COMMITMENT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            captured = match.group(1).strip()
            if not captured:
                continue

            trigger_type, condition = ptm.classify_trigger_type(captured)

            # Skip if no meaningful keywords
            if trigger_type in ("topic", "event") and not condition.get("keywords"):
                continue

            # Dedup check
            kw_key = tuple(sorted(k.lower() for k in condition.get("keywords", [])))
            if kw_key and kw_key in seen:
                continue
            if kw_key:
                seen.add(kw_key)

            # Insert into DB
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute(
                    "INSERT INTO prospective_triggers "
                    "(memory_id, trigger_type, condition, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (memory_id, trigger_type, json.dumps(condition), "pending", now),
                )
                conn.commit()
                trigger_id = cursor.lastrowid
            finally:
                conn.close()

            extra_triggers.append(
                ProspectiveTrigger(
                    trigger_id=trigger_id,
                    memory_id=memory_id,
                    trigger_type=trigger_type,
                    condition=condition,
                    status="pending",
                    created_at=now,
                )
            )

    return ptm_triggers + extra_triggers
