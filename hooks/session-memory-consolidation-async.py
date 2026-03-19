#!/usr/bin/env python3
"""
SessionEnd Hook - Async Consolidation (Fast Version)

Replaces blocking consolidation with queue-based async processing.

Performance:
- Before: 60-120s blocking (timeout risk)
- After: <1s (just writes to queue)

The actual consolidation happens in background worker.

Usage:
    Add to ~/.claude/settings.json:
    {
      "hooks": {
        "SessionEnd": {
          "type": "command",
          "command": "python3 /path/to/session-memory-consolidation-async.py",
          "timeout": 10000
        }
      }
    }
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

from memory_system.async_consolidation import ConsolidationQueue

_HOOK_LOG = Path.home() / "CC/Work/LFI/_ Operations/hooks/hook_events.jsonl"


def _log_event(session_id, **kwargs):
    try:
        event = {"timestamp": datetime.now().isoformat(), "event_type": "session_consolidation_async", "session_id": session_id or "unknown", **kwargs}
        with open(_HOOK_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def main():
    """Fast SessionEnd hook - just adds to queue"""

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except Exception as e:
        print(f"❌ Error reading hook input: {e}", file=sys.stderr)
        _log_event(None, status="error", error=f"Failed to read hook input: {e}")
        return 0  # Bible 3.3: SessionEnd hooks must always return 0

    session_id = hook_input.get('sessionId')
    project_path = hook_input.get('projectPath')

    if not session_id or not project_path:
        print("⚠️  Missing sessionId or projectPath", file=sys.stderr)
        _log_event(session_id, status="error", error="Missing sessionId or projectPath")
        return 0  # Bible 3.3: SessionEnd hooks must always return 0

    # Construct session path
    session_dir = Path.home() / ".claude/projects" / os.path.basename(project_path)
    session_path = session_dir / f"{session_id}.jsonl"

    if not session_path.exists():
        print(f"⚠️  Session file not found: {session_path}", file=sys.stderr)
        _log_event(session_id, status="error", error=f"Session file not found: {session_path}")
        return 0  # Bible 3.3: SessionEnd hooks must always return 0

    # Add to queue (FAST - just a DB insert)
    try:
        queue = ConsolidationQueue()
        added = queue.add(session_id, str(session_path))

        if added:
            print(f"✅ Session queued for consolidation: {session_id[:8]}")
            _log_event(session_id, status="queued")
        else:
            print(f"ℹ️  Session already queued: {session_id[:8]}")
            _log_event(session_id, status="already_queued")

        # Generate and save session summary (best-effort)
        try:
            from memory_system.session_summary import generate_summary, save_summary

            transcript = session_path.read_text()
            summary = generate_summary(transcript, session_id)
            save_summary(summary, session_id)
            print(f"✅ Session summary saved: {session_id[:8]}")
            _log_event(session_id, status="summary_saved")
        except Exception as e:
            print(f"⚠️  Summary generation skipped: {e}", file=sys.stderr)
            _log_event(session_id, status="summary_skipped", error=str(e))

        # Resolve skill outcomes (best-effort — must run after summary is saved)
        try:
            from memory_system.skill_outcome_resolver import resolve_session_outcomes

            outcome_result = resolve_session_outcomes(session_id)
            if outcome_result["updated"] > 0:
                print(
                    f"✅ Skill outcomes resolved: {outcome_result['updated']} skill(s)"
                    f" → {outcome_result['outcome']}"
                )
                _log_event(session_id, status="skill_outcomes_resolved", updated=outcome_result["updated"])
        except Exception as e:
            print(f"⚠️  Skill outcome resolution skipped: {e}", file=sys.stderr)
            _log_event(session_id, status="skill_outcomes_skipped", error=str(e))

        # Bible 2.14 (Two-level learning): graduate corrections confirmed 3+ sessions
        try:
            from memory_system.correction_graduator import CorrectionGraduator
            graduator = CorrectionGraduator(
                claude_md_path=Path.home() / "CC/.claude/CLAUDE.md"
            )
            grad_result = graduator.graduate()
            corrections_graduated = grad_result.get("rules_written", 0)
            if corrections_graduated > 0:
                print(f"✅ Corrections graduated: {corrections_graduated}")
                _log_event(session_id, status="corrections_graduated", count=corrections_graduated)
        except Exception as e:
            print(f"⚠️  Correction graduation skipped: {e}", file=sys.stderr)
            _log_event(session_id, status="correction_graduation_skipped", error=str(e))

        # Bible 1.11 (Actionable metrics): track memory surfacing accuracy
        try:
            from memory_system.confidence_calibration import log_calibration_event
            log_calibration_event(
                session_id=session_id,
                memories_surfaced=0,  # Baseline — worker updates after consolidation
                memories_used=0,
            )
            _log_event(session_id, status="calibration_logged")
        except Exception as e:
            print(f"⚠️  Calibration skipped: {e}", file=sys.stderr)
            _log_event(session_id, status="calibration_skipped", error=str(e))

        return 0

    except Exception as e:
        print(f"❌ Error queuing session: {e}", file=sys.stderr)
        _log_event(session_id, status="error", error=f"Queue error: {e}")
        return 0  # Bible 3.3: SessionEnd hooks must always return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"⚠️  Async consolidation failed: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)  # Always exit 0
