"""
Daily memory maintenance - Decay, archival, stats, health checks

Runs daily at 3 AM via LaunchAgent:
- Apply decay to all memories (0.99^days since last access)
- Archive low-importance memories (<0.2 threshold)
- Collect stats for dashboard
- Health checks (memory-ts accessible, corruption detection)

Future enhancement: Memory clustering integration
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import time

from .memory_ts_client import MemoryTSClient, MemoryTSError
from .importance_engine import apply_decay


@dataclass
class MaintenanceResult:
    """Result of maintenance run"""
    timestamp: str
    duration_ms: float
    decay_count: int
    archived_count: int
    stats: Dict[str, Any]
    health: Dict[str, Any]


class MaintenanceRunner:
    """
    Daily maintenance runner for memory-ts

    Handles:
    - Decay application (0.99^days)
    - Low-importance archival (<0.2)
    - Stats collection
    - Health checks
    """

    def __init__(self, memory_dir: Optional[Path] = None):
        """
        Initialize maintenance runner

        Args:
            memory_dir: Directory for memory-ts storage
        """
        self.memory_dir = memory_dir
        self.client = MemoryTSClient(memory_dir=memory_dir)

    def run(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run complete maintenance pipeline

        Args:
            dry_run: If True, simulate without applying changes

        Returns:
            MaintenanceResult dict
        """
        start_time = time.time()

        # Apply decay
        decay_count = 0 if dry_run else apply_decay_to_all(self.memory_dir)

        # Archive low importance
        archived_count = 0 if dry_run else archive_low_importance(self.memory_dir)

        # Collect stats
        stats = collect_stats(self.memory_dir)

        # Health check
        health = health_check(self.memory_dir)

        duration_ms = (time.time() - start_time) * 1000

        result = MaintenanceResult(
            timestamp=datetime.now().isoformat(),
            duration_ms=duration_ms,
            decay_count=decay_count,
            archived_count=archived_count,
            stats=stats,
            health=health
        )

        return asdict(result)


def apply_decay_to_all(memory_dir: Optional[Path] = None) -> int:
    """
    Apply decay to all memories based on days since last access

    Formula: new_importance = importance × (0.99 ^ days_since_accessed)

    Args:
        memory_dir: Directory for memory-ts storage

    Returns:
        Number of memories decayed
    """
    client = MemoryTSClient(memory_dir=memory_dir)
    memories = client.search()  # Get all memories

    decayed_count = 0
    now = datetime.now()

    for memory in memories:
        # Calculate days since created (using created as proxy for last access)
        try:
            created_dt = datetime.fromisoformat(memory.created)
            days_since = (now - created_dt).days

            if days_since > 0:
                # Apply decay
                new_importance = apply_decay(memory.importance, days_since)

                if new_importance != memory.importance:
                    client.update(
                        memory.id,
                        importance=new_importance
                    )
                    decayed_count += 1
        except (ValueError, AttributeError):
            # Skip memories with invalid timestamps
            continue

    return decayed_count


def archive_low_importance(
    memory_dir: Optional[Path] = None,
    threshold: float = 0.2
) -> int:
    """
    Archive memories below importance threshold

    Archives by setting status to "archived" and adding #archived tag

    Args:
        memory_dir: Directory for memory-ts storage
        threshold: Importance threshold (default 0.2)

    Returns:
        Number of memories archived
    """
    client = MemoryTSClient(memory_dir=memory_dir)
    memories = client.search()

    archived_count = 0

    for memory in memories:
        if memory.importance < threshold and memory.status == "active":
            # Archive by updating status and adding tag
            tags = memory.tags if memory.tags else []
            if "#archived" not in tags:
                tags.append("#archived")

            client.update(
                memory.id,
                status="archived",
                tags=tags
            )
            archived_count += 1

    return archived_count


def collect_stats(memory_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Collect statistics for dashboard

    Returns dict with:
    - total_memories: Total memory count
    - high_importance_count: Memories with importance >= 0.8
    - avg_importance: Average importance score
    - project_breakdown: Per-project counts
    - tag_distribution: Tag usage counts

    Args:
        memory_dir: Directory for memory-ts storage

    Returns:
        Stats dictionary
    """
    client = MemoryTSClient(memory_dir=memory_dir)
    memories = client.search()

    if len(memories) == 0:
        return {
            "total_memories": 0,
            "high_importance_count": 0,
            "avg_importance": 0,
            "project_breakdown": {},
            "tag_distribution": {}
        }

    # Calculate basic stats
    total = len(memories)
    high_importance = sum(1 for m in memories if m.importance >= 0.8)
    avg_importance = sum(m.importance for m in memories) / total

    # Project breakdown
    project_breakdown = {}
    for memory in memories:
        proj = memory.project_id
        project_breakdown[proj] = project_breakdown.get(proj, 0) + 1

    # Tag distribution
    tag_distribution = {}
    for memory in memories:
        for tag in memory.tags:
            tag_distribution[tag] = tag_distribution.get(tag, 0) + 1

    return {
        "total_memories": total,
        "high_importance_count": high_importance,
        "avg_importance": round(avg_importance, 3),
        "project_breakdown": project_breakdown,
        "tag_distribution": tag_distribution
    }


def health_check(memory_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Perform health checks on memory-ts

    Checks:
    - Memory directory accessible
    - Memory file count
    - Corrupted file detection

    Args:
        memory_dir: Directory for memory-ts storage

    Returns:
        Health status dictionary
    """
    from .memory_ts_client import DEFAULT_MEMORY_DIR

    mem_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR

    # Check accessibility
    accessible = mem_dir.exists() and mem_dir.is_dir()

    if not accessible:
        return {
            "memory_ts_accessible": False,
            "memory_dir": str(mem_dir),
            "memory_file_count": 0,
            "corrupted_files": 0
        }

    # Count memory files
    memory_files = list(mem_dir.glob("*.md"))
    file_count = len(memory_files)

    # Check for corrupted files
    client = MemoryTSClient(memory_dir=memory_dir)
    corrupted_count = 0

    for memory_file in memory_files:
        try:
            # Try to read and validate basic structure
            content = memory_file.read_text()

            # Must have frontmatter markers
            if content.count("---") < 2:
                corrupted_count += 1
                continue

            # Check for required frontmatter fields
            parts = content.split("---", 2)
            if len(parts) < 3:
                corrupted_count += 1
                continue

            frontmatter = parts[1]

            # Required fields that must be present
            required_fields = ["id:", "created:", "project_id:"]
            missing_fields = [field for field in required_fields if field not in frontmatter]

            if missing_fields:
                corrupted_count += 1
                continue

            # Try to parse
            memory = client._read_memory(memory_file)

            # Validate required fields have valid values
            if not memory.id or not memory.content or not memory.project_id:
                corrupted_count += 1

        except (MemoryTSError, Exception):
            corrupted_count += 1

    return {
        "memory_ts_accessible": True,
        "memory_dir": str(mem_dir),
        "memory_file_count": file_count,
        "corrupted_files": corrupted_count
    }


def run_daily_maintenance(
    memory_dir: Optional[Path] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Convenience function for running daily maintenance

    Args:
        memory_dir: Directory for memory-ts storage
        dry_run: If True, simulate without applying changes

    Returns:
        MaintenanceResult dict
    """
    runner = MaintenanceRunner(memory_dir=memory_dir)
    return runner.run(dry_run=dry_run)


