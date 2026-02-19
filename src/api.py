"""
Unified API for the memory system.

Single entry point that orchestrates all subsystems:
- MemoryTSClient (CRUD)
- Hybrid search (semantic + BM25)
- Contradiction detection
- Confidence scoring
- Daily maintenance

Usage:
    from memory_system.api import MemorySystem

    ms = MemorySystem()
    ms.save("prefers dark mode", tags=["#pref"], importance=0.8)
    results = ms.search("dark mode")
    recent = ms.get_recent(10)
    stats = ms.get_stats()
    ms.run_maintenance()
"""

import argparse
import json
import logging
import sys
import time
from typing import List, Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

from .memory_ts_client import MemoryTSClient, Memory
from .config import cfg


class MemorySystem:
    """Unified API for the memory system. Orchestrates all subsystems."""

    def __init__(self, memory_dir: Optional[Path] = None, project_id: str = "default"):
        self.client = MemoryTSClient(memory_dir=memory_dir)
        self.project_id = project_id
        self._memory_dir = memory_dir
        self._cache = None
        self._cache_time = 0.0
        self._cache_ttl = 5.0  # seconds

    def _list_memories(self):
        """Cached memory listing with 5-second TTL."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache
        self._cache = self.client.list()
        self._cache_time = now
        return self._cache

    def _invalidate_cache(self):
        """Invalidate the memory cache (call after writes)."""
        self._cache = None
        self._cache_time = 0.0

    def save(
        self,
        content: str,
        project_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[float] = None,
        session_id: Optional[str] = None,
        check_contradictions: bool = True,
        **kwargs,
    ) -> Memory:
        """
        Save a memory with full pipeline:
        1. Check for contradictions against existing memories (optional)
        2. If contradiction found with action='replace', archive the old memory
        3. Save via MemoryTSClient.create()
        4. Return the saved Memory

        Args:
            content: Memory content (markdown text)
            project_id: Project identifier (defaults to self.project_id)
            tags: List of tags (e.g. ["#pref", "#learning"])
            importance: Importance score 0.0-1.0 (auto-calculated if None)
            session_id: Session ID for provenance tracking
            check_contradictions: If True, check for contradictions before saving
            **kwargs: Additional fields passed to MemoryTSClient.create()

        Returns:
            Created Memory object
        """
        resolved_project = project_id or self.project_id
        resolved_tags = tags if tags is not None else []

        # Step 1: contradiction check
        if check_contradictions:
            try:
                from .contradiction_detector import check_contradictions as _check

                existing = self._list_memories()
                existing_dicts = [
                    {"id": m.id, "content": m.content} for m in existing
                ]

                if existing_dicts:
                    result = _check(content, existing_dicts)

                    # Step 2: archive contradicted memory if action is 'replace'
                    if result.contradicts and result.action == "replace":
                        contradicted = result.contradicted_memory
                        if contradicted and "id" in contradicted:
                            self.client.archive(
                                contradicted["id"], reason="contradicted"
                            )
            except Exception:
                # Contradiction check is best-effort; don't block save
                logger.debug("Contradiction check failed (best-effort)", exc_info=True)

        # Step 3: save
        memory = self.client.create(
            content=content,
            project_id=resolved_project,
            tags=resolved_tags,
            importance=importance,
            source_session_id=session_id,
            **kwargs,
        )

        self._invalidate_cache()
        return memory

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """
        Search memories using hybrid search (70% semantic + 30% BM25).

        Falls back to BM25-only when semantic search is unavailable.

        Args:
            query: Natural language search query
            top_k: Max results to return

        Returns:
            List of dicts with memory data + scores
        """
        from .hybrid_search import hybrid_search

        all_memories = self._list_memories()
        if not all_memories:
            return []

        memory_dicts = [
            {
                "id": m.id,
                "content": m.content,
                "importance": m.importance,
                "tags": m.tags,
                "project_id": m.project_id,
                "created": m.created,
                "updated": m.updated,
                "confidence_score": m.confidence_score,
            }
            for m in all_memories
        ]

        return hybrid_search(
            query=query,
            memories=memory_dicts,
            top_k=top_k,
            use_semantic=False,  # BM25-only by default for speed/portability
        )

    def get_recent(self, n: int = 10) -> List[Memory]:
        """
        Get N most recently created memories, sorted by created date descending.

        Args:
            n: Number of memories to return

        Returns:
            List of Memory objects, newest first
        """
        all_memories = self._list_memories()
        sorted_memories = sorted(
            all_memories, key=lambda m: m.created, reverse=True
        )
        return sorted_memories[:n]

    def get_stats(self) -> Dict[str, Any]:
        """
        Return system stats.

        Returns:
            Dict with:
            - total_memories: int
            - avg_importance: float
            - confidence_distribution: dict (from get_confidence_stats)
            - tag_counts: dict
            - project_counts: dict
        """
        from .confidence_scoring import get_confidence_stats

        all_memories = self._list_memories()

        if not all_memories:
            return {
                "total_memories": 0,
                "avg_importance": 0.0,
                "confidence_distribution": get_confidence_stats([]),
                "tag_counts": {},
                "project_counts": {},
            }

        # Average importance
        total = len(all_memories)
        avg_importance = sum(m.importance for m in all_memories) / total

        # Confidence distribution
        memory_dicts = [
            {"confidence_score": m.confidence_score} for m in all_memories
        ]
        confidence_dist = get_confidence_stats(memory_dicts)

        # Tag counts
        tag_counts: Dict[str, int] = {}
        for m in all_memories:
            for tag in m.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Project counts
        project_counts: Dict[str, int] = {}
        for m in all_memories:
            project_counts[m.project_id] = project_counts.get(m.project_id, 0) + 1

        return {
            "total_memories": total,
            "avg_importance": round(avg_importance, 3),
            "confidence_distribution": confidence_dist,
            "tag_counts": tag_counts,
            "project_counts": project_counts,
        }

    def run_maintenance(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Run daily maintenance (decay, archival, stats).

        Args:
            dry_run: If True, simulate without applying changes

        Returns:
            MaintenanceResult dict
        """
        from .daily_memory_maintenance import MaintenanceRunner

        runner = MaintenanceRunner(memory_dir=self._memory_dir)
        return runner.run(dry_run=dry_run)


def main():
    """CLI entry point for the memory system API."""
    parser = argparse.ArgumentParser(
        prog="memory_system.api",
        description="Unified CLI for the memory system",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # save
    save_parser = subparsers.add_parser("save", help="Save a new memory")
    save_parser.add_argument("content", help="Memory content")
    save_parser.add_argument(
        "--tags", nargs="*", default=[], help="Tags (e.g. #pref #learning)"
    )
    save_parser.add_argument(
        "--importance", type=float, default=None, help="Importance (0.0-1.0)"
    )
    save_parser.add_argument(
        "--project", default=None, help="Project ID"
    )
    save_parser.add_argument(
        "--session-id", default=None, help="Session ID for provenance"
    )
    save_parser.add_argument(
        "--no-contradiction-check",
        action="store_true",
        help="Skip contradiction checking",
    )

    # search
    search_parser = subparsers.add_parser("search", help="Search memories")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--top-k", type=int, default=10, help="Max results"
    )

    # recent
    recent_parser = subparsers.add_parser(
        "recent", help="Get recent memories"
    )
    recent_parser.add_argument(
        "--count", type=int, default=10, help="Number of memories"
    )

    # stats
    subparsers.add_parser("stats", help="Show system stats")

    # maintain
    maintain_parser = subparsers.add_parser(
        "maintain", help="Run maintenance"
    )
    maintain_parser.add_argument(
        "--dry-run", action="store_true", help="Simulate without changes"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    ms = MemorySystem()

    if args.command == "save":
        memory = ms.save(
            content=args.content,
            project_id=args.project,
            tags=args.tags,
            importance=args.importance,
            session_id=args.session_id,
            check_contradictions=not args.no_contradiction_check,
        )
        print(f"Saved memory {memory.id}")
        print(f"  Content: {memory.content[:80]}")
        print(f"  Tags: {memory.tags}")
        print(f"  Importance: {memory.importance}")

    elif args.command == "search":
        results = ms.search(args.query, top_k=args.top_k)
        if not results:
            print("No results found.")
        else:
            for i, r in enumerate(results, 1):
                score = r.get("hybrid_score", 0)
                content = r.get("content", "")[:80]
                print(f"{i}. [{score:.3f}] {content}")

    elif args.command == "recent":
        memories = ms.get_recent(n=args.count)
        if not memories:
            print("No memories found.")
        else:
            for m in memories:
                print(f"  [{m.created[:10]}] {m.content[:80]}")

    elif args.command == "stats":
        stats = ms.get_stats()
        print(json.dumps(stats, indent=2))

    elif args.command == "maintain":
        result = ms.run_maintenance(dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
