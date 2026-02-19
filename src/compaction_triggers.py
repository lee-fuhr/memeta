"""
Compaction triggers - Time-based and event-based triggers for conversation compaction.

Complements conversation_compactor.py (message count threshold) and
event_detector.py (task/topic/handoff events) with:
1. Inactivity timeout - compact when conversation goes idle
2. Session-end signals - compact when user signals end of session
3. Enhanced should_compact - unified check combining all triggers
"""

import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any

from .event_detector import detect_handoff


def check_inactivity_timeout(
    messages: List[Dict],
    timeout_minutes: int = 60
) -> bool:
    """
    Returns True if the last message timestamp is older than timeout_minutes.

    Expects messages to have a 'timestamp' field (ISO format string).
    Returns False if messages is empty or no timestamps found.

    Args:
        messages: List of message dicts, each optionally with 'timestamp' key
        timeout_minutes: Minutes of inactivity before triggering (default: 60)

    Returns:
        True if last message is older than timeout, False otherwise
    """
    if not messages:
        return False

    # Find the latest timestamp across all messages
    latest_ts: Optional[datetime] = None

    for msg in messages:
        ts_str = msg.get('timestamp')
        if not ts_str or not isinstance(ts_str, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            # Normalize to offset-aware UTC if naive
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
        except (ValueError, TypeError):
            continue

    if latest_ts is None:
        return False

    now = datetime.now(timezone.utc)
    threshold = timedelta(minutes=timeout_minutes)
    return (now - latest_ts) > threshold


# Session-end signal patterns (case-insensitive)
_SESSION_END_PATTERNS = [
    r"that'?s\s+all",
    r"done\s+for\s+(today|now)",
    r"sign(ing)?\s+off",
    r"wrapp?(ing)?\s+up",
    r"good\s*night",
    r"talk\s+(later|tomorrow)",
    r"clos(ing|e)\s+out",
    r"shutting\s+down",
]

_SESSION_END_RE = re.compile(
    '|'.join(_SESSION_END_PATTERNS),
    re.IGNORECASE,
)


def detect_session_end_signal(message: str) -> bool:
    """
    Returns True if the message contains a session-end signal.

    Patterns detected (case-insensitive):
    - "that's all" / "thats all"
    - "done for today" / "done for now"
    - "signing off" / "sign off"
    - "wrapping up" / "wrap up"
    - "good night" / "goodnight"
    - "talk later" / "talk tomorrow"
    - "closing out" / "close out"
    - "shutting down"

    Also delegates to event_detector.detect_handoff() for additional patterns.

    Args:
        message: Message text to check

    Returns:
        True if session-end signal detected
    """
    if not message:
        return False

    if _SESSION_END_RE.search(message):
        return True

    # Delegate to handoff detector for patterns like "continue later",
    # "pick up tomorrow", "switching contexts", etc.
    if detect_handoff(message):
        return True

    return False


def should_compact_enhanced(
    messages: List[Dict],
    message_threshold: int = 50,
    timeout_minutes: int = 60,
) -> Dict[str, Any]:
    """
    Enhanced compaction trigger that checks all three triggers:

    1. Message count threshold (existing behavior)
    2. Inactivity timeout
    3. Session-end signal in the last message

    Priority: message_count > session_end_signal > inactivity_timeout

    Args:
        messages: List of message dicts with optional 'timestamp', 'content' keys
        message_threshold: Compact when exceeding this many messages (default: 50)
        timeout_minutes: Minutes of inactivity before triggering (default: 60)

    Returns:
        Dict with:
        - 'should_compact': bool
        - 'reason': 'message_count' | 'inactivity_timeout' | 'session_end_signal' | None
        - 'details': str  (human-readable explanation)
    """
    result: Dict[str, Any] = {
        'should_compact': False,
        'reason': None,
        'details': 'No compaction triggers fired',
    }

    # --- 1. Message count (highest priority) ---
    if len(messages) > message_threshold:
        result['should_compact'] = True
        result['reason'] = 'message_count'
        result['details'] = (
            f"Message count ({len(messages)}) exceeds threshold ({message_threshold})"
        )
        return result

    # --- 2. Session-end signal (second priority) ---
    if messages:
        last_content = messages[-1].get('content', '')
        if isinstance(last_content, str) and detect_session_end_signal(last_content):
            result['should_compact'] = True
            result['reason'] = 'session_end_signal'
            result['details'] = 'Session-end signal detected in last message'
            return result

    # --- 3. Inactivity timeout (lowest priority) ---
    if check_inactivity_timeout(messages, timeout_minutes=timeout_minutes):
        result['should_compact'] = True
        result['reason'] = 'inactivity_timeout'
        result['details'] = (
            f"Last message is older than {timeout_minutes} minutes"
        )
        return result

    return result
