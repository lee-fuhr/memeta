"""
Confirmation tracker — closes the memory feedback loop.

Tracks whether surfaced memories were actually helpful by detecting
references in the user's subsequent response. Maintains confirmation_count
and surfaced_count per memory file, enabling the system to learn which
memories deliver value and which are noise.

Design:
- record_surfacing(): called by memory-injection hook after surfacing memories.
  Stores pending confirmations in hook state.
- check_confirmation(): called on the NEXT exchange. Compares user's response
  against pending memory contents using keyword overlap.
- record_confirmation(): writes confirmation/surfacing counts to memory YAML files.
- Query functions: get_most_confirmed(), get_frequently_ignored(), get_confirmation_stats().

Signal detection is intentionally noisy-tolerant: a few false positives
(counting a confirmation that wasn't) are better than false negatives
(missing a real confirmation). The signal compounds over hundreds of sessions.
"""

import re
from datetime import datetime
from pathlib import Path

from memory_system.hook_state import (
    get_session_state,
    load_state,
    save_state,
    update_session_state,
)

# Keywords that signal explicit acknowledgment (independent of memory content)
ACKNOWLEDGMENT_PATTERNS = [
    r"\bright\b",
    r"\byes\b",
    r"\bexactly\b",
    r"\bgood (point|reminder|call)\b",
    r"\bthanks for (the reminder|reminding|surfacing)\b",
    r"\bi forgot about that\b",
    r"\boh (right|yeah)\b",
]

# Stop words to exclude from keyword overlap (too common to be signal)
STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "it", "its",
    "this", "that", "these", "those", "i", "you", "he", "she", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "our", "their", "and", "but", "or", "not", "no", "so", "if",
    "then", "than", "when", "what", "which", "who", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "only", "just", "also", "very", "too", "now",
})

# Minimum keyword overlap ratio to count as confirmation
MIN_OVERLAP_RATIO = 0.15


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, excluding stop words."""
    words = set(re.findall(r"\b[a-z]{3,}\b", text.lower()))
    return words - STOP_WORDS


def _has_acknowledgment(text: str) -> bool:
    """Check if text contains explicit acknowledgment patterns."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in ACKNOWLEDGMENT_PATTERNS)


def record_surfacing(
    memory_ids: list[str],
    user_prompt: str,
    session_id: str,
    state_file: Path | None = None,
) -> None:
    """Record that memories were surfaced, pending confirmation check.

    Called by the memory injection hook after surfacing memories.
    Stores the IDs and context for later comparison.

    Args:
        memory_ids: IDs of memories that were just surfaced.
        user_prompt: The prompt that triggered the surfacing.
        session_id: Current session ID.
        state_file: Path to hook state file.
    """
    session = get_session_state(session_id, state_file)
    pending = session.get("pending_confirmations", [])

    now = datetime.now().isoformat()
    for mid in memory_ids:
        pending.append({
            "memory_id": mid,
            "surfaced_at_prompt": user_prompt,
            "surfaced_at": now,
        })

    update_session_state(
        {"pending_confirmations": pending},
        session_id=session_id,
        state_file=state_file,
    )


def check_confirmation(
    user_response: str,
    memory_contents: dict[str, str],
    session_id: str,
    state_file: Path | None = None,
) -> list[str]:
    """Check if the user's response confirms any pending surfaced memories.

    Compares keyword overlap between user response and each pending memory's
    content. Also checks for explicit acknowledgment patterns.

    Args:
        user_response: The user's latest message.
        memory_contents: Mapping of memory_id -> memory content text.
        session_id: Current session ID.
        state_file: Path to hook state file.

    Returns:
        List of memory IDs that were confirmed (referenced by the user).
    """
    session = get_session_state(session_id, state_file)
    pending = session.get("pending_confirmations", [])

    if not pending:
        return []

    response_keywords = _extract_keywords(user_response)
    has_ack = _has_acknowledgment(user_response)
    confirmed_ids = []

    for entry in pending:
        mid = entry["memory_id"]
        content = memory_contents.get(mid, "")
        if not content:
            continue

        memory_keywords = _extract_keywords(content)
        if not memory_keywords:
            continue

        # Calculate keyword overlap
        overlap = response_keywords & memory_keywords
        overlap_ratio = len(overlap) / len(memory_keywords)

        # Confirm if: significant keyword overlap OR (acknowledgment + any overlap)
        if overlap_ratio >= MIN_OVERLAP_RATIO:
            confirmed_ids.append(mid)
        elif has_ack and len(overlap) >= 1:
            confirmed_ids.append(mid)

    # Clear pending confirmations
    update_session_state(
        {"pending_confirmations": []},
        session_id=session_id,
        state_file=state_file,
    )

    return confirmed_ids


def _parse_frontmatter_simple(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter without requiring PyYAML.

    Returns (metadata_dict, body_content).
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    rest = text[3:].lstrip("\n")
    closing_idx = rest.find("\n---")
    if closing_idx == -1:
        return {}, text

    frontmatter_text = rest[:closing_idx]
    body = rest[closing_idx + 4:].strip()

    meta = {}
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        colon_idx = line.find(":")
        if colon_idx == -1:
            continue
        key = line[:colon_idx].strip()
        value = line[colon_idx + 1:].strip()

        if value.lower() in ("null", "none", "~"):
            meta[key] = None
        elif value.lower() == "true":
            meta[key] = True
        elif value.lower() == "false":
            meta[key] = False
        else:
            try:
                meta[key] = int(value)
            except ValueError:
                try:
                    meta[key] = float(value)
                except ValueError:
                    meta[key] = value

    return meta, body


def _serialize_frontmatter(meta: dict, body: str) -> str:
    """Serialize metadata dict + body back to YAML frontmatter format."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            lines.append(f"{key}: null")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def record_confirmation(
    memory_id: str,
    memory_dir: Path | None = None,
    was_confirmed: bool = True,
) -> None:
    """Update a memory file with confirmation/surfacing data.

    Increments surfaced_count always. Increments confirmation_count and
    updates last_confirmed only if was_confirmed is True.

    Args:
        memory_id: The memory file ID (filename without .md).
        memory_dir: Directory containing memory .md files.
        was_confirmed: Whether the memory was confirmed helpful.
    """
    if memory_dir is None:
        memory_dir = Path.home() / ".local/share/memory/LFI/memories"

    filepath = memory_dir / f"{memory_id}.md"
    if not filepath.exists():
        return

    text = filepath.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter_simple(text)

    # Increment surfaced_count
    surfaced = meta.get("surfaced_count", 0)
    if not isinstance(surfaced, int):
        surfaced = 0
    meta["surfaced_count"] = surfaced + 1

    # Increment confirmation_count if confirmed
    if was_confirmed:
        confirmed = meta.get("confirmation_count", 0)
        if not isinstance(confirmed, int):
            confirmed = 0
        meta["confirmation_count"] = confirmed + 1
        meta["last_confirmed"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    filepath.write_text(_serialize_frontmatter(meta, body), encoding="utf-8")


def get_most_confirmed(
    memory_dir: Path | None = None,
    top_k: int = 10,
) -> list[dict]:
    """Return memories with highest confirmation counts.

    Args:
        memory_dir: Directory containing memory .md files.
        top_k: Maximum results to return.

    Returns:
        List of dicts with id, confirmation_count, surfaced_count, sorted descending.
    """
    if memory_dir is None:
        memory_dir = Path.home() / ".local/share/memory/LFI/memories"

    results = []
    for filepath in memory_dir.glob("*.md"):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter_simple(text)
            count = meta.get("confirmation_count", 0)
            if isinstance(count, int) and count > 0:
                results.append({
                    "id": meta.get("id", filepath.stem),
                    "confirmation_count": count,
                    "surfaced_count": meta.get("surfaced_count", 0),
                })
        except (OSError, UnicodeDecodeError):
            continue

    results.sort(key=lambda x: x["confirmation_count"], reverse=True)
    return results[:top_k]


def get_frequently_ignored(
    memory_dir: Path | None = None,
    min_surfaced: int = 3,
) -> list[dict]:
    """Return memories surfaced frequently but never confirmed.

    These are candidates for importance reduction — the system keeps
    showing them but they never help.

    Args:
        memory_dir: Directory containing memory .md files.
        min_surfaced: Minimum surfacing count to be considered "frequent."

    Returns:
        List of dicts with id, surfaced_count, sorted by surfaced_count descending.
    """
    if memory_dir is None:
        memory_dir = Path.home() / ".local/share/memory/LFI/memories"

    results = []
    for filepath in memory_dir.glob("*.md"):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter_simple(text)
            surfaced = meta.get("surfaced_count", 0)
            confirmed = meta.get("confirmation_count", 0)
            if isinstance(surfaced, int) and surfaced >= min_surfaced and confirmed == 0:
                results.append({
                    "id": meta.get("id", filepath.stem),
                    "surfaced_count": surfaced,
                    "confirmation_count": 0,
                })
        except (OSError, UnicodeDecodeError):
            continue

    results.sort(key=lambda x: x["surfaced_count"], reverse=True)
    return results


def get_confirmation_stats(
    memory_dir: Path | None = None,
) -> dict:
    """Return aggregate confirmation statistics.

    Returns:
        Dict with total_memories, total_confirmations, total_surfacings,
        confirmation_rate, never_confirmed_count.
    """
    if memory_dir is None:
        memory_dir = Path.home() / ".local/share/memory/LFI/memories"

    total = 0
    total_confirmations = 0
    total_surfacings = 0
    never_confirmed = 0

    for filepath in memory_dir.glob("*.md"):
        try:
            text = filepath.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter_simple(text)
            confirmed = meta.get("confirmation_count", 0)
            surfaced = meta.get("surfaced_count", 0)

            if not isinstance(confirmed, int):
                confirmed = 0
            if not isinstance(surfaced, int):
                surfaced = 0

            total += 1
            total_confirmations += confirmed
            total_surfacings += surfaced
            if confirmed == 0 and surfaced > 0:
                never_confirmed += 1
        except (OSError, UnicodeDecodeError):
            continue

    rate = total_confirmations / total_surfacings if total_surfacings > 0 else 0.0

    return {
        "total_memories": total,
        "total_confirmations": total_confirmations,
        "total_surfacings": total_surfacings,
        "confirmation_rate": rate,
        "never_confirmed_count": never_confirmed,
    }
