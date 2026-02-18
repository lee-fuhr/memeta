"""
Memory freshness reviewer — identify and manage stale memories

Scans the memory corpus for memories that haven't been updated recently
and flags them for review. Supports:
  - Identification of stale memories (configurable age threshold)
  - Review queue generation (sorted by importance × staleness)
  - CLI interactive review (refresh / archive / skip)
  - Pushover notification summary
  - Dashboard integration via stale_days filter

Usage:
    # Check what's stale (dry run)
    python -m memory_system.memory_freshness_reviewer --scan

    # Interactive review session
    python -m memory_system.memory_freshness_reviewer --review

    # Send summary notification
    python -m memory_system.memory_freshness_reviewer --notify

    # Full cycle: scan → notify → (user reviews later via CLI or dashboard)
    python -m memory_system.memory_freshness_reviewer --scan --notify

Weekly LaunchAgent: com.lfi.memory-freshness-review (Sundays 9am)
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .memory_ts_client import MemoryTSClient, Memory


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_STALE_DAYS = 90
DEFAULT_MIN_IMPORTANCE = 0.3  # Only flag low-importance stale memories
DEFAULT_MAX_REVIEW = 10  # Max memories per review session
MEMORY_DIR = Path.home() / ".local/share/memory/LFI/memories"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class StaleMemory:
    """A memory flagged for freshness review."""
    memory: Memory
    days_since_update: int
    staleness_score: float  # higher = more urgently needs review

    @property
    def summary(self) -> str:
        preview = self.memory.content[:120].replace("\n", " ")
        return f"[{self.days_since_update}d] {self.memory.knowledge_domain}: {preview}"


@dataclass
class ReviewResult:
    """Outcome of a freshness review session."""
    reviewed: int = 0
    refreshed: int = 0
    archived: int = 0
    skipped: int = 0
    details: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def scan_stale_memories(
    memory_dir: Optional[Path] = None,
    stale_days: int = DEFAULT_STALE_DAYS,
    max_importance: float = DEFAULT_MIN_IMPORTANCE,
    include_all_importance: bool = False,
) -> list[StaleMemory]:
    """Find memories that haven't been updated in stale_days.

    Args:
        memory_dir: Path to memory files
        stale_days: Minimum days since update to flag
        max_importance: Only flag memories with importance <= this
        include_all_importance: If True, ignore importance filter

    Returns:
        List of StaleMemory sorted by staleness_score (highest first)
    """
    client = MemoryTSClient(memory_dir=memory_dir or MEMORY_DIR)
    now = datetime.now(tz=timezone.utc)
    stale = []

    for memory_file in (memory_dir or MEMORY_DIR).glob("*.md"):
        try:
            memory = client._read_memory(memory_file)
        except Exception:
            continue

        if memory.status != "active":
            continue

        # Parse updated timestamp
        days = _days_since(memory.updated, now)
        if days is None:
            days = _days_since(memory.created, now)
        if days is None or days < stale_days:
            continue

        if not include_all_importance and memory.importance > max_importance:
            continue

        # Staleness score: older + less important = higher score
        score = (days / 30.0) * (1.0 - memory.importance)
        stale.append(StaleMemory(memory=memory, days_since_update=days, staleness_score=score))

    stale.sort(key=lambda s: s.staleness_score, reverse=True)
    return stale


def refresh_memory(memory_id: str, memory_dir: Optional[Path] = None) -> Memory:
    """Mark a memory as freshly reviewed — resets updated timestamp."""
    client = MemoryTSClient(memory_dir=memory_dir or MEMORY_DIR)
    return client.update(memory_id, status="active")


def archive_memory(memory_id: str, memory_dir: Optional[Path] = None) -> Memory:
    """Archive a stale memory."""
    client = MemoryTSClient(memory_dir=memory_dir or MEMORY_DIR)
    memory = client.get(memory_id)
    tags = list(memory.tags) if memory.tags else []
    if "#archived" not in tags:
        tags.append("#archived")
    return client.update(memory_id, status="archived", tags=tags)


def generate_review_summary(stale: list[StaleMemory], max_items: int = 5) -> str:
    """Generate a human-readable summary for Pushover notification."""
    if not stale:
        return "All memories are fresh. Nothing to review."

    lines = [f"{len(stale)} memories need freshness review:"]
    for s in stale[:max_items]:
        domain = s.memory.knowledge_domain or "unknown"
        age = s.days_since_update
        imp = s.memory.importance
        preview = s.memory.content[:60].replace("\n", " ").strip()
        lines.append(f"  {age}d · {domain} · {imp:.1f} · {preview}…")

    if len(stale) > max_items:
        lines.append(f"  …and {len(stale) - max_items} more")

    lines.append("")
    lines.append("Review: http://localhost:7860 (Stale filter)")
    lines.append("CLI: python -m memory_system.memory_freshness_reviewer --review")
    return "\n".join(lines)


def send_freshness_notification(summary: str) -> bool:
    """Send Pushover notification with freshness review summary."""
    try:
        poke_path = Path(__file__).parent.parent.parent / "poke" / "send_poke_pushover.py"
        if not poke_path.exists():
            # Try alternate path
            poke_path = Path("/Users/lee/CC/LFI/_ Operations/poke/send_poke_pushover.py")

        if not poke_path.exists():
            print(f"Pushover script not found at {poke_path}", file=sys.stderr)
            return False

        # Import and call directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("send_poke", str(poke_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.send_poke(summary, title="Memory Freshness Review")
        return True
    except Exception as e:
        print(f"Notification failed: {e}", file=sys.stderr)
        return False


def interactive_review(
    stale: list[StaleMemory],
    max_review: int = DEFAULT_MAX_REVIEW,
    memory_dir: Optional[Path] = None,
) -> ReviewResult:
    """Run an interactive CLI review session.

    For each stale memory, shows content and asks: refresh / archive / skip.
    """
    result = ReviewResult()
    to_review = stale[:max_review]

    print(f"\n{'='*60}")
    print(f"Memory freshness review — {len(to_review)} of {len(stale)} stale memories")
    print(f"{'='*60}\n")

    for i, s in enumerate(to_review, 1):
        m = s.memory
        print(f"[{i}/{len(to_review)}] {m.knowledge_domain} · {s.days_since_update}d old · importance {m.importance:.2f}")
        print(f"Tags: {', '.join(m.tags[:5])}")
        print(f"---")
        # Show first 300 chars of content
        preview = m.content[:300].strip()
        print(preview)
        if len(m.content) > 300:
            print("…")
        print()

        while True:
            choice = input("  [r]efresh  [a]rchive  [s]kip  [q]uit → ").strip().lower()
            if choice in ("r", "a", "s", "q"):
                break
            print("  Invalid choice. Use r/a/s/q.")

        if choice == "q":
            print("\nReview session ended early.")
            break
        elif choice == "r":
            refresh_memory(m.id, memory_dir=memory_dir)
            result.refreshed += 1
            result.details.append({"id": m.id, "action": "refreshed"})
            print("  → Refreshed (timestamp updated)\n")
        elif choice == "a":
            archive_memory(m.id, memory_dir=memory_dir)
            result.archived += 1
            result.details.append({"id": m.id, "action": "archived"})
            print("  → Archived\n")
        else:
            result.skipped += 1
            result.details.append({"id": m.id, "action": "skipped"})
            print("  → Skipped\n")

        result.reviewed += 1

    print(f"\n{'='*60}")
    print(f"Review complete: {result.refreshed} refreshed, {result.archived} archived, {result.skipped} skipped")
    print(f"{'='*60}\n")

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_since(timestamp_str: str, now: datetime) -> Optional[int]:
    """Parse a timestamp string and return days since then."""
    if not timestamp_str:
        return None

    # Try epoch milliseconds (integer string)
    try:
        ts = int(timestamp_str)
        if ts > 1e12:
            ts = ts / 1000
        return max(0, int((now.timestamp() - ts) / 86400))
    except (TypeError, ValueError):
        pass

    # Try ISO format
    try:
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((now - dt).total_seconds() / 86400))
    except (TypeError, ValueError):
        pass

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Memory freshness reviewer")
    parser.add_argument("--scan", action="store_true", help="Scan for stale memories and print summary")
    parser.add_argument("--review", action="store_true", help="Interactive review session")
    parser.add_argument("--notify", action="store_true", help="Send Pushover notification")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_DAYS, help=f"Staleness threshold (default: {DEFAULT_STALE_DAYS})")
    parser.add_argument("--all-importance", action="store_true", help="Include high-importance memories too")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_REVIEW, help=f"Max memories to review (default: {DEFAULT_MAX_REVIEW})")
    args = parser.parse_args()

    if not any([args.scan, args.review, args.notify]):
        parser.print_help()
        return

    stale = scan_stale_memories(
        stale_days=args.days,
        include_all_importance=args.all_importance,
    )

    if args.scan:
        print(f"\nFound {len(stale)} stale memories (>{args.days} days, importance ≤{DEFAULT_MIN_IMPORTANCE}):\n")
        for s in stale[:20]:
            print(f"  {s.summary}")
        if len(stale) > 20:
            print(f"  …and {len(stale) - 20} more")
        print()

    if args.notify:
        summary = generate_review_summary(stale)
        if send_freshness_notification(summary):
            print("Notification sent.")
        else:
            print("Notification failed — printing summary instead:")
            print(summary)

    if args.review:
        if not stale:
            print("No stale memories to review.")
            return
        interactive_review(stale, max_review=args.max)


if __name__ == "__main__":
    main()
