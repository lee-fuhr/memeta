#!/usr/bin/env python3
"""Pattern recall hook — UserPromptSubmit.

Detects problems and surfaces past solutions from memory.
Guard chain pattern (Bible 2.5): validate at each layer.

Performance budget: <500ms (BM25 only, no model loading).

DEPLOYMENT:
  "UserPromptSubmit": [{
    "type": "command",
    "command": "~/.local/venvs/memory-system/bin/python3 /path/to/memeta/hooks/pattern-recall.py",
    "timeout": 5000
  }]
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add memory-system src to path so bare and qualified imports both resolve
_ms_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ms_root / "src"))

# Cooldown: minimum exchanges between pattern recall injections
_COOLDOWN_EXCHANGES = 5

# Signal strength threshold — only fire for genuine problems
_SIGNAL_THRESHOLD = 0.3

# Default memory directory (override MEMETA_PROJECT to change project name)
_DEFAULT_MEMORY_DIR = Path.home() / ".local/share/memory" / os.environ.get("MEMETA_PROJECT", "default") / "memories"


_HOOK_LOG = Path(os.environ.get("MEMETA_HOOK_LOG", str(Path.home() / ".local/share/memeta/hook_events.jsonl")))


def _log(msg: str) -> None:
    """Log diagnostic info to stderr (never stdout — that's injection)."""
    print(f"[pattern-recall] {msg}", file=sys.stderr)


def _log_event(session_id: str, **kwargs) -> None:
    """Write structured event to hook_events.jsonl (Bible 1.12)."""
    try:
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "pattern_recall",
            "session_id": session_id or "unknown",
            **kwargs,
        }
        with open(_HOOK_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def main() -> None:
    # ── Layer 1: Parse stdin JSON ─────────────────────────────────────
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError) as exc:
        _log(f"stdin parse failed: {exc}")
        return

    # ── Layer 2: Extract prompt content ───────────────────────────────
    session_id = payload.get("sessionId", "")
    content = payload.get("message", {}).get("content", "").strip()
    if not content:
        _log("empty prompt, skipping")
        return

    # ── Late imports (exit cleanly if memory_system not installed) ────
    try:
        from pattern_recall import (
            calculate_problem_signal_strength,
            extract_problem_query,
            format_pattern_recall,
            search_past_solutions,
        )
        from hook_state import (
            get_session_id,
            get_session_state,
            update_session_state,
        )
    except ImportError as exc:
        _log(f"import failed: {exc}")
        return

    sid = session_id or get_session_id()

    # Exchange count is incremented by memory-injection.py (same event).
    # Pattern-recall reads but does not increment — avoids double-counting.

    # ── Layer 3: Calculate signal strength ────────────────────────────
    signal = calculate_problem_signal_strength(content)
    _log(f"signal_strength={signal:.2f} (threshold={_SIGNAL_THRESHOLD})")

    if signal <= _SIGNAL_THRESHOLD:
        _log("below threshold, skipping")
        return

    # ── Layer 4: Check cooldown ───────────────────────────────────────
    session = get_session_state(session_id=sid)
    exchange_count = session.get("exchange_count", 0)
    last_recall = session.get("last_pattern_recall_exchange", 0)
    gap = exchange_count - last_recall

    _log(f"cooldown check: exchange={exchange_count}, last_recall={last_recall}, gap={gap}")

    if gap < _COOLDOWN_EXCHANGES:
        _log(f"cooldown active ({gap} < {_COOLDOWN_EXCHANGES}), skipping")
        return

    # ── Layer 5: Extract query and search ─────────────────────────────
    query = extract_problem_query(content)
    if not query:
        _log("could not extract query from prompt")
        return

    _log(f"searching memories with query: {query[:80]}...")

    # Resolve memory directory — prefer config if available, fall back to default
    try:
        from config import cfg
        project = os.environ.get("MEMETA_PROJECT", "default")
        memory_dir = cfg.memory_dir / project / "memories"
    except (ImportError, Exception):
        memory_dir = _DEFAULT_MEMORY_DIR

    if not memory_dir.exists():
        _log(f"memory dir not found: {memory_dir}")
        return

    solutions = search_past_solutions(query=query, memory_dir=memory_dir, top_k=3)
    _log(f"found {len(solutions)} solution(s)")

    if not solutions:
        _log("no matching solutions, skipping")
        return

    # ── Output: format and print to stdout for injection ──────────────
    output = format_pattern_recall(solutions)
    if output:
        print(output)
        _log("injected pattern recall block")

        # Log structured event (Bible 1.12)
        _log_event(
            sid,
            status="injected",
            signal_strength=round(signal, 2),
            solutions_found=len(solutions),
            exchange=exchange_count,
        )

        # Record that we fired so cooldown kicks in
        update_session_state(
            {"last_pattern_recall_exchange": exchange_count},
            session_id=sid,
        )
    else:
        _log("format_pattern_recall returned empty string")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Bible 3.3: Never block. Never crash. Exit 0 always.
        # Don't use traceback.format_exc() — could leak sensitive memory content
        _log(f"unhandled exception: {type(e).__name__}: {e}")
    # Always exit 0 — hooks must never block the session
    sys.exit(0)
