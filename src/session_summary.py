"""
Session summary module — "Where was I?" resumption cards.

Extracts structured summaries from Claude Code session transcripts using
LLM-powered extraction (with heuristic fallback). Summaries are stored as
JSON and rendered as prose resumption cards at session start.

Architecture:
- Structured JSON at ~/.claude/session-summaries/{session_id}.json
- Eleven fields: session_id, summary, topic, decisions, open_questions,
  open_threads, files_touched, frustration_level, depends_on, generated_at, generator
- Written at session end by the consolidation hook
- Read at session start by session-context.py
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StructuredSessionSummary:
    """Rich session summary with LLM-extracted fields.

    11 fields total:
    - session_id: Unique session identifier
    - summary: 2-3 sentence overview of what was done
    - topic: Main topic/project being worked on
    - decisions: List of decisions made during session
    - open_questions: Unresolved questions
    - open_threads: In-progress work not yet completed
    - files_touched: Key files that were modified
    - frustration_level: "low" | "medium" | "high" | "unknown"
    - depends_on: List of related session IDs (linked sessions)
    - generated_at: ISO 8601 timestamp
    - generator: "llm" | "heuristic" (tracks what produced this summary)
    """
    session_id: str
    summary: str
    topic: str
    decisions: list[str]
    open_questions: list[str]
    open_threads: list[str]
    files_touched: list[str]
    frustration_level: str
    depends_on: list[str]
    generated_at: str
    generator: str

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)


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


def detect_frustration_level(session_id: str) -> str:
    """Detect frustration level for a session.

    Placeholder for integration with frustration_detector.py.
    Returns "unknown" until integrated.

    Args:
        session_id: Session identifier

    Returns:
        "low" | "medium" | "high" | "unknown"
    """
    # TODO: Integrate with src/wild/frustration_detector.py
    # For now, return unknown
    return "unknown"


# ---------------------------------------------------------------------------
# LLM-powered summary generation
# ---------------------------------------------------------------------------

def generate_llm_summary(
    session_transcript: str,
    session_id: str | None = None,
) -> StructuredSessionSummary:
    """Generate a rich summary using LLM extraction with heuristic fallback.

    Calls ask_claude() to extract structured information from the transcript.
    Falls back to heuristic extraction if LLM fails or times out.

    Quality gate for heuristic: Rejects summaries <50 chars or all questions.

    Args:
        session_transcript: JSONL string of the session transcript.
        session_id: Optional session identifier. Generated if None.

    Returns:
        StructuredSessionSummary with all 11 fields populated.
    """
    from memory_system.llm_extractor import ask_claude

    if session_id is None:
        session_id = uuid.uuid4().hex[:16]

    # Truncate huge transcripts (same as heuristic path)
    if len(session_transcript) > MAX_TRANSCRIPT_BYTES:
        session_transcript = session_transcript[-MAX_TRANSCRIPT_BYTES:]
        first_newline = session_transcript.find("\n")
        if first_newline != -1:
            session_transcript = session_transcript[first_newline + 1:]

    messages = _parse_transcript(session_transcript)

    # Try LLM extraction first
    llm_result = _try_llm_extraction(messages, session_id)
    if llm_result is not None:
        return llm_result

    # Fall back to heuristic extraction
    return _heuristic_summary(messages, session_id)


def _try_llm_extraction(
    messages: list[dict],
    session_id: str,
) -> Optional[StructuredSessionSummary]:
    """Attempt LLM extraction. Returns None on failure.

    Args:
        messages: Parsed transcript messages
        session_id: Session identifier

    Returns:
        StructuredSessionSummary or None if LLM fails
    """
    from memory_system.llm_extractor import ask_claude

    # Build prompt for LLM
    # Take last 20 messages for context (same as heuristic)
    recent = messages[-20:] if len(messages) > 20 else messages
    conversation_text = "\n\n".join([
        f"{m['role'].upper()}: {m['text']}"
        for m in recent
    ])

    prompt = f"""Analyze this Claude Code session conversation and extract a structured summary.

CONVERSATION:
{conversation_text}

Extract the following fields:

1. **summary**: 2-3 sentence overview of what was accomplished
2. **topic**: Main topic/project (e.g., "memory-system-v1", "client-website")
3. **decisions**: List of decisions made (as array of strings)
4. **open_questions**: Unresolved questions (as array of strings)
5. **open_threads**: In-progress work not yet completed (as array of strings)
6. **files_touched**: Key files mentioned/modified (as array of strings)

Return ONLY a JSON object with these exact keys:
{{"summary": "...", "topic": "...", "decisions": [...], "open_questions": [...], "open_threads": [...], "files_touched": [...]}}"""

    # Call LLM with timeout
    response = ask_claude(prompt, timeout=30, max_retries=2)

    if not response or not response.strip():
        return None

    # Parse JSON response
    try:
        data = json.loads(response.strip())
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code fence
        if "```json" in response:
            try:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_text = response[json_start:json_end].strip()
                data = json.loads(json_text)
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None

    # Build StructuredSessionSummary from LLM response
    return StructuredSessionSummary(
        session_id=session_id,
        summary=data.get("summary", ""),
        topic=data.get("topic", ""),
        decisions=data.get("decisions", []),
        open_questions=data.get("open_questions", []),
        open_threads=data.get("open_threads", []),
        files_touched=data.get("files_touched", []),
        frustration_level=detect_frustration_level(session_id),
        depends_on=[],  # TODO: Extract linked sessions from transcript
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator="llm"
    )


def _heuristic_summary(
    messages: list[dict],
    session_id: str,
) -> StructuredSessionSummary:
    """Generate summary using heuristic extraction.

    Uses existing heuristic functions to extract summary, questions, files.
    Applies quality gate: rejects if summary is <50 chars or all questions.

    Args:
        messages: Parsed transcript messages
        session_id: Session identifier

    Returns:
        StructuredSessionSummary with heuristic-extracted content
    """
    summary_text = _extract_summary_text(messages)
    open_questions = _extract_open_questions(messages)
    files_touched = _extract_files_touched(messages)

    # Quality gate: check if summary is too short or all questions
    passes_quality_gate = True
    if len(summary_text) < 50:
        passes_quality_gate = False
    if summary_text and all(c in "?.!" for c in summary_text if not c.isspace()):
        passes_quality_gate = False

    # If quality gate fails, use a default summary
    if not passes_quality_gate:
        summary_text = "Session summary unavailable (transcript too short or incomplete)"

    return StructuredSessionSummary(
        session_id=session_id,
        summary=summary_text,
        topic="",  # Heuristic can't reliably extract topic
        decisions=[],  # Heuristic can't extract decisions
        open_questions=open_questions,
        open_threads=[],  # Heuristic can't distinguish threads from questions
        files_touched=files_touched,
        frustration_level=detect_frustration_level(session_id),
        depends_on=[],
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator="heuristic"
    )


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
    Includes "Watch out for" section with relevant corrections from memory.

    Args:
        summary: The summary dict (supports both old and new formats).

    Returns:
        Formatted string.
    """
    from memory_system.memory_injector import search_memories

    session_id = summary.get("session_id", "unknown")
    generated_at = summary.get("generated_at", "unknown")
    summary_text = summary.get("summary", "No summary available.")
    open_questions = summary.get("open_questions", [])
    files_touched = summary.get("files_touched", [])
    topic = summary.get("topic", "")

    # Truncate session_id for display
    sid_display = session_id[:12] if len(session_id) > 12 else session_id

    lines = [
        "# Project state",
        f"**Last session:** {generated_at} `{sid_display}`",
        f"**What was done:** {summary_text or 'No summary available.'}",
    ]

    # Search for relevant corrections to surface
    corrections = []
    if topic:
        # Search using topic as query
        try:
            results = search_memories(
                query=topic,
                top_k=3,
                min_score=0.5,
                min_normalized=0.2,
            )
            # Filter to only corrections
            corrections = [
                r for r in results
                if r.get("context_type") == "correction"
            ][:3]  # Max 3
        except Exception:
            # Silently fail if search fails (hook context, don't crash)
            pass

    # Add "Watch out for" section if we have corrections
    if corrections:
        lines.append("")
        lines.append("## Watch out for")
        for i, corr in enumerate(corrections, 1):
            content = corr.get("content", "")
            # Strip "Correction: " prefix if present
            if content.lower().startswith("correction: "):
                content = content[len("correction: "):]
            lines.append(f"- {content}")
        lines.append("")

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
