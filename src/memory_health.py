"""
Memory health score — aggregate quality metric for the memory corpus.

Feature 21: Computes a 0-100 health score from six weighted components,
grades it A-F, tracks history, and fires alerts when quality drops.

Components:
- pct_high_confidence   (0.20) — % of memories with confidence >= 0.7
- pct_recently_confirmed(0.20) — % confirmed in last 30 days
- pct_with_provenance   (0.15) — % that have a source/session attribution
- avg_freshness         (0.20) — inverse-age score across corpus
- low_contradiction_rate(0.15) — 100 minus (% of memories with contradictions)
- compression_potential  (0.10) — 100 minus estimated redundancy %
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


COMPONENT_WEIGHTS: Dict[str, float] = {
    "pct_high_confidence": 0.20,
    "pct_recently_confirmed": 0.20,
    "pct_with_provenance": 0.15,
    "avg_freshness": 0.20,
    "low_contradiction_rate": 0.15,
    "compression_potential": 0.10,
}


class MemoryHealthScore:
    """Compute, record, and query memory health scores."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(
                Path.home() / ".local/share/memory" / "intelligence.db"
            )
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ── schema ────────────────────────────────────────────────────────────

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS health_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score INTEGER NOT NULL,
                grade TEXT NOT NULL,
                components_json TEXT NOT NULL,
                computed_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    # ── public API ────────────────────────────────────────────────────────

    def compute(
        self,
        memories: Optional[List[Dict]] = None,
        stats: Optional[Dict] = None,
    ) -> Dict:
        """
        Compute a health score from memories and/or pre-aggregated stats.

        If neither argument is provided, returns a baseline score of 50.

        Args:
            memories: list of memory dicts (confidence_score, confirmations,
                      contradictions, source, created_at, etc.)
            stats:    pre-computed component values keyed by component name
                      (each 0-100).

        Returns:
            {score, grade, components, computed_at}
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

        if memories is None and stats is None:
            components = {k: 50.0 for k in COMPONENT_WEIGHTS}
            score = 50
            return {
                "score": score,
                "grade": self._score_to_grade(score),
                "components": components,
                "computed_at": now,
            }

        # Build component scores
        if stats is not None:
            # Caller supplied ready-made component values; fill gaps with 50
            components = {
                k: float(stats.get(k, 50.0)) for k in COMPONENT_WEIGHTS
            }
        else:
            components = self._compute_components(memories)  # type: ignore[arg-type]

        score = self._weighted_score(components)

        return {
            "score": score,
            "grade": self._score_to_grade(score),
            "components": components,
            "computed_at": now,
        }

    def record(self, score_dict: Dict) -> None:
        """Persist a score dict (as returned by compute) to the DB."""
        self.conn.execute(
            "INSERT INTO health_scores (score, grade, components_json, computed_at) "
            "VALUES (?, ?, ?, ?)",
            (
                score_dict["score"],
                score_dict["grade"],
                json.dumps(score_dict["components"]),
                score_dict["computed_at"],
            ),
        )
        self.conn.commit()

    def get_latest(self) -> Optional[Dict]:
        """Return the most recently recorded score, or None."""
        row = self.conn.execute(
            "SELECT score, grade, components_json, computed_at "
            "FROM health_scores ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "score": row["score"],
            "grade": row["grade"],
            "components": json.loads(row["components_json"]),
            "computed_at": row["computed_at"],
        }

    def get_trend(self, days: int = 30) -> List[Dict]:
        """Return historical scores from the last *days* days."""
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
            timespec="seconds"
        )
        rows = self.conn.execute(
            "SELECT score, grade, components_json, computed_at "
            "FROM health_scores WHERE computed_at >= ? ORDER BY computed_at",
            (cutoff,),
        ).fetchall()
        return [
            {
                "score": r["score"],
                "grade": r["grade"],
                "components": json.loads(r["components_json"]),
                "computed_at": r["computed_at"],
            }
            for r in rows
        ]

    def check_alert(self, threshold: int = 50) -> Optional[str]:
        """Return an alert message if the latest score is below *threshold*."""
        latest = self.get_latest()
        if latest is None:
            return None
        if latest["score"] < threshold:
            return (
                f"Memory health score {latest['score']} (grade {latest['grade']}) "
                f"is below threshold {threshold}. "
                f"Weakest component: {self._weakest_component(latest['components'])}."
            )
        return None

    # ── internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _score_to_grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    @staticmethod
    def _weighted_score(components: Dict[str, float]) -> int:
        total = sum(
            components[k] * COMPONENT_WEIGHTS[k] for k in COMPONENT_WEIGHTS
        )
        return max(0, min(100, round(total)))

    @staticmethod
    def _weakest_component(components: Dict[str, float]) -> str:
        return min(components, key=lambda k: components[k])

    # ── component computation from raw memories ───────────────────────────

    @staticmethod
    def _compute_components(memories: List[Dict]) -> Dict[str, float]:
        n = len(memories)
        if n == 0:
            return {k: 0.0 for k in COMPONENT_WEIGHTS}

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. pct_high_confidence: % with confidence >= 0.7
        high_conf = sum(
            1 for m in memories if m.get("confidence_score", 0.5) >= 0.7
        )
        pct_high_confidence = (high_conf / n) * 100

        # 2. pct_recently_confirmed: % confirmed in last 30 days
        thirty_days_ago = now - timedelta(days=30)
        recently_confirmed = 0
        for m in memories:
            confirmed_at = m.get("last_confirmed")
            if confirmed_at:
                if isinstance(confirmed_at, str):
                    try:
                        confirmed_at = datetime.fromisoformat(confirmed_at)
                    except (ValueError, TypeError):
                        continue
                if confirmed_at >= thirty_days_ago:
                    recently_confirmed += 1
        pct_recently_confirmed = (recently_confirmed / n) * 100

        # 3. pct_with_provenance: % that have a source or session_id
        with_prov = sum(
            1
            for m in memories
            if m.get("source") or m.get("session_id")
        )
        pct_with_provenance = (with_prov / n) * 100

        # 4. avg_freshness: 100 * avg(max(0, 1 - age_days/365))
        freshness_scores = []
        for m in memories:
            created = m.get("created_at")
            if created:
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created)
                    except (ValueError, TypeError):
                        freshness_scores.append(0.5)
                        continue
                age_days = (now - created).total_seconds() / 86400
                freshness_scores.append(max(0.0, 1.0 - age_days / 365))
            else:
                freshness_scores.append(0.5)
        avg_freshness = (sum(freshness_scores) / len(freshness_scores)) * 100

        # 5. low_contradiction_rate: 100 - (% with contradictions > 0)
        contradicted = sum(
            1 for m in memories if m.get("contradictions", 0) > 0
        )
        low_contradiction_rate = 100 - (contradicted / n) * 100

        # 6. compression_potential: 100 - estimated redundancy %
        # Heuristic: if many memories share the same tag set it hints
        # redundancy.  Without embeddings we use a simple proxy: count of
        # duplicate titles / total.
        titles = [m.get("title", "") for m in memories if m.get("title")]
        if titles:
            unique = len(set(titles))
            redundancy_pct = ((len(titles) - unique) / len(titles)) * 100
        else:
            redundancy_pct = 0.0
        compression_potential = 100 - redundancy_pct

        return {
            "pct_high_confidence": round(pct_high_confidence, 2),
            "pct_recently_confirmed": round(pct_recently_confirmed, 2),
            "pct_with_provenance": round(pct_with_provenance, 2),
            "avg_freshness": round(avg_freshness, 2),
            "low_contradiction_rate": round(low_contradiction_rate, 2),
            "compression_potential": round(compression_potential, 2),
        }

    # ── cleanup ───────────────────────────────────────────────────────────

    def close(self):
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
