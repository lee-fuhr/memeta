"""BibleEvolutionEngine — tracks Build Bible changes over time + principle reinforcement.

Stores a per-section snapshot history with unified diffs, and records session-experience
evidence (supporting / conflicting) so you can see which principles are battle-tested,
which are untested, and which are contested by real-world outcomes.

Two SQLite tables (default: `bible_evolution.db` alongside `intelligence.db`):
  - `bible_section_snapshots` — change history per section
  - `bible_experiences`       — supporting/conflicting evidence per section

Usage:
    engine = BibleEvolutionEngine()
    snap = engine.snapshot(Path("Build Bible.md"))
    print(f"Changed: {snap.changed_count}  Unchanged: {snap.unchanged_count}")

    engine.record_experience("1.1", memory_id="mem-abc", experience_type="supporting")
    score = engine.get_reinforcement_score("1.1")  # -1.0 → 1.0
    report = engine.get_section_health_report()
"""
import difflib
import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section parsing constants (mirrors BibleImporter — kept local for independence)
# ---------------------------------------------------------------------------

_SECTION_TYPE_MAP: dict[int, str] = {
    1: "principle",
    2: "pattern",
    6: "anti_pattern",
}

_SUBSECTION_RE = re.compile(r"^###\s+(\d+)\.(\d+)\s+(.+)$", re.MULTILINE)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS bible_section_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id      TEXT    NOT NULL,
    section_type    TEXT    NOT NULL,
    content_hash    TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    diff            TEXT    NOT NULL DEFAULT '',
    change_type     TEXT    NOT NULL,
    snapshotted_at  TEXT    NOT NULL
)
"""

_CREATE_EXPERIENCES = """
CREATE TABLE IF NOT EXISTS bible_experiences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id      TEXT    NOT NULL,
    memory_id       TEXT    NOT NULL,
    experience_type TEXT    NOT NULL,
    strength        REAL    NOT NULL DEFAULT 1.0,
    recorded_at     TEXT    NOT NULL
)
"""

_IDX_SNAP_SECTION = (
    "CREATE INDEX IF NOT EXISTS idx_bss_section "
    "ON bible_section_snapshots (section_id)"
)
_IDX_SNAP_AT = (
    "CREATE INDEX IF NOT EXISTS idx_bss_at "
    "ON bible_section_snapshots (snapshotted_at)"
)
_IDX_EXP_SECTION = (
    "CREATE INDEX IF NOT EXISTS idx_be_section "
    "ON bible_experiences (section_id)"
)

_VALID_EXPERIENCE_TYPES = frozenset({"supporting", "conflicting"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BibleSectionSnapshot:
    """One point-in-time snapshot of a single Bible section."""
    section_id: str
    section_type: str
    content_hash: str
    change_type: str      # initial | changed | unchanged
    diff: str
    snapshotted_at: str


@dataclass
class BibleSnapshot:
    """Result of one full Bible snapshot run."""
    snapshotted_at: str
    sections: list[BibleSectionSnapshot] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return sum(1 for s in self.sections if s.change_type == "changed")

    @property
    def unchanged_count(self) -> int:
        return sum(1 for s in self.sections if s.change_type == "unchanged")


@dataclass
class BibleExperience:
    """A recorded supporting or conflicting experience against a Bible section."""
    section_id: str
    memory_id: str
    experience_type: str  # supporting | conflicting
    strength: float
    recorded_at: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BibleEvolutionEngine:
    """Track Build Bible section changes and principle-reinforcement evidence."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            from memory_system.config import cfg
            db_path = cfg.intelligence_db_path.parent / "bible_evolution.db"
        self._db_path = Path(db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal DB helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_SNAPSHOTS)
            conn.execute(_CREATE_EXPERIENCES)
            conn.execute(_IDX_SNAP_SECTION)
            conn.execute(_IDX_SNAP_AT)
            conn.execute(_IDX_EXP_SECTION)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, bible_path: Path) -> BibleSnapshot:
        """Parse the Bible and snapshot every importable section.

        Compares each section's content hash to its previous snapshot to
        classify the change as initial / changed / unchanged.
        """
        text = bible_path.read_text(encoding="utf-8")
        parsed = self._parse_sections(text)
        now = datetime.now(timezone.utc).isoformat()
        snap_sections: list[BibleSectionSnapshot] = []

        with self._connect() as conn:
            for sec in parsed:
                sid = sec["section_id"]
                stype = sec["section_type"]
                content = sec["content"]
                content_hash = hashlib.sha256(content.strip().encode()).hexdigest()[:16]

                prev = conn.execute(
                    "SELECT content_hash, content FROM bible_section_snapshots "
                    "WHERE section_id = ? ORDER BY snapshotted_at DESC LIMIT 1",
                    (sid,),
                ).fetchone()

                if prev is None:
                    change_type = "initial"
                    diff = ""
                elif prev["content_hash"] == content_hash:
                    change_type = "unchanged"
                    diff = ""
                else:
                    change_type = "changed"
                    diff = "\n".join(difflib.unified_diff(
                        prev["content"].splitlines(),
                        content.splitlines(),
                        fromfile=f"{sid} (prev)",
                        tofile=f"{sid} (new)",
                        lineterm="",
                    ))

                conn.execute(
                    "INSERT INTO bible_section_snapshots "
                    "(section_id, section_type, content_hash, content, diff, change_type, snapshotted_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sid, stype, content_hash, content, diff, change_type, now),
                )

                snap_sections.append(BibleSectionSnapshot(
                    section_id=sid,
                    section_type=stype,
                    content_hash=content_hash,
                    change_type=change_type,
                    diff=diff,
                    snapshotted_at=now,
                ))

        return BibleSnapshot(snapshotted_at=now, sections=snap_sections)

    def get_history(self, section_id: str) -> list[BibleSectionSnapshot]:
        """Snapshot history for a section, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bible_section_snapshots "
                "WHERE section_id = ? ORDER BY snapshotted_at DESC",
                (section_id,),
            ).fetchall()
        return [
            BibleSectionSnapshot(
                section_id=row["section_id"],
                section_type=row["section_type"],
                content_hash=row["content_hash"],
                change_type=row["change_type"],
                diff=row["diff"],
                snapshotted_at=row["snapshotted_at"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------

    def record_experience(
        self,
        section_id: str,
        memory_id: str,
        experience_type: str,
        strength: float = 1.0,
    ) -> BibleExperience:
        """Record that a memory supports or conflicts with a Bible section.

        Args:
            section_id:      Bible section (e.g. "1.1").
            memory_id:       ID of the memory providing evidence.
            experience_type: "supporting" or "conflicting".
            strength:        Evidence weight, 0.0–1.0 (default 1.0).

        Raises:
            ValueError: if experience_type is not "supporting" or "conflicting".
        """
        if experience_type not in _VALID_EXPERIENCE_TYPES:
            raise ValueError(
                f"experience_type must be one of {sorted(_VALID_EXPERIENCE_TYPES)!r}, "
                f"got {experience_type!r}"
            )
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO bible_experiences "
                "(section_id, memory_id, experience_type, strength, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (section_id, memory_id, experience_type, strength, now),
            )
        return BibleExperience(
            section_id=section_id,
            memory_id=memory_id,
            experience_type=experience_type,
            strength=strength,
            recorded_at=now,
        )

    def get_experiences(self, section_id: str) -> list[BibleExperience]:
        """All recorded experiences for a section, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bible_experiences WHERE section_id = ? "
                "ORDER BY recorded_at DESC",
                (section_id,),
            ).fetchall()
        return [
            BibleExperience(
                section_id=row["section_id"],
                memory_id=row["memory_id"],
                experience_type=row["experience_type"],
                strength=row["strength"],
                recorded_at=row["recorded_at"],
            )
            for row in rows
        ]

    def get_reinforcement_score(self, section_id: str) -> float:
        """Net reinforcement score for a section.

        Returns a value in [-1.0, 1.0] where:
          +1.0 = all experiences are strongly supporting
          -1.0 = all experiences are strongly conflicting
           0.0 = no experiences, or equal weight on both sides

        Formula: (sum_supporting - sum_conflicting) / (sum_supporting + sum_conflicting)
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT experience_type, strength FROM bible_experiences WHERE section_id = ?",
                (section_id,),
            ).fetchall()

        if not rows:
            return 0.0

        supporting = sum(r["strength"] for r in rows if r["experience_type"] == "supporting")
        conflicting = sum(r["strength"] for r in rows if r["experience_type"] == "conflicting")
        total = supporting + conflicting
        if total == 0.0:
            return 0.0
        return (supporting - conflicting) / total

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    def get_stale_sections(self, threshold_days: int = 30) -> list[str]:
        """Return section IDs whose most recent snapshot is older than threshold_days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=threshold_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT section_id, MAX(snapshotted_at) AS latest "
                "FROM bible_section_snapshots "
                "GROUP BY section_id "
                "HAVING latest < ?",
                (cutoff,),
            ).fetchall()
        return [row["section_id"] for row in rows]

    # ------------------------------------------------------------------
    # Health report
    # ------------------------------------------------------------------

    def get_section_health_report(self) -> dict[str, dict]:
        """Health summary for every tracked section.

        Returns:
            dict mapping section_id → {
                section_type, last_snapshotted, reinforcement_score, experience_count
            }
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT section_id, section_type, MAX(snapshotted_at) AS last_snapshotted "
                "FROM bible_section_snapshots GROUP BY section_id"
            ).fetchall()

        report: dict[str, dict] = {}
        for row in rows:
            sid = row["section_id"]
            exps = self.get_experiences(sid)
            report[sid] = {
                "section_type": row["section_type"],
                "last_snapshotted": row["last_snapshotted"],
                "reinforcement_score": self.get_reinforcement_score(sid),
                "experience_count": len(exps),
            }
        return report

    # ------------------------------------------------------------------
    # Parsing (mirrors BibleImporter — kept local for independence)
    # ------------------------------------------------------------------

    def _parse_sections(self, text: str) -> list[dict]:
        """Extract importable sections from Bible markdown text."""
        matches = list(_SUBSECTION_RE.finditer(text))
        sections = []
        for i, match in enumerate(matches):
            top_num = int(match.group(1))
            if top_num not in _SECTION_TYPE_MAP:
                continue
            section_id = f"{match.group(1)}.{match.group(2)}"
            section_type = _SECTION_TYPE_MAP[top_num]
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append({
                    "section_id": section_id,
                    "section_type": section_type,
                    "content": content,
                })
        return sections
