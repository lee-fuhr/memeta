"""
Feature 31: Auto-Summarization

LLM synthesis of all memories on a topic.

Capabilities:
- Topic-based summarization with narrative
- Timeline generation
- Key insights extraction
- Daily/weekly/monthly digests
- Summary persistence and regeneration

Database: intelligence.db (summaries table)
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_pool import get_connection
from memory_ts_client import Memory


def _ask_claude(prompt: str, timeout: int = 30) -> str:
    """Wrapper for LLM calls."""
    import llm_extractor
    return llm_extractor.ask_claude(prompt, timeout)


@dataclass
class TopicSummary:
    """Summary of memories on a topic"""
    summary_id: Optional[int]
    topic: str
    narrative: str
    timeline: List[dict]  # [{"date": ..., "event": ...}]
    key_insights: List[str]
    memory_count: int
    created_at: datetime
    memory_ids: List[str]


class AutoSummarization:
    """
    LLM-powered summarization of memory topics with persistence.

    Capabilities:
    - Topic-based summarization
    - Timeline generation
    - Key insights extraction
    - Summary persistence
    - Regeneration support

    Example:
        summarizer = AutoSummarization()

        # Summarize topic
        summary = summarizer.summarize_topic(
            topic="client feedback",
            memories=[...]
        )

        print(summary.narrative)
        for insight in summary.key_insights:
            print(f"- {insight}")

        # Get past summaries
        past = summarizer.get_summaries(topic="client feedback")

        # Regenerate summary
        regenerated = summarizer.regenerate_summary(summary.summary_id)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize summarization system.

        Args:
            db_path: Path to intelligence.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "intelligence.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Create summaries table."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    narrative TEXT NOT NULL,
                    timeline TEXT NOT NULL,
                    key_insights TEXT NOT NULL,
                    memory_count INTEGER NOT NULL,
                    memory_ids TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_topic
                ON summaries(topic, created_at DESC)
            """)

            conn.commit()

    def summarize_topic(
        self,
        topic: str,
        memories: List[Memory],
        save: bool = True
    ) -> TopicSummary:
        """
        Generate summary of memories on topic.

        Args:
            topic: Topic to summarize
            memories: Memories to include
            save: Save summary to database

        Returns:
            TopicSummary object
        """
        now = datetime.now()

        if not memories:
            summary = TopicSummary(
                summary_id=None,
                topic=topic,
                narrative=f"No memories found about {topic}",
                timeline=[],
                key_insights=[],
                memory_count=0,
                created_at=now,
                memory_ids=[]
            )
            if save:
                return self._save_summary(summary)
            return summary

        # Sort by date
        sorted_memories = sorted(memories, key=lambda m: m.created)

        # Build timeline
        timeline = []
        for mem in sorted_memories:
            timeline.append({
                "date": mem.created.strftime("%Y-%m-%d"),
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
            response = _ask_claude(prompt, timeout=30)
            data = json.loads(response.strip())

            narrative = data.get("narrative", "Unable to generate summary")
            key_insights = data.get("key_insights", [])
        except Exception:
            # Fallback if LLM fails
            narrative = f"Found {len(memories)} memories about {topic}. "
            narrative += f"Spanning from {sorted_memories[0].created.strftime('%Y-%m-%d')} "
            narrative += f"to {sorted_memories[-1].created.strftime('%Y-%m-%d')}."
            key_insights = [f"{mem.content[:100]}..." for mem in sorted_memories[:3]]

        summary = TopicSummary(
            summary_id=None,
            topic=topic,
            narrative=narrative,
            timeline=timeline,
            key_insights=key_insights,
            memory_count=len(memories),
            created_at=now,
            memory_ids=[m.id for m in memories]
        )

        if save:
            return self._save_summary(summary)

        return summary

    def get_summaries(
        self,
        topic: Optional[str] = None,
        limit: int = 10
    ) -> List[TopicSummary]:
        """
        Get past summaries.

        Args:
            topic: Filter by topic
            limit: Maximum results

        Returns:
            List of TopicSummary objects
        """
        with get_connection(self.db_path) as conn:
            if topic:
                query = """
                    SELECT summary_id, topic, narrative, timeline, key_insights,
                           memory_count, memory_ids, created_at
                    FROM summaries
                    WHERE topic = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params = (topic, limit)
            else:
                query = """
                    SELECT summary_id, topic, narrative, timeline, key_insights,
                           memory_count, memory_ids, created_at
                    FROM summaries
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params = (limit,)

            cursor = conn.execute(query, params)

            summaries = []
            for row in cursor.fetchall():
                summaries.append(TopicSummary(
                    summary_id=row[0],
                    topic=row[1],
                    narrative=row[2],
                    timeline=json.loads(row[3]),
                    key_insights=json.loads(row[4]),
                    memory_count=row[5],
                    memory_ids=json.loads(row[6]),
                    created_at=datetime.fromtimestamp(row[7])
                ))

            return summaries

    def get_summary(self, summary_id: int) -> Optional[TopicSummary]:
        """Get specific summary by ID."""
        summaries = self.get_summaries()
        return next((s for s in summaries if s.summary_id == summary_id), None)

    def regenerate_summary(self, summary_id: int) -> Optional[TopicSummary]:
        """
        Regenerate a summary with same memories.

        Args:
            summary_id: Summary to regenerate

        Returns:
            New TopicSummary or None if original not found
        """
        original = self.get_summary(summary_id)
        if not original:
            return None

        # Get original memories
        from memory_ts_client import MemoryTSClient
        client = MemoryTSClient()

        memories = []
        for mem_id in original.memory_ids:
            mem = client.get(mem_id)
            if mem:
                memories.append(mem)

        # Generate new summary
        return self.summarize_topic(original.topic, memories, save=True)

    def _save_summary(self, summary: TopicSummary) -> TopicSummary:
        """Save summary to database."""
        now = int(time.time())

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO summaries
                (topic, narrative, timeline, key_insights, memory_count, memory_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                summary.topic,
                summary.narrative,
                json.dumps(summary.timeline),
                json.dumps(summary.key_insights),
                summary.memory_count,
                json.dumps(summary.memory_ids),
                now
            ))

            summary_id = cursor.lastrowid
            conn.commit()

        # Return summary with ID
        summary.summary_id = summary_id
        return summary
