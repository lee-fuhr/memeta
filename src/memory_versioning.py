"""
Memory versioning - Track memory evolution over time.

Feature 23: Store edit history for each memory.
Enables rollback, diff view, "why did this change?" queries.
"""

import json
import time
from typing import List, Dict, Optional
from pathlib import Path


def create_version(
    memory_id: str,
    content: str,
    importance: float,
    changed_by: str = "user",
    change_reason: Optional[str] = None
) -> Dict:
    """
    Create a new version entry for a memory.

    Args:
        memory_id: Memory identifier
        content: Memory content at this version
        importance: Importance score
        changed_by: Who made the change (user | llm | system)
        change_reason: Why it changed (optional)

    Returns:
        Version dict
    """
    return {
        'version': int(time.time() * 1000),
        'memory_id': memory_id,
        'content': content,
        'importance': importance,
        'changed_by': changed_by,
        'change_reason': change_reason,
        'timestamp': int(time.time())
    }


def get_version_history(memory_id: str, version_dir: Path) -> List[Dict]:
    """Get all versions of a memory, sorted oldest to newest."""
    version_file = version_dir / f"{memory_id}.json"

    if not version_file.exists():
        return []

    with open(version_file) as f:
        versions = json.load(f)

    return sorted(versions, key=lambda v: v['version'])


def rollback_to_version(memory_id: str, version_number: int, version_dir: Path) -> Optional[Dict]:
    """Rollback memory to specific version."""
    history = get_version_history(memory_id, version_dir)

    for version in history:
        if version['version'] == version_number:
            return version

    return None


def diff_versions(version_a: Dict, version_b: Dict) -> Dict:
    """Show differences between two versions."""
    return {
        'content_changed': version_a['content'] != version_b['content'],
        'importance_changed': version_a['importance'] != version_b['importance'],
        'content_diff': {
            'before': version_a['content'],
            'after': version_b['content']
        },
        'importance_diff': {
            'before': version_a['importance'],
            'after': version_b['importance']
        },
        'time_between': version_b['timestamp'] - version_a['timestamp']
    }
