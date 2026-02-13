"""
Feature 26: Memory Summarization

LLM-powered summarization of memories.

Three types of summaries:
- Cluster summaries: What's this group of related memories about?
- Project summaries: What happened in this project over time period?
- Period summaries: What was captured this week/month?

Use cases:
- Quick overview of clusters
- Project retrospectives
- Weekly/monthly memory digests
- Session consolidation summaries
"""

import sqlite3
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from intelligence_db import IntelligenceDB
from memory_ts_client import MemoryTSClient


# Dynamic import to avoid issues
def _ask_claude(prompt: str, model: str = "sonnet", temperature: float = 0.3, timeout: int = 30) -> str:
    """Wrapper for ask_claude import"""
    import llm_extractor
    return llm_extractor.ask_claude(prompt, timeout=timeout)


@dataclass
class Summary:
    """A generated summary of memories"""
    id: str
    summary_type: str  # cluster, project, period
    target_id: Optional[str]  # cluster_id or project_id
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    summary: str  # The actual summary text
    memory_count: int
    created_at: datetime


class MemorySummarizer:
    """
    LLM-powered summarization of memories.

    Generates three types of summaries:
    - Cluster summaries: What's this group of related memories about?
    - Project summaries: What happened in this project over time period?
    - Period summaries: What was captured this week/month?
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

    def summarize_cluster(self, cluster_id: str) -> Optional[Summary]:
        """
        Generate summary of a memory cluster.

        Algorithm:
        1. Get all memories in cluster (from memory_clusters table)
        2. Sample up to 20 memories (or all if < 20)
        3. LLM synthesizes: theme, key points, patterns
        4. Store summary with cluster_id reference

        Args:
            cluster_id: Cluster identifier from memory_clusters table

        Returns:
            Summary object or None if cluster not found
        """
        # Get cluster from intelligence.db
        cursor = self.intel_db.conn.cursor()
        cursor.execute("""
            SELECT id, name, memory_ids
            FROM memory_clusters
            WHERE id = ?
        """, (cluster_id,))

        row = cursor.fetchone()
        if not row:
            return None

        cluster_name = row[1]
        memory_ids = json.loads(row[2])

        if not memory_ids:
            # Empty cluster
            summary_text = f"Cluster '{cluster_name}' contains no memories."
            return self._create_summary(
                summary_type="cluster",
                target_id=cluster_id,
                summary=summary_text,
                memory_count=0
            )

        # Get memory contents
        memories = []
        for mem_id in memory_ids[:20]:  # Sample up to 20
            memory = self.memory_client.get(mem_id)
            if memory:
                memories.append(memory.content)

        if not memories:
            summary_text = f"Cluster '{cluster_name}' memories not found."
            return self._create_summary(
                summary_type="cluster",
                target_id=cluster_id,
                summary=summary_text,
                memory_count=0
            )

        # Generate summary via LLM
        summary_text = self._generate_cluster_summary(cluster_name, memories)

        # Store and return
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

        Algorithm:
        1. Get all memories for project in date range
        2. Group by week if >50 memories (hierarchical summary)
        3. LLM synthesizes: progress, decisions, blockers, insights
        4. Store summary with project_id + date range

        Args:
            project_id: Project identifier
            days: Number of days to look back (default: 30)
            min_memories: Minimum memories needed for summary (default: 5)

        Returns:
            Summary or None if insufficient memories
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Get memories for project in date range
        memories = self.memory_client.search(project_id=project_id, limit=10000)

        # Filter by date
        period_memories = [
            m for m in memories
            if hasattr(m, 'created_at') and
            start_date <= m.created_at <= end_date
        ]

        if len(period_memories) < min_memories:
            return None

        # Extract contents (with dates)
        memory_contents = []
        for m in period_memories[:50]:  # Sample up to 50
            date_str = m.created_at.strftime("%Y-%m-%d")
            memory_contents.append(f"[{date_str}] {m.content[:500]}")

        # Generate summary via LLM
        summary_text = self._generate_project_summary(
            project_id,
            memory_contents,
            start_date,
            end_date
        )

        # Store and return
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

        Algorithm:
        1. Get all memories in date range (optionally filtered by project)
        2. Group by theme/cluster if available
        3. LLM synthesizes: highlights, patterns, insights
        4. Store summary with date range

        Args:
            start: Period start date
            end: Period end date
            project_id: Optional project filter

        Returns:
            Summary or None if no memories
        """
        # Ensure start < end
        if start > end:
            start, end = end, start

        # Get memories
        if project_id:
            memories = self.memory_client.search(project_id=project_id, limit=10000)
        else:
            memories = self.memory_client.search(content="", limit=10000)

        # Filter by date
        period_memories = [
            m for m in memories
            if hasattr(m, 'created_at') and
            start <= m.created_at <= end
        ]

        if not period_memories:
            return None

        # Extract contents
        memory_contents = []
        for m in period_memories[:30]:  # Sample up to 30
            memory_contents.append(m.content[:500])

        # Generate summary via LLM
        summary_text = self._generate_period_summary(
            memory_contents,
            start,
            end,
            project_id
        )

        # Store and return
        return self._create_summary(
            summary_type="period",
            target_id=project_id,
            period_start=start,
            period_end=end,
            summary=summary_text,
            memory_count=len(period_memories)
        )

    def get_summary(self, summary_id: str) -> Optional[Summary]:
        """Retrieve summary by ID"""
        cursor = self.intel_db.conn.cursor()
        cursor.execute("""
            SELECT id, summary_type, target_id, period_start, period_end,
                   summary, memory_count, created_at
            FROM memory_summaries
            WHERE id = ?
        """, (summary_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_summary(row)

    def get_summaries(
        self,
        summary_type: Optional[str] = None,
        target_id: Optional[str] = None,
        after: Optional[datetime] = None
    ) -> List[Summary]:
        """
        Get summaries filtered by type, target, or date.

        Args:
            summary_type: Filter by cluster/project/period
            target_id: Filter by cluster_id or project_id
            after: Only summaries created after this date

        Returns:
            List of matching summaries
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

        cursor = self.intel_db.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_summary(row) for row in rows]

    def delete_summary(self, summary_id: str) -> bool:
        """Delete a summary (memories remain unchanged)"""
        cursor = self.intel_db.conn.cursor()
        cursor.execute("DELETE FROM memory_summaries WHERE id = ?", (summary_id,))
        self.intel_db.conn.commit()
        return cursor.rowcount > 0

    def regenerate_summary(self, summary_id: str) -> Optional[Summary]:
        """
        Regenerate an existing summary.
        Useful when memories have been added since last summary.
        """
        # Get existing summary
        existing = self.get_summary(summary_id)
        if not existing:
            return None

        # Delete old summary
        self.delete_summary(summary_id)

        # Regenerate based on type
        if existing.summary_type == "cluster":
            return self.summarize_cluster(existing.target_id)
        elif existing.summary_type == "project":
            if existing.period_start and existing.period_end:
                days = (existing.period_end - existing.period_start).days
                return self.summarize_project(existing.target_id, days=days)
        elif existing.summary_type == "period":
            if existing.period_start and existing.period_end:
                return self.summarize_period(
                    existing.period_start,
                    existing.period_end,
                    existing.target_id
                )

        return None

    def get_summary_statistics(self) -> dict:
        """
        Return summary statistics:
        - Total summaries by type
        - Average memory count per summary
        - Most summarized cluster/project
        """
        cursor = self.intel_db.conn.cursor()

        # Total by type
        cursor.execute("""
            SELECT summary_type, COUNT(*)
            FROM memory_summaries
            GROUP BY summary_type
        """)
        by_type = dict(cursor.fetchall())

        # Average memory count
        cursor.execute("SELECT AVG(memory_count) FROM memory_summaries")
        avg_count = cursor.fetchone()[0] or 0

        # Most summarized target
        cursor.execute("""
            SELECT target_id, COUNT(*) as count
            FROM memory_summaries
            WHERE target_id IS NOT NULL
            GROUP BY target_id
            ORDER BY count DESC
            LIMIT 1
        """)
        most_summarized = cursor.fetchone()

        return {
            "total_summaries": sum(by_type.values()),
            "by_type": by_type,
            "average_memory_count": round(avg_count, 1),
            "most_summarized_target": {
                "id": most_summarized[0],
                "count": most_summarized[1]
            } if most_summarized else None
        }

    # === Private Helper Methods ===

    def _create_summary(
        self,
        summary_type: str,
        summary: str,
        memory_count: int,
        target_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> Summary:
        """Create and store a summary"""
        summary_id = str(uuid.uuid4())
        now = int(datetime.now().timestamp())

        cursor = self.intel_db.conn.cursor()
        cursor.execute("""
            INSERT INTO memory_summaries
            (id, summary_type, target_id, period_start, period_end, summary, memory_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            summary_id,
            summary_type,
            target_id,
            int(period_start.timestamp()) if period_start else None,
            int(period_end.timestamp()) if period_end else None,
            summary,
            memory_count,
            now
        ))
        self.intel_db.conn.commit()

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
        """Convert database row to Summary object"""
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

    def _generate_cluster_summary(self, cluster_name: str, memories: List[str]) -> str:
        """Generate cluster summary via LLM"""
        try:
            prompt = f"""Analyze these related memories from cluster "{cluster_name}" and generate a summary that captures:
1. The overarching theme (what connects these memories?)
2. Key insights or patterns
3. Notable details or decisions

Memories:
{chr(10).join(f"- {m[:500]}" for m in memories)}

Generate a 2-3 paragraph summary. Be concise but insightful."""

            summary = _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30)
            return summary.strip()

        except Exception as e:
            # Fallback summary
            return f"Cluster '{cluster_name}' contains {len(memories)} related memories. Summary unavailable (timeout)."

    def _generate_project_summary(
        self,
        project_id: str,
        memory_contents: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> str:
        """Generate project summary via LLM"""
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

            summary = _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30)
            return summary.strip()

        except Exception as e:
            # Fallback summary
            return f"Project '{project_id}' had {len(memory_contents)} memories captured from {date_range}. Summary unavailable (timeout)."

    def _generate_period_summary(
        self,
        memory_contents: List[str],
        start_date: datetime,
        end_date: datetime,
        project_id: Optional[str]
    ) -> str:
        """Generate period summary via LLM"""
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

            summary = _ask_claude(prompt, model="sonnet", temperature=0.3, timeout=30)
            return summary.strip()

        except Exception as e:
            # Fallback summary
            return f"Period {date_range} had {len(memory_contents)} memories captured. Summary unavailable (timeout)."
