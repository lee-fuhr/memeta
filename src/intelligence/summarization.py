"""
Feature 26 + 31: Memory Summarization (merged)

LLM-powered summarization of memories.

Summary types:
- Cluster summaries (F26): What's this group of related memories about?
- Project summaries (F26): What happened in this project over time period?
- Period summaries (F26): What was captured this week/month?
- Topic summaries (F31): Narrative + timeline + key insights on any topic

Use cases:
- Quick overview of clusters
- Project retrospectives
- Weekly/monthly memory digests
- Session consolidation summaries
- Ad-hoc topic synthesis
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from memory_system.db_pool import get_connection
from memory_system.intelligence_db import IntelligenceDB
from memory_system.memory_ts_client import Memory, MemoryTSClient


def _ask_claude(prompt: str, model: str = "sonnet", temperature: float = 0.3, timeout: int = 30) -> str:
    """Wrapper for LLM calls."""
    from memory_system import llm_extractor
    return llm_extractor.ask_claude(prompt, timeout=timeout)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Summary:
    """A generated summary of memories (cluster / project / period)."""
    id: str
    summary_type: str  # cluster, project, period
    target_id: Optional[str]  # cluster_id or project_id
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    summary: str  # The actual summary text
    memory_count: int
    created_at: datetime


@dataclass
class TopicSummary:
    """A narrative summary of memories on a specific topic (F31)."""
    summary_id: Optional[int]
    topic: str
    narrative: str
    timeline: List[dict]  # [{"date": ..., "event": ...}]
    key_insights: List[str]
    memory_count: int
    created_at: datetime
    memory_ids: List[str]


# ── Main class ────────────────────────────────────────────────────────────────

class MemorySummarizer:
    """
    LLM-powered summarization of memories.

    Generates four types of summaries:
    - Cluster summaries: What's this group of related memories about?
    - Project summaries: What happened in this project over time period?
    - Period summaries: What was captured this week/month?
    - Topic summaries: Narrative + timeline + key insights on any topic
    """

    def __init__(self, db_path: Optional[Path] = None, memory_client: Optional[MemoryTSClient] = None):
        """
        Initialize summarizer with intelligence.db

        Args:
            db_path: Path to intelligence.db (default: auto-detect)
            memory_client: Optional client for memory-ts operations
        """
        self.intel_db = IntelligenceDB(db_path)
        self.memory_client = memory_client or MemoryTSClient()
        self._init_topic_table()

    def _init_topic_table(self):
        """Ensure topic summaries table exists."""
        with get_connection(self.intel_db.db_path) as conn:
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

    # ── F26: Cluster / Project / Period summarization ─────────────────────

    def summarize_cluster(self, cluster_id: str) -> Optional[Summary]:
        """
        Generate summary of a memory cluster.

        Args:
            cluster_id: Cluster identifier from memory_clusters table

        Returns:
            Summary object or None if cluster not found
        """
        with get_connection(self.intel_db.db_path) as conn:
            row = conn.execute(
                "SELECT id, name, memory_ids FROM memory_clusters WHERE id = ?",
                (cluster_id,)
            ).fetchone()

        if not row:
            return None

        cluster_name = row[1]
        memory_ids = json.loads(row[2])

        if not memory_ids:
            return self._create_summary(
                summary_type="cluster",
                target_id=cluster_id,
                summary=f"Cluster '{cluster_name}' contains no memories.",
                memory_count=0
            )

        memories = []
        for mem_id in memory_ids[:20]:
            memory = self.memory_client.get(mem_id)
            if memory:
                memories.append(memory.content)

        if not memories:
            return self._create_summary(
                summary_type="cluster",
                target_id=cluster_id,
                summary=f"Cluster '{cluster_name}' memories not found.",
                memory_count=0
            )

        summary_text = self._generate_cluster_summary(cluster_name, memories)
        return self._create_summary(
            summary_type="cluster",
            target_id=cluster_id,
            summary=summary_text,
            memory_count=len(memory_ids)
        )

    def summarize_project(
        self,
        project_id: str,
        days: int = 30,
        min_memories: int = 5
    ) -> Optional[Summary]:
        """
        Generate summary of project activity over time period.

        Args:
            project_id: Project identifier
            days: Number of days to look back (default: 30)
            min_memories: Minimum memories needed for summary (default: 5)

        Returns:
            Summary or None if insufficient memories
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        memories = self.memory_client.search(project_id=project_id, limit=10000)
        period_memories = [
            m for m in memories
            if hasattr(m, 'created_at') and start_date <= m.created_at <= end_date
        ]

        if len(period_memories) < min_memories:
            return None

        memory_contents = []
        for m in period_memories[:50]:
            date_str = m.created_at.strftime("%Y-%m-%d")
            memory_contents.append(f"[{date_str}] {m.content[:500]}")

        summary_text = self._generate_project_summary(
            project_id, memory_contents, start_date, end_date
        )
        return self._create_summary(
            summary_type="project",
            target_id=project_id,
            period_start=start_date,
            period_end=end_date,
            summary=summary_text,
            memory_count=len(period_memories)
        )

    def summarize_period(
        self,
        start: datetime,
        end: datetime,
        project_id: Optional[str] = None
    ) -> Optional[Summary]:
        """
        Generate summary of memories captured in time period.

        Args:
            start: Period start date
            end: Period end date
            project_id: Optional project filter

        Returns:
            Summary or None if no memories
        """
        if start > end:
            start, end = end, start

        if project_id:
            memories = self.memory_client.search(project_id=project_id, limit=10000)
        else:
            memories = self.memory_client.search(content="", limit=10000)

        period_memories = [
            m for m in memories
            if hasattr(m, 'created_at') and start <= m.created_at <= end
        ]

        if not period_memories:
            return None

        memory_contents = [m.content[:500] for m in period_memories[:30]]

        summary_text = self._generate_period_summary(memory_contents, start, end, project_id)
        return self._create_summary(
            summary_type="period",
            target_id=project_id,
            period_start=start,
            period_end=end,
            summary=summary_text,
            memory_count=len(period_memories)
        )

    def get_summary(self, summary_id) -> Optional[object]:
        """
        Retrieve a summary by ID.

        - int → TopicSummary (F31 API)
        - str → Summary (F26 API: cluster/project/period)
        """
        if isinstance(summary_id, int):
            return self.get_topic_summary(summary_id)
        return self._get_base_summary(summary_id)

    def _get_base_summary(self, summary_id: str) -> Optional[Summary]:
        """Retrieve a cluster/project/period summary by UUID string."""
        with get_connection(self.intel_db.db_path) as conn:
            row = conn.execute(
                """SELECT id, summary_type, target_id, period_start, period_end,
                          summary, memory_count, created_at
                   FROM memory_summaries WHERE id = ?""",
                (summary_id,)
            ).fetchone()

        return self._row_to_summary(row) if row else None

    def get_summaries(
        self,
        topic: Optional[str] = None,
        limit: Optional[int] = None,
        summary_type: Optional[str] = None,
        target_id: Optional[str] = None,
        after: Optional[datetime] = None
    ) -> List[object]:
        """
        Get summaries, dispatching by API:

        - If topic or limit provided → TopicSummary list (F31 API)
        - Otherwise → Summary list (F26 API: cluster/project/period)
        """
        if topic is not None or limit is not None:
            return self.get_topic_summaries(topic=topic, limit=limit or 10)
        return self._get_base_summaries(summary_type=summary_type, target_id=target_id, after=after)

    def _get_base_summaries(
        self,
        summary_type: Optional[str] = None,
        target_id: Optional[str] = None,
        after: Optional[datetime] = None
    ) -> List[Summary]:
        """
        Get cluster/project/period summaries, optionally filtered.

        Args:
            summary_type: Filter by cluster/project/period
            target_id: Filter by cluster_id or project_id
            after: Only summaries created after this date
        """
        query = "SELECT * FROM memory_summaries WHERE 1=1"
        params = []

        if summary_type:
            query += " AND summary_type = ?"
            params.append(summary_type)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        if after:
            query += " AND created_at >= ?"
            params.append(int(after.timestamp()))

        query += " ORDER BY created_at DESC"

        with get_connection(self.intel_db.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._row_to_summary(row) for row in rows]

    def delete_summary(self, summary_id: str) -> bool:
        """Delete a cluster/project/period summary."""
        with get_connection(self.intel_db.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM memory_summaries WHERE id = ?", (summary_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def regenerate_summary(self, summary_id) -> Optional[object]:
        """
        Regenerate a summary by ID.

        - int → regenerates TopicSummary (F31 API)
        - str → regenerates Summary (F26 API: cluster/project/period)
        """
        if isinstance(summary_id, int):
            return self.regenerate_topic_summary(summary_id)
        return self._regenerate_base_summary(summary_id)

    def _regenerate_base_summary(self, summary_id: str) -> Optional[Summary]:
        """Regenerate an existing cluster/project/period summary."""
        existing = self._get_base_summary(summary_id)
        if not existing:
            return None

        self.delete_summary(summary_id)

        if existing.summary_type == "cluster":
            return self.summarize_cluster(existing.target_id)
        elif existing.summary_type == "project":
            if existing.period_start and existing.period_end:
                days = (existing.period_end - existing.period_start).days
                return self.summarize_project(existing.target_id, days=days)
        elif existing.summary_type == "period":
            if existing.period_start and existing.period_end:
                return self.summarize_period(
                    existing.period_start, existing.period_end, existing.target_id
                )
        return None

    def get_summary_statistics(self) -> dict:
        """Return summary statistics by type."""
        with get_connection(self.intel_db.db_path) as conn:
            by_type = dict(conn.execute(
                "SELECT summary_type, COUNT(*) FROM memory_summaries GROUP BY summary_type"
            ).fetchall())

            avg_count = conn.execute(
                "SELECT AVG(memory_count) FROM memory_summaries"
            ).fetchone()[0] or 0

            most_summarized = conn.execute(
                """SELECT target_id, COUNT(*) as count FROM memory_summaries
                   WHERE target_id IS NOT NULL
                   GROUP BY target_id ORDER BY count DESC LIMIT 1"""
            ).fetchone()

        return {
            "total_summaries": sum(by_type.values()),
            "by_type": by_type,
            "average_memory_count": round(avg_count, 1),
            "most_summarized_target": {
                "id": most_summarized[0],
                "count": most_summarized[1]
            } if most_summarized else None
        }

    # ── F31: Topic summarization ──────────────────────────────────────────

    def summarize_topic(
        self,
        topic: str,
        memories: List[Memory],
        save: bool = True
    ) -> TopicSummary:
        """
        Generate narrative summary of memories on a topic.

        Args:
            topic: Topic to summarize
            memories: Memory objects to include
            save: Persist to database

        Returns:
            TopicSummary with narrative, timeline, and key insights
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
            return self._save_topic_summary(summary) if save else summary

        sorted_memories = sorted(memories, key=lambda m: m.created)

        timeline = [
            {"date": m.created.strftime("%Y-%m-%d"), "event": m.content[:100]}
            for m in sorted_memories
        ]

        memory_texts = "\n".join([f"- {m.content}" for m in sorted_memories[:20]])
        prompt = f"""Synthesize these memories about "{topic}" into a coherent narrative.

Memories:
{memory_texts}

Provide:
1. A narrative summary (2-3 paragraphs)
2. 3-5 key insights

Format as JSON:
{{"narrative": "...", "key_insights": ["...", "..."]}}"""

        try:
            response = _ask_claude(prompt, timeout=30)
            data = json.loads(response.strip())
            narrative = data.get("narrative", "Unable to generate summary")
            key_insights = data.get("key_insights", [])
        except Exception:
            narrative = (
                f"Found {len(memories)} memories about {topic}. "
                f"Spanning from {sorted_memories[0].created.strftime('%Y-%m-%d')} "
                f"to {sorted_memories[-1].created.strftime('%Y-%m-%d')}."
            )
            key_insights = [f"{m.content[:100]}..." for m in sorted_memories[:3]]

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
        return self._save_topic_summary(summary) if save else summary

    def get_topic_summaries(
        self,
        topic: Optional[str] = None,
        limit: int = 10
    ) -> List[TopicSummary]:
        """Get topic summaries, optionally filtered by topic."""
        with get_connection(self.intel_db.db_path) as conn:
            if topic:
                rows = conn.execute(
                    """SELECT summary_id, topic, narrative, timeline, key_insights,
                              memory_count, memory_ids, created_at
                       FROM summaries WHERE topic = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (topic, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT summary_id, topic, narrative, timeline, key_insights,
                              memory_count, memory_ids, created_at
                       FROM summaries ORDER BY created_at DESC LIMIT ?""",
                    (limit,)
                ).fetchall()

        return [self._row_to_topic_summary(row) for row in rows]

    def get_topic_summary(self, summary_id: int) -> Optional[TopicSummary]:
        """Get a specific topic summary by ID."""
        results = self.get_topic_summaries()
        return next((s for s in results if s.summary_id == summary_id), None)

    def regenerate_topic_summary(self, summary_id: int) -> Optional[TopicSummary]:
        """Regenerate a topic summary using the same original memory IDs."""
        original = self.get_topic_summary(summary_id)
        if not original:
            return None

        memories = []
        for mem_id in original.memory_ids:
            mem = self.memory_client.get(mem_id)
            if mem:
                memories.append(mem)

        return self.summarize_topic(original.topic, memories, save=True)

    # ── Private helpers ───────────────────────────────────────────────────

    def _create_summary(
        self,
        summary_type: str,
        summary: str,
        memory_count: int,
        target_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> Summary:
        """Create and persist a cluster/project/period summary."""
        summary_id = str(uuid.uuid4())
        now = int(datetime.now().timestamp())

        with get_connection(self.intel_db.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_summaries
                   (id, summary_type, target_id, period_start, period_end, summary, memory_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary_id, summary_type, target_id,
                    int(period_start.timestamp()) if period_start else None,
                    int(period_end.timestamp()) if period_end else None,
                    summary, memory_count, now
                )
            )
            conn.commit()

        return Summary(
            id=summary_id,
            summary_type=summary_type,
            target_id=target_id,
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            memory_count=memory_count,
            created_at=datetime.fromtimestamp(now)
        )

    def _row_to_summary(self, row) -> Summary:
        """Convert database row to Summary object."""
        return Summary(
            id=row[0],
            summary_type=row[1],
            target_id=row[2],
            period_start=datetime.fromtimestamp(row[3]) if row[3] else None,
            period_end=datetime.fromtimestamp(row[4]) if row[4] else None,
            summary=row[5],
            memory_count=row[6],
            created_at=datetime.fromtimestamp(row[7])
        )

    def _save_topic_summary(self, summary: TopicSummary) -> TopicSummary:
        """Persist a topic summary and return it with assigned ID."""
        now = int(time.time())
        with get_connection(self.intel_db.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO summaries
                   (topic, narrative, timeline, key_insights, memory_count, memory_ids, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary.topic,
                    summary.narrative,
                    json.dumps(summary.timeline),
                    json.dumps(summary.key_insights),
                    summary.memory_count,
                    json.dumps(summary.memory_ids),
                    now
                )
            )
            summary.summary_id = cursor.lastrowid
            conn.commit()
        return summary

    def _row_to_topic_summary(self, row) -> TopicSummary:
        """Convert database row to TopicSummary object."""
        return TopicSummary(
            summary_id=row[0],
            topic=row[1],
            narrative=row[2],
            timeline=json.loads(row[3]),
            key_insights=json.loads(row[4]),
            memory_count=row[5],
            memory_ids=json.loads(row[6]),
            created_at=datetime.fromtimestamp(row[7])
        )

    def _generate_cluster_summary(self, cluster_name: str, memories: List[str]) -> str:
        """Generate cluster summary via LLM."""
        try:
            prompt = f"""Analyze these related memories from cluster "{cluster_name}" and generate a summary that captures:
1. The overarching theme (what connects these memories?)
2. Key insights or patterns
3. Notable details or decisions

Memories:
{chr(10).join(f"- {m[:500]}" for m in memories)}

Generate a 2-3 paragraph summary. Be concise but insightful."""
            return _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30).strip()
        except Exception:
            return f"Cluster '{cluster_name}' contains {len(memories)} related memories. Summary unavailable (timeout)."

    def _generate_project_summary(
        self,
        project_id: str,
        memory_contents: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> str:
        """Generate project summary via LLM."""
        date_range = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        try:
            prompt = f"""Summarize progress on project "{project_id}" over {date_range}:

Memories captured:
{chr(10).join(f"- {m}" for m in memory_contents)}

Generate a summary covering:
1. What was accomplished
2. Key decisions made
3. Open questions or blockers
4. Insights or learnings

Format: 3-4 paragraphs, chronological flow where relevant."""
            return _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30).strip()
        except Exception:
            return f"Project '{project_id}' had {len(memory_contents)} memories captured from {date_range}. Summary unavailable (timeout)."

    def _generate_period_summary(
        self,
        memory_contents: List[str],
        start_date: datetime,
        end_date: datetime,
        project_id: Optional[str]
    ) -> str:
        """Generate period summary via LLM."""
        date_range = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        try:
            scope = f"for project '{project_id}'" if project_id else "across all projects"
            prompt = f"""Generate a digest of memories captured {scope} from {date_range}:

Memories:
{chr(10).join(f"- {m}" for m in memory_contents)}

Organize the summary by themes/topics. Include:
1. Highlights (most important captures)
2. Patterns or trends
3. Notable insights

Format: 3-5 bullet points per theme, conversational tone."""
            return _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30).strip()
        except Exception:
            return f"Period {date_range} had {len(memory_contents)} memories captured. Summary unavailable (timeout)."
