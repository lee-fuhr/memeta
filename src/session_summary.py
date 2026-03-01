"""
Session summary module — "Where was I?" resumption cards.

Extracts structured summaries from Claude Code session transcripts using
simple heuristics (no LLM). Summaries are stored as JSON and rendered as
prose resumption cards at session start.

Architecture:
- Structured JSON at ~/.claude/session-summaries/{session_id}.json
- Five fields: session_id, summary, open_questions, files_touched, generated_at
- Written at session end by the consolidation hook
- Read at session start by session-context.py
"""

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SUMMARIES_DIR = Path.home() / ".claude" / "session-summaries"
MAX_SUMMARY_LENGTH = 200  # chars for summary field
MAX_FILES_TRACKED = 10  # max files in files_touched list
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024  # 2 MB — only parse tail of large transcripts

# Patterns that indicate open questions or unfinished work
_QUESTION_MARKERS = re.compile(
    r"(?:^|\s)(?:TODO|FIXME|HACK|need to|should we|open question)",
    re.IGNORECASE,
)

# File path patterns to extract from transcript text
_FILE_PATH_RE = re.compile(
    r"""
    (?:                         # Absolute paths
        /(?:Users|home|tmp|var|etc|opt)
        /[^\s"'`,;:)\]}>]+     # Continue until whitespace or delimiter
    )
    |
    (?:                         # Relative paths with common prefixes
        (?:src|tests|lib|bin|scripts|docs|hooks|dashboard|config)
        /[^\s"'`,;:)\]}>]+     # Continue until whitespace or delimiter
    )
    |
    (?:                         # Files with common extensions (standalone)
        \b[\w./-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|sh|sql|css|html)
        \b
    )
    """,
    re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def get_summaries_dir(path: Path | None = None) -> Path:
    """Return the summaries directory, creating it if needed.

    Args:
        path: Override directory. Defaults to DEFAULT_SUMMARIES_DIR.

    Returns:
        Path to the summaries directory.
    """
    target = path if path is not None else DEFAULT_SUMMARIES_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def _parse_transcript(transcript: str) -> list[dict]:
    """Parse a JSONL session transcript into a list of message dicts.

    Each returned dict has:
        role: "human" | "assistant"
        text: str (substantive text content only, tool blocks stripped)

    Skips malformed lines silently.
    """
    messages: list[dict] = []
    if not transcript or not transcript.strip():
        return messages

    for line in transcript.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type", "")
        message = obj.get("message", {})
        content = message.get("content", "")

        if msg_type == "human":
            if isinstance(content, str) and content.strip():
                messages.append({"role": "human", "text": content.strip()})
        elif msg_type == "assistant":
            if isinstance(content, list):
                # Extract only text blocks, skip tool_use / tool_result
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            text_parts.append(text)
                if text_parts:
                    messages.append({
                        "role": "assistant",
                        "text": " ".join(text_parts),
                    })
            elif isinstance(content, str) and content.strip():
                messages.append({"role": "assistant", "text": content.strip()})

    return messages


def _extract_summary_text(messages: list[dict]) -> str:
    """Build a summary string from the last substantive messages.

    Takes the last ~20 messages, concatenates their text, then extracts
    key topic sentences from the last 2000 chars.
    """
    if not messages:
        return ""

    # Focus on last 20 messages
    recent = messages[-20:]
    combined = " ".join(m["text"] for m in recent)

    # Take last 2000 chars of non-tool content
    tail = combined[-2000:] if len(combined) > 2000 else combined

    # Extract key sentences (first sentence from each message in recent tail)
    sentences = []
    for m in recent[-5:]:
        text = m["text"]
        # Take first sentence
        first_sentence = re.split(r"[.!?\n]", text)[0].strip()
        if first_sentence and len(first_sentence) > 10:
            sentences.append(first_sentence)

    if sentences:
        result = ". ".join(sentences)
    else:
        # Fallback: just use the tail text
        result = tail.strip()

    # Truncate to MAX_SUMMARY_LENGTH
    if len(result) > MAX_SUMMARY_LENGTH:
        result = result[: MAX_SUMMARY_LENGTH - 3].rstrip() + "..."
    return result


def _extract_open_questions(messages: list[dict]) -> list[str]:
    """Find open questions and TODOs in the transcript.

    Looks for:
    - Lines containing "?"
    - Lines matching TODO/need to/should we/open question patterns
    """
    questions: list[str] = []
    seen: set[str] = set()

    # Focus on last portion of messages
    recent = messages[-20:]

    for m in recent:
        text = m["text"]
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) < 10:
                continue

            is_question = "?" in line
            is_marker = bool(_QUESTION_MARKERS.search(line))

            if is_question or is_marker:
                # Clean up the line
                clean = line[:200].strip()
                if clean not in seen:
                    seen.add(clean)
                    questions.append(clean)

    return questions


def _extract_files_touched(messages: list[dict]) -> list[str]:
    """Extract file paths mentioned in the transcript.

    Looks for absolute paths, relative paths with common prefixes,
    and files with common extensions.
    """
    files: list[str] = []
    seen: set[str] = set()

    for m in messages:
        matches = _FILE_PATH_RE.findall(m["text"])
        for match in matches:
            # Clean up trailing punctuation
            clean = match.rstrip(".,;:!?)>]}'\"")
            if clean and clean not in seen:
                seen.add(clean)
                files.append(clean)

    # Limit to MAX_FILES_TRACKED, preferring later (more recent) mentions
    if len(files) > MAX_FILES_TRACKED:
        files = files[-MAX_FILES_TRACKED:]

    return files


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def generate_summary(
    session_transcript: str,
    session_id: str | None = None,
) -> dict:
    """Extract a structured summary from a session transcript.

    Uses simple heuristics (not LLM) to extract:
    - summary: Key topics from last ~5 substantive messages
    - open_questions: Lines with ?, TODO, need to, etc.
    - files_touched: File paths mentioned in transcript
    - generated_at: ISO 8601 timestamp

    Args:
        session_transcript: JSONL string of the session transcript.
        session_id: Optional session identifier. Generated if None.

    Returns:
        Dict with session_id, summary, open_questions, files_touched, generated_at.
    """
    if session_id is None:
        session_id = uuid.uuid4().hex[:16]

    # Guard against huge transcripts (sessions can be 100MB+).
    # Heuristic extractors only look at the last ~20 messages, so
    # keeping the tail is sufficient and prevents OOM / timeout.
    if len(session_transcript) > MAX_TRANSCRIPT_BYTES:
        session_transcript = session_transcript[-MAX_TRANSCRIPT_BYTES:]
        # Find the first complete JSONL line boundary after truncation
        first_newline = session_transcript.find("\n")
        if first_newline != -1:
            session_transcript = session_transcript[first_newline + 1:]

    messages = _parse_transcript(session_transcript)

    return {
        "session_id": session_id,
        "summary": _extract_summary_text(messages),
        "open_questions": _extract_open_questions(messages),
        "files_touched": _extract_files_touched(messages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_summary(
    summary: dict,
    session_id: str | None = None,
    summaries_dir: Path | None = None,
) -> Path:
    """Save a summary dict as JSON with atomic write.

    Uses .tmp + rename for crash safety.

    Args:
        summary: The summary dict to persist.
        session_id: Filename stem. Falls back to summary["session_id"].
        summaries_dir: Target directory. Defaults to DEFAULT_SUMMARIES_DIR.

    Returns:
        Path to the written file.
    """
    sid = session_id or summary.get("session_id", uuid.uuid4().hex[:16])
    target_dir = get_summaries_dir(summaries_dir)
    target_path = target_dir / f"{sid}.json"

    # Atomic write: write to .tmp then rename
    tmp_path = target_path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        tmp_path.replace(target_path)
    except Exception:
        # Clean up temp file on failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return target_path


def load_summary(
    session_id: str,
    summaries_dir: Path | None = None,
) -> dict | None:
    """Load a summary by session ID.

    Args:
        session_id: The session identifier (filename stem).
        summaries_dir: Directory to search. Defaults to DEFAULT_SUMMARIES_DIR.

    Returns:
        The summary dict, or None if missing or corrupt.
    """
    target_dir = summaries_dir if summaries_dir is not None else DEFAULT_SUMMARIES_DIR
    target_path = target_dir / f"{session_id}.json"

    if not target_path.exists():
        return None

    try:
        data = json.loads(target_path.read_text())
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def get_latest_summary(
    summaries_dir: Path | None = None,
) -> dict | None:
    """Return the most recently generated summary.

    Scans all .json files in the summaries directory and returns the one
    with the newest generated_at timestamp.

    Args:
        summaries_dir: Directory to scan. Defaults to DEFAULT_SUMMARIES_DIR.

    Returns:
        The newest summary dict, or None if no valid summaries exist.
    """
    target_dir = summaries_dir if summaries_dir is not None else DEFAULT_SUMMARIES_DIR
    if not target_dir.exists():
        return None

    newest: dict | None = None
    newest_ts: str = ""

    for path in target_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                continue
            ts = data.get("generated_at", "")
            if ts > newest_ts:
                newest_ts = ts
                newest = data
        except (json.JSONDecodeError, OSError):
            continue

    return newest


def format_resumption_card(summary: dict) -> str:
    """Format a summary as a human-readable resumption card.

    Produces a markdown block suitable for injection into session context.

    Args:
        summary: The summary dict.

    Returns:
        Formatted string.
    """
    session_id = summary.get("session_id", "unknown")
    generated_at = summary.get("generated_at", "unknown")
    summary_text = summary.get("summary", "No summary available.")
    open_questions = summary.get("open_questions", [])
    files_touched = summary.get("files_touched", [])

    # Truncate session_id for display
    sid_display = session_id[:12] if len(session_id) > 12 else session_id

    lines = [
        "# Project state",
        f"**Last session:** {generated_at} `{sid_display}`",
        f"**What was done:** {summary_text or 'No summary available.'}",
    ]

    if open_questions:
        lines.append(f"**Open questions:** {'; '.join(open_questions)}")
    else:
        lines.append("**Open questions:** None")

    if files_touched:
        lines.append(f"**Files touched:** {', '.join(files_touched)}")

    return "\n".join(lines)


def cleanup_old_summaries(
    summaries_dir: Path | None = None,
    max_age_days: int = 30,
) -> int:
    """Remove summary files older than max_age_days.

    Uses file modification time (mtime) for age calculation.

    Args:
        summaries_dir: Directory to clean. Defaults to DEFAULT_SUMMARIES_DIR.
        max_age_days: Maximum age in days before removal.

    Returns:
        Number of files removed.
    """
    target_dir = summaries_dir if summaries_dir is not None else DEFAULT_SUMMARIES_DIR
    if not target_dir.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for path in target_dir.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue

    return removed
