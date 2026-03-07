"""Cross-pollination index.

Measures knowledge transfer between client/project contexts.
Detects when a solution (memory) originating in one project appears
in or is applied to another. Quantifies whether the system actually
helps Lee reuse knowledge across engagements.

Detection uses BM25-style keyword overlap as a proxy for content
similarity — no ML dependencies, fast, explainable.
"""
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_DEFAULT_MIN_SIMILARITY = 0.5
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "with", "by", "from", "this", "that", "it", "be", "are",
    "was", "were", "has", "have", "had", "not", "as", "if", "so", "do",
    "does", "can", "will", "would", "should", "may", "might",
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cross_pollination_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_project TEXT NOT NULL,
    target_project TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    similarity_score REAL NOT NULL DEFAULT 0.0,
    context TEXT NOT NULL DEFAULT '',
    detected_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class PollinationEvent:
    event_id: int
    source_project: str
    target_project: str
    memory_id: str
    similarity_score: float
    context: str
    detected_at: str


@dataclass
class ProjectSimilarity:
    project_a: str
    project_b: str
    event_count: int
    avg_similarity: float


class CrossPollinationIndex:
    """Tracks and measures knowledge transfer between projects."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            from memory_system.config import MemorySystemConfig
            db_path = MemorySystemConfig().intelligence_db
        self._db_path = Path(db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # record_event
    # ------------------------------------------------------------------

    def record_event(
        self,
        source_project: str,
        target_project: str,
        memory_id: str,
        similarity_score: float = 1.0,
        context: str = "",
    ) -> int:
        """Record a detected cross-pollination event.

        Returns the new row id.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cross_pollination_events
                    (source_project, target_project, memory_id, similarity_score, context)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_project, target_project, memory_id, similarity_score, context),
            )
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # get_events
    # ------------------------------------------------------------------

    def get_events(
        self,
        source_project: Optional[str] = None,
        target_project: Optional[str] = None,
    ) -> list[PollinationEvent]:
        """Return all recorded events, optionally filtered by project."""
        clauses = []
        params = []
        if source_project:
            clauses.append("source_project = ?")
            params.append(source_project)
        if target_project:
            clauses.append("target_project = ?")
            params.append(target_project)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM cross_pollination_events {where} ORDER BY detected_at DESC",
                params,
            ).fetchall()

        return [
            PollinationEvent(
                event_id=r["id"],
                source_project=r["source_project"],
                target_project=r["target_project"],
                memory_id=r["memory_id"],
                similarity_score=r["similarity_score"],
                context=r["context"],
                detected_at=r["detected_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # detect_cross_pollination
    # ------------------------------------------------------------------

    def detect_cross_pollination(
        self,
        memories_by_project: dict[str, list[dict]],
        min_similarity: float = _DEFAULT_MIN_SIMILARITY,
        persist: bool = True,
    ) -> list[PollinationEvent]:
        """Detect and optionally record cross-pollination events.

        Args:
            memories_by_project: {project_id: [{"id": ..., "content": ...}]}
            min_similarity: Minimum Jaccard similarity to flag as cross-pollination.
            persist: If True, record detected events to the database.

        Returns:
            List of detected PollinationEvent objects.
        """
        projects = list(memories_by_project.keys())
        if len(projects) < 2:
            return []

        events: list[PollinationEvent] = []

        # Compare every pair of projects
        for i in range(len(projects)):
            for j in range(i + 1, len(projects)):
                proj_a = projects[i]
                proj_b = projects[j]
                mems_a = memories_by_project[proj_a]
                mems_b = memories_by_project[proj_b]

                for mem_a in mems_a:
                    for mem_b in mems_b:
                        sim = _jaccard_similarity(
                            mem_a.get("content", ""),
                            mem_b.get("content", ""),
                        )
                        if sim >= min_similarity:
                            # proj_a is source (earlier), proj_b is target
                            event_id = -1
                            if persist:
                                event_id = self.record_event(
                                    source_project=proj_a,
                                    target_project=proj_b,
                                    memory_id=mem_a.get("id", ""),
                                    similarity_score=sim,
                                    context=f"{mem_a.get('id','')} ↔ {mem_b.get('id','')}",
                                )
                            events.append(PollinationEvent(
                                event_id=event_id,
                                source_project=proj_a,
                                target_project=proj_b,
                                memory_id=mem_a.get("id", ""),
                                similarity_score=sim,
                                context=f"{mem_a.get('id','')} ↔ {mem_b.get('id','')}",
                                detected_at=datetime.utcnow().isoformat(),
                            ))
        return events

    # ------------------------------------------------------------------
    # get_project_similarity_matrix
    # ------------------------------------------------------------------

    def get_project_similarity_matrix(self) -> list[ProjectSimilarity]:
        """Aggregate events into per-pair similarity statistics.

        Returns list of ProjectSimilarity sorted by event_count descending.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    source_project,
                    target_project,
                    COUNT(*) AS event_count,
                    AVG(similarity_score) AS avg_similarity
                FROM cross_pollination_events
                GROUP BY source_project, target_project
                ORDER BY event_count DESC
                """
            ).fetchall()
        return [
            ProjectSimilarity(
                project_a=r["source_project"],
                project_b=r["target_project"],
                event_count=r["event_count"],
                avg_similarity=r["avg_similarity"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # get_most_transferred_knowledge
    # ------------------------------------------------------------------

    def get_most_transferred_knowledge(self, top_k: int = 10) -> list[dict]:
        """Return memory IDs that have been cross-pollinated most often.

        Returns [{memory_id, transfer_count}] sorted by transfer_count desc.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT memory_id, COUNT(*) AS transfer_count
                FROM cross_pollination_events
                GROUP BY memory_id
                ORDER BY transfer_count DESC
                LIMIT ?
                """,
                (top_k,),
            ).fetchall()
        return [{"memory_id": r["memory_id"], "transfer_count": r["transfer_count"]} for r in rows]

    # ------------------------------------------------------------------
    # format_summary
    # ------------------------------------------------------------------

    def format_summary(self) -> str:
        """Render a brief markdown summary of cross-pollination activity."""
        matrix = self.get_project_similarity_matrix()
        if not matrix:
            return "No cross-pollination events recorded yet."

        total = sum(s.event_count for s in matrix)
        lines = [f"**Cross-pollination: {total} event(s) across {len(matrix)} project pair(s)**"]
        for sim in matrix[:5]:
            lines.append(
                f"- **{sim.project_a}** → **{sim.project_b}**: "
                f"{sim.event_count} event(s), avg similarity {sim.avg_similarity:.0%}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Tokenize text, removing stop words and short tokens."""
    words = set(text.lower().split())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Jaccard similarity between two texts (token sets)."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)
