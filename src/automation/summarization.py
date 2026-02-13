"""
Feature 31: Auto-Summarization

LLM synthesis of all memories on a topic.

"Tell me everything about X" → coherent narrative with timeline

Uses:
- Clustering to group related memories
- LLM to generate narrative
- Timeline ordering
"""

import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory_ts_client import Memory


def _ask_claude(prompt: str, timeout: int = 30) -> str:
    """Wrapper for LLM calls."""
    import llm_extractor
    return llm_extractor.ask_claude(prompt, timeout)


@dataclass
class TopicSummary:
    """Summary of memories on a topic"""
    topic: str
    narrative: str
    timeline: List[dict]  # [{"date": ..., "event": ...}]
    key_insights: List[str]
    memory_count: int


class AutoSummarization:
    """
    LLM-powered summarization of memory topics.
    
    Example:
        summarizer = AutoSummarization()
        
        summary = summarizer.summarize_topic(
            topic="client feedback",
            memories=[...]
        )
        
        print(summary.narrative)
        for event in summary.timeline:
            print(f"{event['date']}: {event['event']}")
    """

    def summarize_topic(self, topic: str, memories: List[Memory]) -> TopicSummary:
        """Generate summary of memories on topic."""
        if not memories:
            return TopicSummary(
                topic=topic,
                narrative=f"No memories found about {topic}",
                timeline=[],
                key_insights=[],
                memory_count=0
            )
        
        # Sort by date
        sorted_memories = sorted(memories, key=lambda m: m.created_at)
        
        # Build timeline
        timeline = []
        for mem in sorted_memories:
            timeline.append({
                "date": mem.created_at.strftime("%Y-%m-%d"),
                "event": mem.content[:100]  # First 100 chars
            })
        
        # Generate narrative via LLM
        memory_texts = "\n".join([f"- {m.content}" for m in sorted_memories[:20]])  # Limit to 20
        
        prompt = f"""
Synthesize these memories about "{topic}" into a coherent narrative.

Memories:
{memory_texts}

Provide:
1. A narrative summary (2-3 paragraphs)
2. 3-5 key insights

Format as JSON:
{{"narrative": "...", "key_insights": ["...", "..."]}}
"""
        
        try:
            import json
            response = _ask_claude(prompt, timeout=30)
            data = json.loads(response.strip())
            
            narrative = data.get("narrative", "Unable to generate summary")
            key_insights = data.get("key_insights", [])
        except Exception:
            narrative = f"Found {len(memories)} memories about {topic}"
            key_insights = []
        
        return TopicSummary(
            topic=topic,
            narrative=narrative,
            timeline=timeline,
            key_insights=key_insights,
            memory_count=len(memories)
        )

    def daily_digest(self, date: Optional[str] = None) -> TopicSummary:
        """Generate daily digest of memories."""
        from memory_ts_client import MemoryTSClient
        from datetime import datetime, timedelta
        
        client = MemoryTSClient()
        
        # Get memories from date (default: yesterday)
        if date is None:
            target_date = datetime.now() - timedelta(days=1)
        else:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        
        all_memories = client.search()
        day_memories = [
            m for m in all_memories
            if m.created_at.date() == target_date.date()
        ]
        
        return self.summarize_topic(
            topic=f"Daily digest for {target_date.strftime('%Y-%m-%d')}",
            memories=day_memories
        )
