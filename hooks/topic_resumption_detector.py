#!/usr/bin/env python3
"""
Topic Resumption Detector Hook

Triggers when user references past discussions.
Auto-searches memories and surfaces relevant context.

Hook type: UserPromptSubmit
Timeout: 3000ms
"""

import sys
import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, List

# Skip hook if disabled
if os.getenv('SKIP_HOOK_TOPIC_RESUMPTION'):
    sys.exit(0)

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from memory_ts_client import MemoryTSClient, Memory
from wild.temporal_predictor import TemporalPatternPredictor


# Trigger phrases
TRIGGER_PHRASES = [
    r"\bwe discussed this before\b",
    r"\bdidn't we talk about\b",
    r"\bwe had some back and forth\b",
    r"\bpreviously\b",
    r"\bremember when we\b",
    r"\blast time we discussed\b",
    r"\bwe already covered\b",
    r"\bas I mentioned before\b",
    r"\bI think we talked about\b",
    r"\bdidn't I tell you\b",
]

# Stopwords for keyword extraction
STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'we', 'this', 'that', 'is',
    'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
    'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may',
    'might', 'must', 'can', 'about', 'some', 'before', 'previously',
    'didn', 'talk', 'discussed', 'mentioned', 'remember', 'when', 'already',
    'covered', 'think', 'tell', 'you', 'i', 'me', 'my', 'it', 'its', 'there'
}


def detect_topic_resumption(user_message: str) -> Optional[Dict]:
    """
    Detect if user is referencing past discussion.

    Returns:
        {
            'detected': True,
            'trigger_phrase': "we discussed this before",
            'context_keywords': ["messaging", "framework", "Connection Lab"],
            'search_query': "messaging framework Connection Lab"
        }
    """
    # 1. Check for trigger phrases (regex)
    matched_phrase = None
    for pattern in TRIGGER_PHRASES:
        if re.search(pattern, user_message, re.IGNORECASE):
            matched_phrase = pattern
            break

    if not matched_phrase:
        return None

    # 2. Extract topic keywords from surrounding message
    # Use simple stopword removal + noun extraction
    words = user_message.lower().split()
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 3]

    # 3. Build search query
    search_query = " ".join(keywords[:5])  # Top 5 keywords

    return {
        'detected': True,
        'trigger_phrase': matched_phrase,
        'context_keywords': keywords,
        'search_query': search_query
    }


def search_relevant_memories(query: str, limit: int = 5) -> List[Memory]:
    """
    Search memories using MemoryTSClient.
    """
    try:
        client = MemoryTSClient()
        results = client.search(content=query, project_id="LFI")

        # Log accesses for temporal pattern learning
        predictor = TemporalPatternPredictor()
        session_id = os.getenv('CLAUDE_SESSION_ID')

        for memory in results[:limit]:
            predictor.log_memory_access(
                memory_id=memory.id,
                access_type='hook',
                context_keywords=query.split(),
                session_id=session_id
            )

        # Manually slice to limit since search() doesn't have limit parameter
        return results[:limit]
    except Exception as e:
        # Silent failure - don't break the user's flow
        return []


def format_hook_output(memories: List[Memory]) -> str:
    """
    Format memories for injection into Claude's context.
    """
    if not memories:
        return ""

    output = "\n## Relevant Context from Past Discussions\n\n"

    for i, mem in enumerate(memories, 1):
        output += f"{i}. **{mem.created[:10]}** (importance: {mem.importance:.1f})\n"
        output += f"   {mem.content}\n"
        if mem.session_id:
            output += f"   [Resume session: `claude --resume {mem.session_id}`]\n"
        output += "\n"

    return output


def main():
    try:
        # Read user message from stdin
        input_data = json.loads(sys.stdin.read())

        # Extract message text
        if 'message' in input_data:
            user_message = input_data['message']
        elif 'content' in input_data:
            content_blocks = input_data['content']
            user_message = " ".join(
                block['text'] for block in content_blocks
                if block.get('type') == 'text'
            )
        else:
            sys.exit(0)

        # Detect topic resumption
        detection = detect_topic_resumption(user_message)

        if not detection:
            sys.exit(0)  # No trigger

        # Search memories
        memories = search_relevant_memories(
            detection['search_query'],
            limit=5
        )

        if not memories:
            sys.exit(0)  # No relevant memories

        # Output context for Claude
        output = format_hook_output(memories)
        print(output)

        sys.exit(0)

    except Exception as e:
        # Silent failure - don't break user's flow
        sys.exit(0)


if __name__ == '__main__':
    main()
