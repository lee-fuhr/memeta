"""
Cluster-based morning briefing — surface knowledge clusters at session start.

Reads memory clusters (from clustering.py / intelligence.db) and generates
a concise briefing showing:
  - Top knowledge clusters by size
  - Preview of most relevant memories per cluster
  - Divergence signals (clusters that may need splitting)

Usage:
    from memory_system.cluster_briefing import ClusterBriefing

    cb = ClusterBriefing()
    text = cb.get_formatted_briefing()
    print(text)

    # Or get structured data
    briefing = cb.get_briefing()
    for item in briefing.items:
        print(f"{item.topic}: {item.member_count} memories")
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MEMORY_DIR = Path.home() / ".local/share/memory/LFI/memories"
INTELLIGENCE_DB = Path(__file__).parent / "intelligence.db"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class BriefingItem:
    """One cluster's contribution to the briefing."""
    cluster_id: int
    topic: str
    keywords: list[str]
    member_count: int
    top_memories: list[str]  # memory IDs (highest similarity)
    summary: str  # content preview

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "topic": self.topic,
            "keywords": self.keywords,
            "member_count": self.member_count,
            "top_memories": self.top_memories,
            "summary": self.summary,
        }


@dataclass
class MorningBriefing:
    """Complete morning briefing from cluster data."""
    items: list[BriefingItem]
    divergences: list[str]  # signals about clusters that may need splitting
    generated_at: datetime

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def generate_briefing(
    db_path: Optional[Path] = None,
    memory_dir: Optional[Path] = None,
    max_clusters: int = 10,
    top_n_memories: int = 5,
) -> MorningBriefing:
    """Generate a morning briefing from stored memory clusters.

    Args:
        db_path: Path to intelligence.db
        memory_dir: Path to memory .md files
        max_clusters: Maximum clusters to include
        top_n_memories: Max memories to preview per cluster

    Returns:
        MorningBriefing with items sorted by cluster size (largest first)
    """
    db = db_path or INTELLIGENCE_DB
    mem_dir = memory_dir or MEMORY_DIR

    if not Path(db).exists():
        return MorningBriefing(items=[], divergences=[], generated_at=datetime.now(tz=timezone.utc))

    conn = sqlite3.connect(str(db))
    try:
        # Get all clusters sorted by member_count DESC
        clusters = conn.execute(
            "SELECT cluster_id, topic_label, keywords, member_count "
            "FROM memory_clusters ORDER BY member_count DESC"
        ).fetchall()

        if not clusters:
            return MorningBriefing(items=[], divergences=[], generated_at=datetime.now(tz=timezone.utc))

        items = []
        for cluster_id, topic, keywords_json, member_count in clusters[:max_clusters]:
            keywords = json.loads(keywords_json) if keywords_json else []

            # Get top members by similarity
            members = conn.execute(
                "SELECT memory_id FROM cluster_memberships "
                "WHERE cluster_id = ? ORDER BY similarity_score DESC LIMIT ?",
                (cluster_id, top_n_memories),
            ).fetchall()
            top_ids = [row[0] for row in members]

            # Build summary from memory content previews
            summary = _build_cluster_summary(mem_dir, top_ids)

            items.append(BriefingItem(
                cluster_id=cluster_id,
                topic=topic,
                keywords=keywords,
                member_count=member_count,
                top_memories=top_ids,
                summary=summary,
            ))

        divergences = detect_cluster_divergence(db_path=db)
        return MorningBriefing(
            items=items,
            divergences=divergences,
            generated_at=datetime.now(tz=timezone.utc),
        )
    finally:
        conn.close()


def detect_cluster_divergence(
    db_path: Optional[Path] = None,
    split_threshold: int = 15,
) -> list[str]:
    """Detect clusters that may have diverged and need re-clustering.

    A cluster is flagged if its member count exceeds split_threshold,
    suggesting it may contain multiple sub-topics.

    Args:
        db_path: Path to intelligence.db
        split_threshold: Member count above which to flag

    Returns:
        List of human-readable divergence signals
    """
    db = db_path or INTELLIGENCE_DB
    if not Path(db).exists():
        return []

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT topic_label, member_count FROM memory_clusters "
            "WHERE member_count > ? ORDER BY member_count DESC",
            (split_threshold,),
        ).fetchall()

        signals = []
        for topic, count in rows:
            signals.append(
                f"Your thinking about '{topic}' may have split — "
                f"{count} memories, consider re-clustering."
            )
        return signals
    finally:
        conn.close()


def format_briefing_text(briefing: MorningBriefing) -> str:
    """Format a MorningBriefing as human-readable text.

    Args:
        briefing: The briefing to format

    Returns:
        Formatted string suitable for terminal or notification
    """
    if briefing.is_empty:
        return "No clusters available. Run clustering first to generate a briefing."

    lines = ["Knowledge clusters:"]
    lines.append("")

    for item in briefing.items:
        kw_str = ", ".join(item.keywords[:4]) if item.keywords else ""
        lines.append(f"  {item.topic} ({item.member_count} memories)")
        if kw_str:
            lines.append(f"    Keywords: {kw_str}")
        if item.summary:
            lines.append(f"    {item.summary}")
        lines.append("")

    if briefing.divergences:
        lines.append("Divergence signals:")
        for d in briefing.divergences:
            lines.append(f"  {d}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_cluster_summary(memory_dir: Path, memory_ids: list[str]) -> str:
    """Build a summary string from memory file content previews.

    Reads the first ~100 chars of each memory's body content.
    """
    previews = []
    for mid in memory_ids[:3]:  # limit to 3 for brevity
        fpath = memory_dir / f"{mid}.md"
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text()
            # Extract body after frontmatter
            parts = text.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()
            else:
                body = text.strip()
            preview = body[:100].replace("\n", " ").strip()
            if preview:
                previews.append(preview)
        except Exception:
            continue

    if not previews:
        return ""
    return " | ".join(previews)


# ---------------------------------------------------------------------------
# Main interface class
# ---------------------------------------------------------------------------

class ClusterBriefing:
    """Main interface for cluster-based morning briefings."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
    ):
        self.db_path = db_path or INTELLIGENCE_DB
        self.memory_dir = memory_dir or MEMORY_DIR

    def get_briefing(self, max_clusters: int = 10, top_n_memories: int = 5) -> MorningBriefing:
        """Get structured briefing data."""
        return generate_briefing(
            db_path=self.db_path,
            memory_dir=self.memory_dir,
            max_clusters=max_clusters,
            top_n_memories=top_n_memories,
        )

    def get_formatted_briefing(self, max_clusters: int = 10) -> str:
        """Get human-readable briefing text."""
        briefing = self.get_briefing(max_clusters=max_clusters)
        return format_briefing_text(briefing)
