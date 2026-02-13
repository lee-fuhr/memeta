"""
Event-based compaction - Detect task completion, topic shifts for proactive compaction.

Feature 13: Instead of waiting for message count threshold, compact when:
- Task completion detected ("done", "shipped", "merged", "deployed")
- Topic shift detected (different subject, new project)
- Session handoff detected (user says "pause" or "switching to X")
"""

from typing import Optional, Dict
import re


# Completion keywords
COMPLETION_KEYWORDS = [
    'done', 'complete', 'finished', 'shipped', 'merged', 'deployed',
    'fixed', 'resolved', 'closed', 'implemented', 'built', 'delivered'
]

# Topic shift keywords
TOPIC_SHIFT_KEYWORDS = [
    'moving on', 'switching to', 'next up', 'different topic',
    'new task', 'change subject', 'actually', 'by the way'
]

# Handoff keywords
HANDOFF_KEYWORDS = [
    'pause', 'continue later', 'pick up tomorrow', 'save this',
    'come back to', 'switching contexts', 'need to switch'
]


def detect_task_completion(message: str) -> bool:
    """
    Detect if message indicates task completion.

    Args:
        message: User or assistant message

    Returns:
        True if completion detected
    """
    message_lower = message.lower()

    # Check for completion keywords
    for keyword in COMPLETION_KEYWORDS:
        if keyword in message_lower:
            # Additional context check - avoid false positives
            # "not done" should not trigger
            if f"not {keyword}" in message_lower:
                continue
            if f"isn't {keyword}" in message_lower:
                continue
            if f"hasn't {keyword}" in message_lower:
                continue

            return True

    # Pattern: "task is complete", "feature is shipped"
    if re.search(r'\b(is|are)\s+(done|complete|finished|shipped)', message_lower):
        return True

    return False


def detect_topic_shift(message: str) -> bool:
    """
    Detect if message indicates topic change.

    Args:
        message: User message

    Returns:
        True if topic shift detected
    """
    message_lower = message.lower()

    # Check for explicit topic shift keywords
    for keyword in TOPIC_SHIFT_KEYWORDS:
        if keyword in message_lower:
            return True

    # Pattern: "let's talk about X instead"
    if re.search(r"let'?s (talk about|discuss|move to|switch to)", message_lower):
        return True

    # Pattern: "okay now [new topic]"
    if re.search(r'(okay|alright|cool)[,\s]+(now|next)', message_lower):
        return True

    return False


def detect_handoff(message: str) -> bool:
    """
    Detect if message indicates session handoff/pause.

    Args:
        message: User message

    Returns:
        True if handoff detected
    """
    message_lower = message.lower()

    # Check for handoff keywords
    for keyword in HANDOFF_KEYWORDS:
        if keyword in message_lower:
            return True

    # Pattern: "I'll come back to this"
    if re.search(r"(i'll|i will|gonna) (come back|return|resume)", message_lower):
        return True

    return False


def should_compact_conversation(messages: list) -> Dict[str, bool]:
    """
    Determine if conversation should be compacted based on events.

    Args:
        messages: List of recent messages (dicts with 'role' and 'content')

    Returns:
        Dict with reasons:
        {
            'should_compact': bool,
            'reason': str,
            'task_complete': bool,
            'topic_shift': bool,
            'handoff': bool
        }
    """
    if not messages:
        return {
            'should_compact': False,
            'reason': None,
            'task_complete': False,
            'topic_shift': False,
            'handoff': False
        }

    # Check last few messages for events
    recent_messages = messages[-5:]  # Last 5 messages

    task_complete = False
    topic_shift = False
    handoff = False

    for msg in recent_messages:
        content = msg.get('content', '')
        if not isinstance(content, str):
            continue

        if detect_task_completion(content):
            task_complete = True

        if detect_topic_shift(content):
            topic_shift = True

        if detect_handoff(content):
            handoff = True

    # Decide if should compact
    should_compact = task_complete or topic_shift or handoff

    # Determine reason
    reason = None
    if task_complete:
        reason = "task_completion"
    elif topic_shift:
        reason = "topic_shift"
    elif handoff:
        reason = "session_handoff"

    return {
        'should_compact': should_compact,
        'reason': reason,
        'task_complete': task_complete,
        'topic_shift': topic_shift,
        'handoff': handoff
    }
