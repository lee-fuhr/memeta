#!/usr/bin/env python3
"""
Memory injection hook — UserPromptSubmit.

Every N exchanges, searches Memeta for memories relevant to the user's
current prompt and injects them into context.

Performance budget: <500ms (no model loading, BM25 only).

DEPLOYMENT NOTE: Register with the memory-system venv Python, e.g.:
  ~/.local/venvs/memory-system/bin/python3 /path/to/memory-injection.py
The bare `from hook_state` / `from memory_injector` imports resolve via
sys.path, but memory_injector internally uses `from memory_system.hybrid_search`
which requires the package to be installed.
"""

import json
import sys
from pathlib import Path

# Add memory-system src to path
_ms_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ms_root / "src"))


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return

    session_id = payload.get("sessionId", "")
    content = payload.get("message", {}).get("content", "").strip()
    if not content:
        return

    # Late import — exit silently if memory_system isn't installed
    try:
        from hook_state import (get_session_id, get_session_state,
                                increment_exchange, record_injection, should_inject,
                                should_inject_immediately, reduce_injection_interval)
        from memory_injector import format_injection, load_search_index, search_memories
        from memory_system.confirmation_tracker import (
            check_confirmation, record_confirmation, record_surfacing,
        )
        _has_confirmation = True
    except ImportError:
        try:
            from hook_state import (get_session_id, get_session_state,
                                    increment_exchange, record_injection, should_inject,
                                    should_inject_immediately, reduce_injection_interval)
            from memory_injector import format_injection, load_search_index, search_memories
            _has_confirmation = False
        except ImportError:
            return

    sid = session_id or get_session_id()

    # --- Confirmation check: was the PREVIOUS surfacing helpful? ---
    if _has_confirmation:
        try:
            session_state = get_session_state(session_id=sid)
            pending = session_state.get("pending_confirmations", [])
            if pending:
                # Build content map from pending memory IDs
                all_memories = load_search_index()
                memory_contents = {
                    m.get("id"): m.get("content", "")
                    for m in all_memories
                    if m.get("id") in {p["memory_id"] for p in pending}
                }
                # Check if user's current prompt references any pending memories
                confirmed_ids = check_confirmation(
                    user_response=content,
                    memory_contents=memory_contents,
                    session_id=sid,
                )
                # Record results to memory files
                pending_ids = {p["memory_id"] for p in pending}
                for mid in pending_ids:
                    record_confirmation(
                        mid,
                        was_confirmed=(mid in confirmed_ids),
                    )
        except Exception:
            pass  # Confirmation tracking must never block injection

    # Always increment; check for frustration signal to bypass gate
    increment_exchange(session_id=sid)
    immediate = should_inject_immediately(content)
    if not immediate and not should_inject(session_id=sid):
        return

    # When frustration detected, reduce interval for rest of session
    if immediate:
        reduce_injection_interval(session_id=sid)

    # Load index — skip silently if not built yet
    memories = load_search_index()
    if not memories:
        return

    # Exclude previously injected memories
    session = get_session_state(session_id=sid)
    exclude_ids = set(session.get("last_injected_ids", []))
    if exclude_ids:
        memories = [m for m in memories if m.get("id") not in exclude_ids]
    if not memories:
        return

    # Search with higher top_k if frustration detected (broader coverage)
    top_k = 5 if immediate else 3
    results = search_memories(query=content, memories=memories, top_k=top_k)
    if not results:
        return

    output = format_injection(results, context="prompt")
    if output:
        print(output)

    # Record injected IDs so they're excluded next time
    injected_ids = [r.get("id") for r in results if r.get("id")]
    if injected_ids:
        record_injection(injected_ids, session_id=sid)

        # Record surfacing for confirmation tracking on next exchange
        if _has_confirmation:
            try:
                record_surfacing(
                    memory_ids=injected_ids,
                    user_prompt=content,
                    session_id=sid,
                )
            except Exception:
                pass  # Never block on confirmation tracking


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Hooks must never crash — fail silently, log to stderr
        import traceback
        print(traceback.format_exc(), file=sys.stderr)
