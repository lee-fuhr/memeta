"""
Hook shared state module.

Provides read/write access to a single JSON state file that tracks
per-session state for Claude Code hooks. Each session gets its own
key in the state dict, with fields for exchange counting, memory
injection timing, and active skills.

Design decisions:
- Single JSON file at ~/.claude/hook-state.json
- Single-writer-per-event (hooks fire sequentially per event), so
  no file locking is needed
- Session ID keys with probabilistic cleanup (1-in-10 on write,
  removes sessions older than 24 hours)
- Atomic writes (write to .tmp then os.replace) to prevent corruption
"""

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DEFAULT_STATE_FILE: Path = Path.home() / ".claude" / "hook-state.json"
DEFAULT_INJECTION_INTERVAL: int = 10

_DEFAULT_SESSION_SCHEMA: dict = {
    "exchange_count": 0,
    "project": None,
    "last_injection_ts": None,
    "last_injection_exchange": 0,
    "last_injected_ids": [],
    "active_skills": [],
    "injection_interval": DEFAULT_INJECTION_INTERVAL,
    "initialized_at": None,  # set at creation time
}


def get_session_id() -> str:
    """Read the current session ID from the CLAUDE_SESSION_ID env var.

    Returns 'unknown' if the variable is missing or empty.
    """
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    return session_id if session_id else "unknown"


def load_state(state_file: Optional[Path] = None) -> dict:
    """Load the full state dict from disk.

    Returns an empty dict if the file is missing or contains invalid JSON.
    """
    path = state_file or DEFAULT_STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict, state_file: Optional[Path] = None) -> None:
    """Atomically write *state* to disk.

    Writes to a .tmp sibling first, then uses ``os.replace`` to swap it
    into place. Creates parent directories if needed.
    """
    path = state_file or DEFAULT_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, indent=2))
    os.replace(str(tmp_path), str(path))


def get_session_state(
    session_id: Optional[str] = None,
    state_file: Optional[Path] = None,
) -> dict:
    """Return the state dict for a single session.

    If the session doesn't exist yet it is initialised with default
    values and persisted before returning.
    """
    sid = session_id or get_session_id()
    state = load_state(state_file)

    if sid not in state:
        entry = dict(_DEFAULT_SESSION_SCHEMA)
        # Deep-copy mutable defaults
        entry["last_injected_ids"] = list(entry["last_injected_ids"])
        entry["active_skills"] = list(entry["active_skills"])
        entry["initialized_at"] = datetime.now().isoformat()
        state[sid] = entry
        save_state(state, state_file)

    return state[sid]


def update_session_state(
    updates: dict,
    session_id: Optional[str] = None,
    state_file: Optional[Path] = None,
) -> dict:
    """Merge *updates* into the session's state and persist.

    Initialises the session with defaults first if it doesn't exist,
    then applies the updates on top. Returns the updated session dict.
    """
    sid = session_id or get_session_id()
    state = load_state(state_file)

    if sid not in state:
        # Bootstrap with defaults
        entry = dict(_DEFAULT_SESSION_SCHEMA)
        entry["last_injected_ids"] = list(entry["last_injected_ids"])
        entry["active_skills"] = list(entry["active_skills"])
        entry["initialized_at"] = datetime.now().isoformat()
        state[sid] = entry

    state[sid].update(updates)
    save_state(state, state_file)

    # Probabilistic cleanup: 1-in-10 chance on every write
    if random.random() < 0.1:
        cleanup_stale_sessions(state_file=state_file)

    return state[sid]


def increment_exchange(
    session_id: Optional[str] = None,
    state_file: Optional[Path] = None,
) -> int:
    """Increment the exchange counter for a session.

    Returns the *new* count.
    """
    sid = session_id or get_session_id()
    # Ensure session exists
    get_session_state(sid, state_file)

    state = load_state(state_file)
    state[sid]["exchange_count"] += 1
    new_count = state[sid]["exchange_count"]
    save_state(state, state_file)
    return new_count


def should_inject(
    session_id: Optional[str] = None,
    state_file: Optional[Path] = None,
) -> bool:
    """Determine whether it's time to inject memories.

    Returns True when:
    1. ``exchange_count`` is a multiple of ``injection_interval``, AND
    2. At least ``injection_interval`` exchanges have passed since
       ``last_injection_exchange``.
    """
    sid = session_id or get_session_id()
    session = get_session_state(sid, state_file)

    count = session["exchange_count"]
    interval = session["injection_interval"]
    last_inj = session["last_injection_exchange"]

    if count == 0:
        return False
    if count % interval != 0:
        return False
    if (count - last_inj) < interval:
        return False
    return True


def record_injection(
    memory_ids: list,
    session_id: Optional[str] = None,
    state_file: Optional[Path] = None,
) -> None:
    """Record that a memory injection just happened.

    Updates ``last_injection_ts``, ``last_injection_exchange``, and
    ``last_injected_ids`` in the session state.
    """
    sid = session_id or get_session_id()
    session = get_session_state(sid, state_file)
    update_session_state(
        {
            "last_injection_ts": datetime.now().isoformat(),
            "last_injection_exchange": session["exchange_count"],
            "last_injected_ids": list(memory_ids),
        },
        session_id=sid,
        state_file=state_file,
    )


def cleanup_stale_sessions(
    state_file: Optional[Path] = None,
    max_age_hours: int = 24,
) -> int:
    """Remove sessions older than *max_age_hours*.

    Returns the number of sessions removed. Safe to call when the
    state file is missing or empty.
    """
    state = load_state(state_file)
    if not state:
        return 0

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    to_remove: list[str] = []

    for sid, session in state.items():
        init_ts = session.get("initialized_at")
        if init_ts is None:
            # No timestamp — treat as stale
            to_remove.append(sid)
            continue
        try:
            init_dt = datetime.fromisoformat(init_ts)
            if init_dt < cutoff:
                to_remove.append(sid)
        except (ValueError, TypeError):
            # Unparseable timestamp — leave it alone
            pass

    for sid in to_remove:
        del state[sid]

    if to_remove:
        save_state(state, state_file)

    return len(to_remove)
