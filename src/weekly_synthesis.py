"""
Weekly synthesis - collects promoted memories and generates summary draft

Runs weekly (Friday 5pm via LaunchAgent):
1. Collect recently promoted memories
2. Group by cluster/theme
3. Generate markdown draft for universal-learnings.md
4. Send Pushover notification to Lee for review
"""

import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .fsrs_scheduler import FSRSScheduler
from .memory_ts_client import MemoryTSClient
from .memory_clustering import MemoryClustering


@dataclass
class SynthesisReport:
    """Result of weekly synthesis"""
    promoted_count: int
    cluster_summaries: Dict[str, List[str]]  # cluster_name -> memory_ids
    draft_text: str
    output_path: Optional[str] = None
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class WeeklySynthesis:
    """
    Generates weekly synthesis of promoted memories.

    Collects all promoted memories, groups by cluster theme,
    generates a markdown draft, and optionally sends notification.
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        fsrs_db_path: Optional[Path] = None,
        cluster_db_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        scheduler: Optional[FSRSScheduler] = None,
        memory_client: Optional[MemoryTSClient] = None,
    ):
        """
        Initialize weekly synthesis.

        Args:
            memory_dir: Path to memory-ts memories directory
            fsrs_db_path: Path to FSRS database
            cluster_db_path: Path to cluster database
            output_dir: Directory for synthesis output files
            scheduler: FSRS scheduler instance
            memory_client: Memory-ts client instance
        """
        self.memory_client = memory_client or MemoryTSClient(memory_dir=memory_dir)
        self.scheduler = scheduler or FSRSScheduler(db_path=fsrs_db_path)
        self.clustering = MemoryClustering(
            memory_dir=memory_dir,
            db_path=cluster_db_path,
        )

        if output_dir is None:
            output_dir = Path(__file__).parent.parent / "synthesis"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self) -> SynthesisReport:
        """
        Generate weekly synthesis report.

        Collects promoted memories, clusters them, generates markdown draft.

        Returns:
            SynthesisReport with draft text and metadata
        """
        # Find all promoted memories
        promoted_memories = self.memory_client.search(
            scope="global",
            tags=["#promoted"],
        )

        if not promoted_memories:
            return SynthesisReport(
                promoted_count=0,
                cluster_summaries={},
                draft_text="",
            )

        # Build clusters for grouping
        clusters = self.clustering.build_clusters()

        # Map memory IDs to clusters
        cluster_summaries: Dict[str, List[str]] = defaultdict(list)
        clustered_ids = set()

        for cluster in clusters:
            for mem_id in cluster.memory_ids:
                if any(m.id == mem_id for m in promoted_memories):
                    cluster_summaries[cluster.name].append(mem_id)
                    clustered_ids.add(mem_id)

        # Any promoted memories not in a cluster go to "uncategorized"
        for mem in promoted_memories:
            if mem.id not in clustered_ids:
                cluster_summaries["uncategorized"].append(mem.id)

        # Generate draft markdown
        draft = self._generate_draft(promoted_memories, dict(cluster_summaries))

        # Write to file
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_file = self.output_dir / f"synthesis-{date_str}.md"
        output_file.write_text(draft)

        return SynthesisReport(
            promoted_count=len(promoted_memories),
            cluster_summaries=dict(cluster_summaries),
            draft_text=draft,
            output_path=str(output_file),
        )

    def _generate_draft(
        self,
        promoted_memories: list,
        cluster_summaries: Dict[str, List[str]],
    ) -> str:
        """
        Generate markdown draft for universal-learnings.md update.

        Args:
            promoted_memories: List of promoted Memory objects
            cluster_summaries: Cluster name -> memory ID mapping

        Returns:
            Markdown text
        """
        # Build lookup
        memory_map = {m.id: m for m in promoted_memories}

        lines = [
            f"# Weekly synthesis — {datetime.now().strftime('%Y-%m-%d')}",
            "",
            f"**{len(promoted_memories)} memories promoted this period**",
            "",
        ]

        for cluster_name, mem_ids in sorted(cluster_summaries.items()):
            lines.append(f"## {cluster_name.title()}")
            lines.append("")

            for mem_id in mem_ids:
                mem = memory_map.get(mem_id)
                if mem:
                    lines.append(f"- {mem.content}")

            lines.append("")

        return "\n".join(lines)

    def notify(self, report: SynthesisReport):
        """
        Send Pushover notification about synthesis results.

        Args:
            report: SynthesisReport to notify about
        """
        if report.promoted_count == 0:
            return

        message = (
            f"Weekly memory synthesis: {report.promoted_count} memories promoted. "
            f"Review draft at: {report.output_path}"
        )

        try:
            subprocess.run(
                [
                    "python3",
                    str(Path(__file__).parent.parent.parent / "poke" / "send_poke_pushover.py"),
                    message,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            pass  # Notification failure is non-critical
