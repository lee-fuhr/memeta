"""
FSRS dashboard data exporter

Reads fsrs.db + hook_events.jsonl, writes fsrs-status.json
for the static memory dashboard to fetch.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from memory_system.db_pool import get_connection


def export_dashboard_data(
    fsrs_db: Path,
    hook_log: Path,
    output: Path,
) -> dict:
    """Export FSRS state to JSON for the dashboard.

    Args:
        fsrs_db: Path to fsrs.db SQLite database
        hook_log: Path to hook_events.jsonl
        output: Path to write fsrs-status.json

    Returns:
        The exported data dict
    """
    data = {
        "exported_at": datetime.now().isoformat(),
        "pipeline": [],
        "projects": {},
        "promoted_ids": [],
        "memory_projects": [],
        "recent_reinforcements": [],
        "totals": {
            "tracked": 0,
            "promoted": 0,
            "pending_promotion": 0,
        },
    }

    # --- Read FSRS database ---
    if fsrs_db.exists():
        with get_connection(str(fsrs_db)) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT memory_id, stability, difficulty, review_count, "
                    "projects_validated, promoted, promoted_date, last_review "
                    "FROM memory_reviews"
                ).fetchall()

                for row in rows:
                    projects = []
                    try:
                        projects = json.loads(row["projects_validated"] or "[]")
                    except (json.JSONDecodeError, TypeError):
                        pass

                    stability = row["stability"] or 1.0
                    review_count = row["review_count"] or 0
                    project_count = len(projects)
                    promoted = bool(row["promoted"])

                    # Path A (cross-project): stability >= 2.0, reviews >= 2, projects >= 2
                    path_a = min(
                        stability / 2.0,
                        review_count / 2.0 if review_count else 0,
                        project_count / 2.0 if project_count else 0,
                    )
                    path_a = min(max(path_a, 0), 1.0)

                    # Path B (deep reinforcement): stability >= 4.0, reviews >= 5
                    path_b = min(
                        stability / 4.0,
                        review_count / 5.0 if review_count else 0,
                    )
                    path_b = min(max(path_b, 0), 1.0)

                    entry = {
                        "memory_id": row["memory_id"],
                        "stability": round(stability, 2),
                        "review_count": review_count,
                        "projects": projects,
                        "promoted": promoted,
                        "path_a_progress": round(path_a, 2),
                        "path_b_progress": round(path_b, 2),
                    }
                    data["pipeline"].append(entry)

                    # Aggregate project counts
                    for proj in projects:
                        data["projects"][proj] = data["projects"].get(proj, 0) + 1

                # Totals
                data["totals"]["tracked"] = len(rows)
                data["totals"]["promoted"] = sum(
                    1 for r in data["pipeline"] if r["promoted"]
                )
                data["totals"]["pending_promotion"] = sum(
                    1
                    for r in data["pipeline"]
                    if not r["promoted"]
                    and (r["path_a_progress"] >= 0.75 or r["path_b_progress"] >= 0.75)
                )
                # Promoted IDs for accurate dashboard filtering
                data["promoted_ids"] = [
                    r["memory_id"] for r in data["pipeline"] if r["promoted"]
                ]
            finally:
                conn.close()

    # --- Scan memory project directories ---
    memory_base = Path.home() / ".local/share/memory"
    if memory_base.exists():
        for proj_dir in sorted(memory_base.iterdir()):
            if not proj_dir.is_dir():
                continue
            mem_subdir = proj_dir / "memories"
            if not mem_subdir.exists():
                continue
            count = sum(1 for _ in mem_subdir.glob("*.md"))
            if count > 0:
                data["memory_projects"].append({
                    "id": proj_dir.name,
                    "count": count,
                })

    # --- Read recent reinforcements from hook log ---
    if hook_log.exists():
        reinforcement_events = []
        try:
            with open(hook_log, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Match consolidation events with reinforcements
                    is_consolidation = (
                        event.get("event_type") == "memory_consolidation"
                        or event.get("hook") == "memory_consolidation"
                    )
                    if not is_consolidation:
                        continue

                    details = event.get("details", event)
                    detected = details.get("reinforcements_detected", 0)
                    if detected and detected > 0:
                        reinforcement_events.append(
                            {
                                "timestamp": event.get("timestamp", ""),
                                "session_id": event.get("session_id", ""),
                                "reinforcements": detected,
                                "promotions": details.get(
                                    "promotions_executed", 0
                                ),
                            }
                        )
        except Exception:
            pass

        # Last 20, most recent first
        data["recent_reinforcements"] = reinforcement_events[-20:][::-1]

    # --- Write output ---
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(data, f, indent=2)

    return data


if __name__ == "__main__":
    base = Path.home() / "CC/LFI/_ Operations"
    result = export_dashboard_data(
        fsrs_db=base / "memory-system-v1/fsrs.db",
        hook_log=base / "hooks/hook_events.jsonl",
        output=base / "memory-system-v1/fsrs-status.json",
    )
    print(
        f"Exported: {result['totals']['tracked']} tracked, "
        f"{result['totals']['promoted']} promoted, "
        f"{result['totals']['pending_promotion']} pending, "
        f"{len(result['recent_reinforcements'])} reinforcement events"
    )
