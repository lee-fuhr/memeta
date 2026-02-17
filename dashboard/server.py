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

    # Sort
    if sort == "importance":
        filtered.sort(key=lambda m: m.get("importance_weight") or 0, reverse=True)
    elif sort == "recency":
        filtered.sort(
            key=lambda m: m.get("created") or 0,
            reverse=True,
        )

    # Return slim projection
    result = []
    for m in filtered[:limit]:
        body = m.get("_body") or ""
        result.append({
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
            "preview": body[:240].replace("\n", " "),
        })

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
                "source_session": m.get("source_session") or "",
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
    sessions = _cache["sessions"][:limit]
    return jsonify({"total": len(_cache["sessions"]), "sessions": sessions})


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
