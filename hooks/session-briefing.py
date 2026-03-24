#!/usr/bin/env python3
"""Session briefing hook — SessionStart.

Injects unified context card: top memories, corrections, commitments,
skill recommendations, anti-pattern alerts. Enrichment-only (Bible 3.3).

Graceful degradation (Bible 2.10): missing index → empty string,
missing DB → empty string. Import failures → silent exit.

Observability (Bible 1.12): logs generated sections to stderr.

DEPLOYMENT:
  "SessionStart": [{
    "type": "command",
    "command": "~/.local/venvs/memory-system/bin/python3 /path/to/memeta/hooks/session-briefing.py",
    "timeout": 10000
  }]
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add memory-system src to path so memory_system imports resolve
_ms_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ms_root / "src"))


_HOOK_LOG = Path(os.environ.get("MEMETA_HOOK_LOG", str(Path.home() / ".local/share/memeta/hook_events.jsonl")))


def _log(msg: str) -> None:
    """Write diagnostic line to stderr (never stdout — that's for context)."""
    print(f"[session-briefing] {msg}", file=sys.stderr)


def _log_event(session_id: str, **kwargs) -> None:
    """Write structured event to hook_events.jsonl (Bible 1.12)."""
    try:
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "session_briefing",
            "session_id": session_id or "unknown",
            **kwargs,
        }
        with open(_HOOK_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # Non-critical — don't fail the hook


def _read_stdin() -> dict:
    """Parse stdin JSON payload. Returns empty dict on any error."""
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError, ValueError):
        _log("stdin parse failed — proceeding with empty context")
        return {}


def _extract_topic(payload: dict) -> str:
    """Best-effort topic extraction from session context.

    For resume events, the payload may contain session state with a topic.
    For fresh starts, returns empty string (briefing still works without it).
    """
    # Direct topic field (if hook infrastructure provides it)
    topic = payload.get("topic", "")
    if topic:
        return topic

    # Try session metadata for resume events
    session = payload.get("session", {})
    if isinstance(session, dict):
        topic = session.get("topic", "") or session.get("name", "")
        if topic:
            return topic

    return ""


def _count_sections(output: str) -> list[str]:
    """Identify which briefing sections were generated from the output."""
    section_markers = {
        "corrections": "## Active corrections",
        "commitments": "## Open commitments",
        "antipatterns": "## Skill risk alerts",
        "memories": "## Relevant memories",
        "skills": "## Recommended skills",
    }
    found = []
    for name, marker in section_markers.items():
        if marker in output:
            found.append(name)
    return found


def main() -> None:
    t0 = time.monotonic()

    payload = _read_stdin()
    session_id = payload.get("session_id", "") or payload.get("sessionId", "")
    event = payload.get("event", "startup")
    topic = _extract_topic(payload)

    _log(f"event={event} session={str(session_id)[:12] or '(none)'} topic={topic or '(none)'}")

    # Late import — exit silently if memory_system isn't available (Bible 2.10)
    try:
        from memory_system.session_briefing import SessionBriefing
    except ImportError as e:
        _log(f"import failed: {e} — exiting cleanly")
        return

    # Generate the briefing
    try:
        briefing = SessionBriefing()
        output = briefing.generate(
            topic=topic,
            session_id=session_id or None,
        )
    except Exception as e:
        _log(f"generate() failed: {e} — exiting cleanly")
        return

    # Observability: log what was produced
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if not output or not output.strip():
        _log(f"No briefing content for this session ({elapsed_ms}ms)")
        _log_event(session_id, status="empty", elapsed_ms=elapsed_ms)
        return

    sections = _count_sections(output)
    _log(f"sections=[{', '.join(sections)}] ({elapsed_ms}ms)")

    # Log structured event (Bible 1.12)
    _log_event(
        session_id,
        status="success",
        sections=sections,
        section_count=len(sections),
        elapsed_ms=elapsed_ms,
    )

    # Inject into context via stdout
    print(output)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Hook must NEVER crash Claude Code (Bible 3.3)
        # Don't use traceback.format_exc() — could leak sensitive memory content
        _log(f"unexpected error: {type(e).__name__}: {e}")
    # Exit 0 always — enrichment-only, never block
    sys.exit(0)
