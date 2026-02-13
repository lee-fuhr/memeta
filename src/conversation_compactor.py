"""
Conversation compaction - Auto-summarize long conversations.

When conversations exceed 50 messages, compact them by:
1. Running pre-compaction flush (extract durable facts)
2. Summarizing old messages (keep recent 10 verbatim)
3. Replacing old messages with summary

This saves token budget while preserving important context.
"""

from typing import List, Dict
from datetime import datetime


def should_compact(message_count: int, threshold: int = 50) -> bool:
    """
    Check if conversation should be compacted.

    Args:
        message_count: Current number of messages
        threshold: Compact when exceeding this many messages (default: 50)

    Returns:
        True if should compact, False otherwise
    """
    return message_count > threshold


def compact_conversation(
    messages: List[Dict],
    keep_recent: int = 10
) -> Dict:
    """
    Compact conversation by summarizing old messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        keep_recent: Number of recent messages to keep verbatim (default: 10)

    Returns:
        Dict with:
        - 'summary': Summary of old messages
        - 'compacted_messages': List with summary + recent messages
        - 'messages_compacted': Number of messages summarized
    """
    if len(messages) <= keep_recent:
        return {
            'summary': None,
            'compacted_messages': messages,
            'messages_compacted': 0
        }

    # Split into old (to summarize) and recent (keep verbatim)
    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    # Extract conversation text from old messages
    old_conversation = []
    for msg in old_messages:
        role = msg.get('role', '')
        content = msg.get('content', '')

        if isinstance(content, str) and content:
            old_conversation.append(f"{role}: {content[:500]}")  # Limit each message

    conversation_text = '\n'.join(old_conversation)

    # Generate summary
    from .llm_extractor import ask_claude

    summary_prompt = f"""Summarize this conversation in 2-3 paragraphs. Focus on:
- Key decisions made
- Important context established
- Main topics discussed

Conversation ({len(old_messages)} messages):
{conversation_text[:5000]}"""

    summary = ask_claude(summary_prompt, timeout=20)

    if not summary:
        summary = f"[Compacted {len(old_messages)} messages from conversation]"

    # Create compacted message list
    summary_message = {
        'role': 'system',
        'content': f"[Conversation Summary - {len(old_messages)} messages compacted]\n\n{summary}",
        'timestamp': datetime.now().isoformat(),
        'is_summary': True
    }

    compacted_messages = [summary_message] + recent_messages

    return {
        'summary': summary,
        'compacted_messages': compacted_messages,
        'messages_compacted': len(old_messages)
    }


def get_compaction_stats(messages: List[Dict]) -> Dict:
    """
    Get statistics about conversation compaction.

    Args:
        messages: List of message dicts

    Returns:
        Dict with stats:
        - 'total_messages': Total message count
        - 'summary_messages': Number of summary messages
        - 'real_messages': Number of non-summary messages
        - 'compaction_ratio': Ratio of summaries to total
    """
    total = len(messages)
    summary_count = sum(1 for m in messages if m.get('is_summary', False))
    real_count = total - summary_count

    return {
        'total_messages': total,
        'summary_messages': summary_count,
        'real_messages': real_count,
        'compaction_ratio': summary_count / total if total > 0 else 0
    }
