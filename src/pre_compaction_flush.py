"""
Pre-compaction flush - Extract durable facts before summarizing conversations.

When conversations hit 50+ messages, they get compacted (summarized) to save
token budget. But summarization can lose important facts.

Solution: BEFORE compacting, extract up to 5 durable facts and save them
to memory-ts with "#pre-compaction" tag. Write-ahead log pattern.
"""

import json
from typing import List, Dict
from pathlib import Path
from datetime import datetime


def extract_durable_facts(
    conversation: str,
    max_facts: int = 5
) -> List[Dict]:
    """
    Extract durable facts that should survive compaction.

    Uses LLM to identify names, preferences, decisions, and critical context
    that summarization might lose.

    Args:
        conversation: Full conversation text
        max_facts: Maximum number of facts to extract (default: 5)

    Returns:
        List of fact dicts with 'content', 'importance', 'category' keys
    """
    from .llm_extractor import ask_claude

    # Limit conversation to last 10K chars (most recent = most relevant)
    sample = conversation[-10000:]

    prompt = f"""Extract up to {max_facts} durable facts from this conversation that should be preserved long-term.

Focus on:
- Names (people, companies, products)
- Preferences (user stated "I prefer X")
- Decisions ("We decided to use Y")
- Important context that summarization might lose

Return JSON array:
[{{"content": "...", "importance": 0.7-0.95, "category": "name|preference|decision|context"}}]

If no significant durable facts, return empty array [].

Conversation:
{sample}"""

    try:
        response = ask_claude(prompt, timeout=20)

        # Parse JSON response
        facts = json.loads(response.strip())

        if not isinstance(facts, list):
            return []

        # Validate and sort by importance
        valid_facts = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if 'content' not in fact:
                continue

            # Ensure required fields
            fact.setdefault('importance', 0.75)
            fact.setdefault('category', 'context')

            # Clamp importance
            fact['importance'] = max(0.7, min(0.95, fact['importance']))

            valid_facts.append(fact)

        # Sort by importance and limit
        valid_facts.sort(key=lambda x: x['importance'], reverse=True)
        return valid_facts[:max_facts]

    except (json.JSONDecodeError, Exception):
        # Fail gracefully - compaction continues even if extraction fails
        return []


def extract_before_compaction(
    session_path: Path,
    session_id: str,
    max_facts: int = 5
) -> List[Dict]:
    """
    Pre-compaction flush: Extract durable facts before compacting conversation.

    This is called BEFORE conversation summarization to preserve critical
    facts that might be lost in summarization.

    Args:
        session_path: Path to session JSONL file
        session_id: Session identifier
        max_facts: Maximum facts to extract (default: 5)

    Returns:
        List of extracted facts with content, importance, category
    """
    # Read session file
    try:
        with open(session_path) as f:
            lines = f.readlines()

        # Extract conversation text (filter out tool calls)
        conversation_parts = []

        for line in lines:
            try:
                msg = json.loads(line)
                role = msg.get('role', '')
                content = msg.get('content', '')

                # Skip tool use/result messages
                if role in ['user', 'assistant'] and isinstance(content, str):
                    conversation_parts.append(f"{role}: {content}")

            except json.JSONDecodeError:
                continue

        conversation = '\n'.join(conversation_parts)

        # Extract durable facts
        facts = extract_durable_facts(conversation, max_facts=max_facts)

        # Tag with session_id and pre-compaction marker
        for fact in facts:
            fact['session_id'] = session_id
            fact['tags'] = fact.get('tags', []) + ['#pre-compaction']
            fact['extracted_at'] = datetime.now().isoformat()

        return facts

    except Exception:
        return []
