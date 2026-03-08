"""Skill evolution tracker — snapshots SKILL.md files, diffs changes, classifies them.

Stores a history of SKILL.md snapshots per skill, computes unified diffs, and
classifies each change as initial / meaningful / cosmetic / unchanged / missing.

Usage:
    from memory_system.skill_evolution import SkillEvolutionTracker

    tracker = SkillEvolutionTracker()
    snapshot = tracker.snapshot("my-skill")
    print(snapshot.change_type)  # "initial", "meaningful", "cosmetic", "unchanged", "missing"

    history = tracker.get_history("my-skill")
    last_update = tracker.get_last_meaningful_update("my-skill")
"""

import difflib
import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memory_system.config import cfg

logger = logging.getLogger(__name__)

# All valid change type strings.
CHANGE_TYPES: frozenset[str] = frozenset(
    {"initial", "meaningful", "cosmetic", "unchanged", "missing"}
)

_MEANINGFUL_TYPES = frozenset({"initial", "meaningful"})

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS skill_evolution_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name      TEXT    NOT NULL,
    content_hash    TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    diff            TEXT    NOT NULL DEFAULT '',
    change_type     TEXT    NOT NULL,
    change_summary  TEXT    NOT NULL DEFAULT '',
    snapshotted_at  TEXT    NOT NULL
)
"""

_IDX_SKILL = "CREATE INDEX IF NOT EXISTS idx_ses_skill ON skill_evolution_snapshots (skill_name)"
_IDX_AT = "CREATE INDEX IF NOT EXISTS idx_ses_at ON skill_evolution_snapshots (snapshotted_at)"


@dataclass
class SkillSnapshot:
    """One point-in-time snapshot of a skill's SKILL.md."""

    id: int
    skill_name: str
    content_hash: str
    content: str
    diff: str
    change_type: str
    change_summary: str
    snapshotted_at: str


class SkillEvolutionTracker:
    """Track how SKILL.md files evolve over time.

    Each call to snapshot() reads the skill's SKILL.md, hashes the content,
    computes a diff against the previous snapshot, classifies the change, and
    persists to SQLite.
    """

    def __init__(
        self,
        db_path: str | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        self._db_path = str(db_path) if db_path else str(cfg.intelligence_db_path)
        self._skills_dir = Path(skills_dir) if skills_dir else cfg.skills_dir
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ── Setup ─────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_IDX_SKILL)
        self._conn.execute(_IDX_AT)
        self._conn.commit()

    # ── Public API ────────────────────────────────────────────────────────

    def snapshot(self, skill_name: str) -> SkillSnapshot:
        """Snapshot the current SKILL.md for skill_name and persist it.

        Returns a SkillSnapshot describing what changed (or didn't).
        """
        skill_md = self._skills_dir / skill_name / "SKILL.md"

        if not skill_md.exists():
            return self._record(
                skill_name=skill_name,
                content="",
                content_hash=_hash(""),
                diff="",
                change_type="missing",
                change_summary="SKILL.md not found",
            )

        content = skill_md.read_text(errors="ignore")
        content_hash = _hash(content)

        prev = self._last_snapshot(skill_name)

        if prev is None:
            return self._record(
                skill_name=skill_name,
                content=content,
                content_hash=content_hash,
                diff="",
                change_type="initial",
                change_summary="First snapshot",
            )

        if prev["content_hash"] == content_hash:
            return self._record(
                skill_name=skill_name,
                content=content,
                content_hash=content_hash,
                diff="",
                change_type="unchanged",
                change_summary="No change since last snapshot",
            )

        diff = _unified_diff(prev["content"], content, skill_name)
        change_type = _classify(prev["content"], content)
        change_summary = _summarize(change_type, diff)

        return self._record(
            skill_name=skill_name,
            content=content,
            content_hash=content_hash,
            diff=diff,
            change_type=change_type,
            change_summary=change_summary,
        )

    def snapshot_all(self) -> list[SkillSnapshot]:
        """Snapshot all skill subdirectories. Returns list of SkillSnapshots."""
        if not self._skills_dir.exists():
            return []
        results = []
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                results.append(self.snapshot(entry.name))
            except Exception:
                logger.debug("Failed to snapshot skill %s", entry.name, exc_info=True)
        return results

    def get_history(self, skill_name: str) -> list[SkillSnapshot]:
        """Return all snapshots for skill_name in chronological order."""
        rows = self._conn.execute(
            "SELECT * FROM skill_evolution_snapshots WHERE skill_name = ?"
            " ORDER BY snapshotted_at ASC, id ASC",
            (skill_name,),
        ).fetchall()
        return [_row_to_snapshot(r) for r in rows]

    def get_last_meaningful_update(self, skill_name: str) -> datetime | None:
        """Return the datetime of the most recent initial/meaningful snapshot, or None."""
        row = self._conn.execute(
            "SELECT snapshotted_at FROM skill_evolution_snapshots"
            " WHERE skill_name = ? AND change_type IN ('initial', 'meaningful')"
            " ORDER BY snapshotted_at DESC, id DESC LIMIT 1",
            (skill_name,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["snapshotted_at"])

    def has_changed(self, skill_name: str) -> bool:
        """True if the current SKILL.md differs from the last snapshot (or no snapshot exists).

        Returns False if both the last snapshot and current state are missing.
        """
        skill_md = self._skills_dir / skill_name / "SKILL.md"
        current_content = skill_md.read_text(errors="ignore") if skill_md.exists() else ""
        current_hash = _hash(current_content)

        prev = self._last_snapshot(skill_name)
        if prev is None:
            # No previous snapshot — treat as changed unless there's nothing to snapshot.
            return skill_md.exists()

        return prev["content_hash"] != current_hash

    def get_skills_by_change_type(self, change_type: str) -> list[str]:
        """Return skill names whose most recent snapshot has the given change_type."""
        rows = self._conn.execute(
            """
            SELECT skill_name
            FROM skill_evolution_snapshots s1
            WHERE change_type = ?
              AND id = (
                SELECT MAX(id) FROM skill_evolution_snapshots s2
                WHERE s2.skill_name = s1.skill_name
              )
            """,
            (change_type,),
        ).fetchall()
        return [r["skill_name"] for r in rows]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _last_snapshot(self, skill_name: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM skill_evolution_snapshots WHERE skill_name = ?"
            " ORDER BY id DESC LIMIT 1",
            (skill_name,),
        ).fetchone()

    def _record(
        self,
        skill_name: str,
        content: str,
        content_hash: str,
        diff: str,
        change_type: str,
        change_summary: str,
    ) -> SkillSnapshot:
        snapshotted_at = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO skill_evolution_snapshots"
            " (skill_name, content_hash, content, diff, change_type, change_summary, snapshotted_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (skill_name, content_hash, content, diff, change_type, change_summary, snapshotted_at),
        )
        self._conn.commit()
        return SkillSnapshot(
            id=cur.lastrowid,
            skill_name=skill_name,
            content_hash=content_hash,
            content=content,
            diff=diff,
            change_type=change_type,
            change_summary=change_summary,
            snapshotted_at=snapshotted_at,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _normalize(content: str) -> str:
    """Strip trailing whitespace from each line for cosmetic comparison."""
    return "\n".join(line.rstrip() for line in content.splitlines())


def _classify(prev: str, new: str) -> str:
    """Classify a content change as 'meaningful' or 'cosmetic'.

    Cosmetic: only trailing whitespace / empty line differences.
    Meaningful: anything else.
    """
    if _normalize(prev) == _normalize(new):
        return "cosmetic"
    return "meaningful"


def _unified_diff(prev: str, new: str, skill_name: str) -> str:
    lines = list(
        difflib.unified_diff(
            prev.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{skill_name}/SKILL.md (prev)",
            tofile=f"{skill_name}/SKILL.md (new)",
        )
    )
    return "".join(lines)


def _summarize(change_type: str, diff: str) -> str:
    if change_type == "meaningful":
        added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        return f"+{added}/-{removed} lines"
    if change_type == "cosmetic":
        return "Whitespace/formatting only"
    return ""


def _row_to_snapshot(row: sqlite3.Row) -> SkillSnapshot:
    return SkillSnapshot(
        id=row["id"],
        skill_name=row["skill_name"],
        content_hash=row["content_hash"],
        content=row["content"],
        diff=row["diff"],
        change_type=row["change_type"],
        change_summary=row["change_summary"],
        snapshotted_at=row["snapshotted_at"],
    )
