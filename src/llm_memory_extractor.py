"""
LLM-powered memory extraction

Uses Claude (me!) to analyze conversations and extract meaningful learnings.
No API costs - runs within Claude Code session context.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class ExtractedLearning:
    """Learning extracted by LLM analysis"""
    content: str
    importance: float
    reasoning: str
    category: str  # preference, correction, technical, process, client


def analyze_conversation_for_learnings(conversation: str) -> str:
    """
    Generate analysis prompt for Claude to extract learnings

    Returns prompt that can be sent to Claude for analysis
    """
    prompt = f"""Analyze this Claude Code session and extract learnings worth remembering.

CONVERSATION:
{conversation[:15000]}

EXTRACT learnings in these categories:

1. **Preferences** - User stated preferences ("I prefer X", "Don't do Y")
2. **Corrections** - User corrected me about something important
3. **Technical** - Solutions, patterns, approaches that worked
4. **Process** - Workflows, sequences, methods that were effective
5. **Client-specific** - Patterns specific to a client/project mentioned

For each learning:
- Write 1-2 clear sentences
- Rate importance: 0.5=minor tip, 0.7=useful pattern, 0.85=critical insight, 0.95=game-changer
- Explain why it's important in 1 sentence

FORMAT as JSON array:
```json
[
  {{
    "content": "Specific, actionable learning in 1-2 sentences",
    "importance": 0.75,
    "reasoning": "Why this matters",
    "category": "correction"
  }}
]
```

QUALITY BARS:
- Only extract if it's genuinely useful to remember
- Skip generic advice ("be clear", "test thoroughly")
- Focus on specific, actionable insights
- Corrections get high importance (0.8+)
- Preferences get medium-high importance (0.7+)

If no significant learnings, return empty array: []

Return ONLY the JSON array, no other text."""

    return prompt


def extract_learnings_interactive(session_file: Path) -> List[ExtractedLearning]:
    """
    Interactive LLM extraction - saves prompt to file for user to review

    Args:
        session_file: Path to session JSONL

    Returns:
        List of extracted learnings (empty if not yet analyzed)
    """
    from .session_consolidator import SessionConsolidator

    # Read session
    consolidator = SessionConsolidator()
    messages = consolidator.read_session(session_file)
    conversation = consolidator.extract_conversation_text(messages)

    # Generate prompt
    prompt = analyze_conversation_for_learnings(conversation)

    # Save to review file
    review_dir = session_file.parent / "memory-extraction-review"
    review_dir.mkdir(exist_ok=True)

    review_file = review_dir / f"{session_file.stem}-extraction-prompt.txt"
    review_file.write_text(prompt)

    # Save marker for results
    results_file = review_dir / f"{session_file.stem}-extracted-learnings.json"

    print(f"Extraction prompt saved to: {review_file}")
    print(f"After Claude analyzes, save JSON to: {results_file}")

    # Check if results already exist
    if results_file.exists():
        try:
            data = json.loads(results_file.read_text())
            learnings = [
                ExtractedLearning(
                    content=item["content"],
                    importance=item["importance"],
                    reasoning=item["reasoning"],
                    category=item["category"]
                )
                for item in data
            ]
            return learnings
        except Exception:
            return []

    return []


def save_extracted_learnings(learnings: List[Dict[str, Any]], output_file: Path):
    """
    Save extracted learnings to JSON file for review

    Args:
        learnings: List of learning dicts from LLM
        output_file: Path to save JSON
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(learnings, indent=2))
    print(f"Saved {len(learnings)} learnings to: {output_file}")
