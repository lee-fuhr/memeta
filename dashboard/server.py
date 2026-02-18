"""
Total Recall Dashboard Server

Serves the dashboard UI and provides JSON API endpoints backed by:
  - Memory .md files at ~/.local/share/memory/{project}/memories/
  - session-history.db
  - intelligence.db (when populated)

Usage:
    python3 dashboard/server.py
    python3 dashboard/server.py --port 7860 --project LFI

Then open: http://localhost:7860
"""

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Try to import Flask; suggest install if missing
try:
    from flask import Flask, jsonify, send_from_directory, request
except ImportError:
    print("Flask not found. Install with: pip install flask", file=sys.stderr)
    sys.exit(1)

# SmartAlerts for notification center
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.automation.alerts import SmartAlerts
    _alerts_available = True
except ImportError:
    _alerts_available = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_BASE = Path.home() / ".local/share/memory"
DEFAULT_PROJECT = "LFI"
DEFAULT_PORT = 7860
DASHBOARD_DIR = Path(__file__).parent


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Total Recall dashboard server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--project", default=DEFAULT_PROJECT)
    p.add_argument("--memory-base", default=str(DEFAULT_MEMORY_BASE))
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Memory file parsing
# ---------------------------------------------------------------------------

def _parse_yaml_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter bounded by --- delimiters from a .md file."""
    lines = text.splitlines()
    meta = {}
    body_start = 0

    # Detect --- bounded frontmatter
    if lines and lines[0].strip() == "---":
        fm_end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
        if fm_end is not None:
            fm_lines = lines[1:fm_end]
            body_start = fm_end + 1
        else:
            fm_lines = []
            body_start = 1
    else:
        # Fallback: plain key:value until empty line
        fm_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                body_start = i + 1
                break
            fm_lines.append(stripped)
            body_start = i + 1

    for line in fm_lines:
        stripped = line.strip()
        if not stripped or not ":" in stripped:
            continue
        key, _, val = stripped.partition(":")
        val = val.strip()
        # Strip surrounding quotes
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        # Try to parse JSON arrays/numbers
        try:
            parsed = json.loads(val)
            meta[key.strip()] = parsed
        except (json.JSONDecodeError, ValueError):
            # Try single-quoted arrays (common in YAML: ['tag1', 'tag2'])
            if val.startswith("[") and val.endswith("]"):
                try:
                    parsed = json.loads(val.replace("'", '"'))
                    meta[key.strip()] = parsed
                    continue
                except (json.JSONDecodeError, ValueError):
                    pass
            if val.lower() == "null":
                meta[key.strip()] = None
            elif val.lower() == "true":
                meta[key.strip()] = True
            elif val.lower() == "false":
                meta[key.strip()] = False
            elif val == "":
                meta[key.strip()] = None
            else:
                meta[key.strip()] = val

    body = "\n".join(lines[body_start:]).strip()
    return meta, body


def load_memories(memory_dir: Path) -> list[dict]:
    """Load all .md memory files from a directory into dicts."""
    memories = []
    if not memory_dir.exists():
        return memories

    for path in memory_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            meta, body = _parse_yaml_frontmatter(text)
            meta["_body"] = body
            meta["_filename"] = path.name
            # Drop heavy fields not needed for dashboard
            meta.pop("embedding", None)
            meta.pop("trigger_phrases", None)
            meta.pop("question_types", None)
            # Normalise numeric fields
            for field in ("importance_weight", "confidence_score"):
                v = meta.get(field)
                if v is not None:
                    try:
                        meta[field] = float(v)
                    except (TypeError, ValueError):
                        meta[field] = 0.5
            # Normalise timestamps (ms epoch → datetime str)
            for ts_field in ("created", "updated"):
                v = meta.get(ts_field)
                if v:
                    try:
                        ts = int(v)
                        if ts > 1e12:  # milliseconds
                            ts = ts // 1000
                        meta[f"{ts_field}_dt"] = datetime.fromtimestamp(
                            ts, tz=timezone.utc
                        ).isoformat()
                    except (TypeError, ValueError):
                        meta[f"{ts_field}_dt"] = None
            memories.append(meta)
        except Exception:
            pass

    return memories


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

def load_sessions(db_path: Path, limit: int = 500) -> list[dict]:
    """Load recent sessions from session-history.db."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, timestamp, name, message_count, tool_call_count,
                      memories_extracted
               FROM session_history
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            ts = r["timestamp"]
            dt = None
            if ts:
                try:
                    dt = datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc).isoformat()
                except (TypeError, ValueError):
                    try:
                        ts_str = str(ts).replace("Z", "+00:00")
                        dt = datetime.fromisoformat(ts_str).isoformat()
                    except (ValueError, AttributeError):
                        dt = None
            result.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "datetime": dt,
                "name": r["name"],
                "message_count": r["message_count"] or 0,
                "tool_call_count": r["tool_call_count"] or 0,
                "memories_extracted": r["memories_extracted"] or 0,
            })
        return result
    except Exception as e:
        return []


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def compute_stats(memories: list[dict], sessions: list[dict]) -> dict:
    """Compute summary statistics for the overview cards."""
    total = len(memories)

    # Importance distribution
    importance_values = [
        m.get("importance_weight", 0.5)
        for m in memories
        if m.get("importance_weight") is not None
    ]
    avg_importance = (
        round(sum(importance_values) / len(importance_values), 3)
        if importance_values
        else 0.0
    )

    # Quality tiers (A/B/C/D)
    def _grade(w: float) -> str:
        if w >= 0.8:
            return "A"
        if w >= 0.6:
            return "B"
        if w >= 0.4:
            return "C"
        return "D"

    grade_counts = Counter(_grade(w) for w in importance_values)

    # Tag frequency
    tag_freq: Counter = Counter()
    for m in memories:
        tags = m.get("semantic_tags") or []
        if isinstance(tags, list):
            tag_freq.update(tags)
        elif isinstance(tags, str):
            # Sometimes stored as comma-separated
            tag_freq.update(t.strip() for t in tags.split(",") if t.strip())

    # Knowledge domains
    domain_freq = Counter(
        m.get("knowledge_domain") or "unknown" for m in memories
    )

    # Context types
    context_freq = Counter(
        m.get("context_type") or "unknown" for m in memories
    )

    # Action required
    action_count = sum(
        1 for m in memories if m.get("action_required") is True
    )

    # Problem-solution pairs
    ps_count = sum(
        1 for m in memories if m.get("problem_solution_pair") is True
    )

    # Sessions stats
    total_sessions = len(sessions)
    total_messages = sum(s.get("message_count", 0) for s in sessions)
    total_memories_from_sessions = sum(
        s.get("memories_extracted", 0) for s in sessions
    )

    # Session activity by day (last 90 days)
    day_counts: Counter = Counter()
    for s in sessions:
        dt_str = s.get("datetime")
        if dt_str:
            try:
                day = dt_str[:10]  # YYYY-MM-DD
                day_counts[day] += 1
            except Exception:
                pass

    return {
        "memories": {
            "total": total,
            "avg_importance": avg_importance,
            "grades": dict(grade_counts),
            "action_required": action_count,
            "problem_solution_pairs": ps_count,
        },
        "tags": dict(tag_freq.most_common(40)),
        "domains": dict(domain_freq.most_common(20)),
        "context_types": dict(context_freq.most_common(10)),
        "sessions": {
            "total": total_sessions,
            "total_messages": total_messages,
            "memories_extracted": total_memories_from_sessions,
            "activity_by_day": dict(day_counts.most_common(90)),
        },
    }


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="")

# State (populated on first request or at startup)
_cache: dict = {}

# Notification system (lazy-init)
_smart_alerts: Optional['SmartAlerts'] = None


def _extract_snippet(body: str, query: str, window: int = 120) -> str:
    """Return a ~window-char excerpt of body centred on the first query match.

    Returns an empty string if the query doesn't appear in body (callers
    should fall back to the normal preview in that case).
    """
    lower_body = body.lower()
    lower_q = query.lower()
    idx = lower_body.find(lower_q)
    if idx == -1:
        return ""
    start = max(0, idx - window // 2)
    end = min(len(body), idx + len(query) + window // 2)
    snippet = body[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    return snippet


def _match_reasons(m: dict, q: str) -> list[str]:
    """Return a list of human-readable reasons why memory *m* matched query *q*."""
    reasons = []
    lower_q = q.lower()
    if lower_q in (m.get("_body") or "").lower():
        reasons.append("body")
    tag_str = json.dumps(m.get("semantic_tags") or []).lower()
    if lower_q in tag_str:
        matched_tags = [t for t in (m.get("semantic_tags") or []) if lower_q in t.lower()]
        if matched_tags:
            reasons.append(f"tag: {matched_tags[0]}")
        else:
            reasons.append("tag")
    if lower_q in (m.get("knowledge_domain") or "").lower():
        reasons.append(f"domain: {m.get('knowledge_domain')}")
    return reasons


def _get_alerts() -> Optional['SmartAlerts']:
    """Lazy-init SmartAlerts pointing at intelligence.db."""
    global _smart_alerts
    if _smart_alerts is None and _alerts_available:
        db_path = Path(__file__).parent.parent / "intelligence.db"
        _smart_alerts = SmartAlerts(db_path=db_path)
    return _smart_alerts


def _ensure_data(project: str, memory_base: Path):
    """Load data if not yet cached (or project changed)."""
    cache_key = f"{project}:{memory_base}"
    if _cache.get("_key") == cache_key:
        return
    memory_dir = memory_base / project / "memories"
    session_db = memory_base / project / "session-history.db"
    memories = load_memories(memory_dir)
    sessions = load_sessions(session_db)
    stats = compute_stats(memories, sessions)
    _cache.update({
        "_key": cache_key,
        "project": project,
        "memories": memories,
        "sessions": sessions,
        "stats": stats,
    })


@app.route("/")
def index():
    return send_from_directory(str(DASHBOARD_DIR), "index.html")


@app.route("/api/refresh", methods=["POST"])
def refresh():
    _cache.clear()
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    data = dict(_cache["stats"])
    data["_project"] = _cache.get("project", "")
    return jsonify(data)


@app.route("/api/memories")
def api_memories():
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    memories = _cache["memories"]

    # Filters
    q = request.args.get("q", "").lower()
    domain = request.args.get("domain", "")
    tag = request.args.get("tag", "")
    session_id = request.args.get("session_id", "")
    action_required = request.args.get("action_required", "")
    min_importance = request.args.get("min_importance", "")
    stale_days = request.args.get("stale_days", "")  # memories older than N days
    sort = request.args.get("sort", "importance")  # importance | recency
    limit = min(int(request.args.get("limit", 50)), 200)

    filtered = memories

    if q:
        filtered = [
            m for m in filtered
            if q in (m.get("_body") or "").lower()
            or q in json.dumps(m.get("semantic_tags") or []).lower()
            or q in (m.get("knowledge_domain") or "").lower()
        ]

    if domain:
        filtered = [
            m for m in filtered
            if (m.get("knowledge_domain") or "").lower() == domain.lower()
        ]

    if tag:
        filtered = [
            m for m in filtered
            if tag in (m.get("semantic_tags") or [])
        ]

    if session_id:
        filtered = [
            m for m in filtered
            if (m.get("session_id") or "").startswith(session_id)
        ]

    if action_required == "true":
        filtered = [
            m for m in filtered
            if m.get("action_required")
        ]

    if min_importance:
        try:
            threshold = float(min_importance)
            filtered = [
                m for m in filtered
                if (m.get("importance_weight") or 0) >= threshold
            ]
        except ValueError:
            pass

    if stale_days:
        try:
            stale_threshold = int(stale_days)
            now_epoch = datetime.now(tz=timezone.utc).timestamp()
            def _is_stale(m):
                for f in ("updated", "created"):
                    v = m.get(f)
                    if v:
                        try:
                            ts = int(v)
                            if ts > 1e12:
                                ts = ts / 1000
                            return (now_epoch - ts) / 86400 >= stale_threshold
                        except (TypeError, ValueError):
                            pass
                return False
            filtered = [m for m in filtered if _is_stale(m)]
        except ValueError:
            pass

    # Sort
    if sort == "importance":
        filtered.sort(key=lambda m: m.get("importance_weight") or 0, reverse=True)
    elif sort == "recency":
        def _recency_key(m):
            v = m.get("created") or 0
            if hasattr(v, "timestamp"):   # datetime.datetime object
                return v.timestamp()
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0
        filtered.sort(key=_recency_key, reverse=True)

    # Return slim projection
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    result = []
    for m in filtered[:limit]:
        body = m.get("_body") or ""
        # Compute days since last update
        days_stale = None
        for ts_field in ("updated", "created"):
            v = m.get(ts_field)
            if v:
                try:
                    ts = int(v)
                    if ts > 1e12:
                        ts = ts / 1000
                    days_stale = max(0, int((now_ts - ts) / 86400))
                    break
                except (TypeError, ValueError):
                    pass

        entry = {
            "id": m.get("id") or m.get("_filename"),
            "importance": m.get("importance_weight", 0.5),
            "confidence": m.get("confidence_score", 0.5),
            "context_type": m.get("context_type") or "unknown",
            "knowledge_domain": m.get("knowledge_domain") or "unknown",
            "tags": m.get("semantic_tags") or [],
            "created": m.get("created_dt"),
            "updated": m.get("updated_dt"),
            "action_required": m.get("action_required") or False,
            "problem_solution": m.get("problem_solution_pair") or False,
            "session_id": m.get("session_id") or "",
            "preview": body[:240].replace("\n", " "),
            "days_stale": days_stale,
        }
        if q:
            entry["match_snippet"] = _extract_snippet(body, q)
            entry["match_reasons"] = _match_reasons(m, q)
        result.append(entry)

    return jsonify({"total": len(filtered), "memories": result})


@app.route("/api/memory/<memory_id>")
def api_memory_detail(memory_id):
    """Return full content for a single memory."""
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    for m in _cache["memories"]:
        mid = m.get("id") or m.get("_filename")
        if mid == memory_id:
            return jsonify({
                "id": mid,
                "importance": m.get("importance_weight", 0.5),
                "confidence": m.get("confidence_score", 0.5),
                "context_type": m.get("context_type") or "unknown",
                "knowledge_domain": m.get("knowledge_domain") or "unknown",
                "tags": m.get("semantic_tags") or [],
                "created": m.get("created_dt"),
                "updated": m.get("updated_dt"),
                "action_required": m.get("action_required") or False,
                "problem_solution": m.get("problem_solution_pair") or False,
                "body": m.get("_body") or "",
                "filename": m.get("_filename") or "",
                "source_session": m.get("session_id") or "",
                "related_memories": m.get("related_memories") or [],
            })
    return jsonify({"error": "Not found"}), 404


@app.route("/api/export")
def api_export():
    """Export memories as JSON or CSV."""
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    fmt = request.args.get("format", "json")
    memories = _cache["memories"]

    rows = []
    for m in memories:
        raw_tags = m.get("semantic_tags") or []
        if isinstance(raw_tags, list):
            tags_str = ", ".join(str(t) for t in raw_tags)
        else:
            tags_str = str(raw_tags)
        rows.append({
            "id": m.get("id") or m.get("_filename"),
            "importance": m.get("importance_weight", 0.5),
            "confidence": m.get("confidence_score", 0.5),
            "context_type": m.get("context_type") or "unknown",
            "knowledge_domain": m.get("knowledge_domain") or "unknown",
            "tags": tags_str,
            "created": m.get("created_dt") or "",
            "updated": m.get("updated_dt") or "",
            "action_required": m.get("action_required") or False,
            "problem_solution": m.get("problem_solution_pair") or False,
            "body": m.get("_body") or "",
        })

    if fmt == "csv":
        import csv
        import io
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=total-recall-memories.csv"},
        )

    return jsonify({"total": len(rows), "memories": rows})


@app.route("/api/sessions")
def api_sessions():
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    limit = min(int(request.args.get("limit", 50)), 200)
    date_filter = request.args.get("date", "")  # YYYY-MM-DD
    sessions = _cache["sessions"]
    if date_filter:
        sessions = [
            s for s in sessions
            if (s.get("date") or "").startswith(date_filter)
        ]
    return jsonify({"total": len(sessions), "sessions": sessions[:limit]})


@app.route("/api/session/<session_id>")
def api_session_detail(session_id):
    """Return session metadata + summarised transcript turns."""
    _ensure_data(app.config["PROJECT"], app.config["MEMORY_BASE"])
    memory_base = Path(app.config["MEMORY_BASE"])
    project = app.config["PROJECT"]
    db_path = memory_base / project / "session-history.db"

    if not db_path.exists():
        return jsonify({"error": "session DB not found"}), 404

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM session_history WHERE id = ?", (session_id,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "session not found"}), 404

    # Build metadata
    ts = row["timestamp"]
    dt = None
    if ts:
        try:
            dt = datetime.fromtimestamp(
                float(ts) / 1000, tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError):
            pass

    meta = {
        "id": row["id"],
        "name": row["name"],
        "datetime": dt,
        "message_count": row["message_count"] or 0,
        "tool_call_count": row["tool_call_count"] or 0,
        "memories_extracted": row["memories_extracted"] or 0,
    }

    # Summarise transcript turns (don't send full multi-MB blob)
    turns = _summarise_transcript(row["full_transcript_json"])

    # Find memories from this session
    memories = [
        {
            "id": m.get("id") or m.get("_filename"),
            "importance": m.get("importance_weight", 0.5),
            "knowledge_domain": m.get("knowledge_domain") or "unknown",
            "preview": (m.get("_body") or "")[:120].replace("\n", " "),
        }
        for m in _cache.get("memories", [])
        if (m.get("session_id") or "").startswith(session_id)
    ]

    return jsonify({"session": meta, "turns": turns, "memories": memories})


def _summarise_transcript(transcript_json: str, max_turns: int = 50) -> list[dict]:
    """Extract user/assistant messages from a full transcript JSON.

    Returns a slim list: [{role, preview, tool_calls, timestamp}, ...]
    Caps at max_turns to keep the response reasonable.
    """
    try:
        data = json.loads(transcript_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    turns = []
    for item in data:
        msg_type = item.get("type", "")
        if msg_type not in ("user", "assistant"):
            continue

        msg = item.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", msg_type)
        content = msg.get("content", "")

        # Multi-part content (list of blocks)
        if isinstance(content, list):
            text_parts = []
            tool_count = 0
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "tool_use":
                        tool_count += 1
                elif isinstance(part, str):
                    text_parts.append(part)
            preview = " ".join(text_parts)[:300]
        else:
            preview = str(content)[:300]
            tool_count = 0

        preview = preview.replace("\n", " ").strip()
        if not preview and tool_count == 0:
            continue

        turns.append({
            "role": role,
            "preview": preview,
            "tool_calls": tool_count,
            "timestamp": item.get("timestamp"),
        })

        if len(turns) >= max_turns:
            break

    return turns


# ---------------------------------------------------------------------------
# Briefing API
# ---------------------------------------------------------------------------

@app.route("/api/briefing")
def api_briefing():
    """Get cluster-based morning briefing."""
    try:
        from memory_system.cluster_briefing import generate_briefing, format_briefing_text
        memory_base = Path(app.config["MEMORY_BASE"])
        project = app.config["PROJECT"]
        memory_dir = memory_base / project / "memories"
        intel_db = Path(__file__).parent.parent / "intelligence.db"

        briefing = generate_briefing(
            db_path=intel_db,
            memory_dir=memory_dir,
            max_clusters=int(request.args.get("max_clusters", 10)),
        )
        return jsonify({
            "items": [item.to_dict() for item in briefing.items],
            "divergences": briefing.divergences,
            "generated_at": briefing.generated_at.isoformat(),
            "is_empty": briefing.is_empty,
            "formatted": format_briefing_text(briefing),
        })
    except ImportError:
        return jsonify({"items": [], "divergences": [], "is_empty": True,
                        "error": "cluster_briefing module not available"})
    except Exception as e:
        return jsonify({"items": [], "divergences": [], "is_empty": True,
                        "error": str(e)})


# ---------------------------------------------------------------------------
# Notification API
# ---------------------------------------------------------------------------

@app.route("/api/notifications")
def api_notifications():
    """Get unread notifications for bell badge + dropdown."""
    alerts_sys = _get_alerts()
    if not alerts_sys:
        return jsonify({"unread_count": 0, "notifications": []})

    alert_type = request.args.get("type", None) or None
    limit = min(int(request.args.get("limit", 8)), 50)

    unread = alerts_sys.get_unread_alerts(alert_type=alert_type, limit=limit)
    all_unread = alerts_sys.get_unread_alerts(limit=999)
    return jsonify({
        "unread_count": len(all_unread),
        "notifications": [a.to_dict() for a in unread],
    })


@app.route("/api/notifications/all")
def api_notifications_all():
    """Get all notifications with pagination (for Activity view)."""
    alerts_sys = _get_alerts()
    if not alerts_sys:
        return jsonify({"total": 0, "notifications": []})

    alert_type = request.args.get("type", None) or None
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    alerts, total = alerts_sys.get_all_alerts(
        alert_type=alert_type, limit=limit, offset=offset
    )
    return jsonify({
        "total": total,
        "notifications": [a.to_dict() for a in alerts],
    })


@app.route("/api/notifications/<int:alert_id>/dismiss", methods=["POST"])
def api_dismiss_notification(alert_id):
    """Dismiss a single notification."""
    alerts_sys = _get_alerts()
    if not alerts_sys:
        return jsonify({"error": "Alerts not available"}), 503

    alerts_sys.dismiss_alert(alert_id)
    return jsonify({"ok": True})


@app.route("/api/notifications/dismiss-all", methods=["POST"])
def api_dismiss_all():
    """Dismiss all unread notifications."""
    alerts_sys = _get_alerts()
    if not alerts_sys:
        return jsonify({"error": "Alerts not available"}), 503

    alerts_sys.dismiss_all()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = _parse_args()
    memory_base = Path(args.memory_base)
    app.config["PROJECT"] = args.project
    app.config["MEMORY_BASE"] = memory_base

    print(f"Total Recall dashboard — http://localhost:{args.port}")
    print(f"  Project : {args.project}")
    print(f"  Memory  : {memory_base / args.project / 'memories'}")
    print(f"  Sessions: {memory_base / args.project / 'session-history.db'}")

    # Pre-load data
    _ensure_data(args.project, memory_base)
    stats = _cache.get("stats", {})
    mem_total = stats.get("memories", {}).get("total", 0)
    sess_total = stats.get("sessions", {}).get("total", 0)
    print(f"  Loaded  : {mem_total} memories, {sess_total} sessions")

    app.run(host="0.0.0.0", port=args.port, debug=args.debug)
