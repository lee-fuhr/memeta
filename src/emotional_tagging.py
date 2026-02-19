"""
Emotional tagging and flashbulb prioritization

Detects emotional valence (-1.0 to +1.0) and arousal (0.0 to 1.0) from
session context surrounding a memory's creation. High-arousal memories
get slower decay rates (1.5x multiplier) and higher retrieval weights.

Based on cognitive psychology:
- Brown & Kulik (1977) flashbulb memory
- McGaugh (2004) amygdala-mediated consolidation

Heuristic signals (no LLM needed):
- Exclamation marks: +0.1 arousal per ! (cap 0.5)
- ALL CAPS words: +0.15 each (cap 0.5)
- Rapid message pace: >5 messages/minute = +0.4 arousal
- Frustration keywords: +0.3 arousal, -0.5 valence
- Success keywords: +0.3 arousal, +0.7 valence
- Correction markers: +0.2 arousal, -0.3 valence
- Question clusters (3+ in 5 messages): +0.2 arousal
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class EmotionalTag:
    """Emotional annotation for a memory."""

    memory_id: str
    valence: float  # -1.0 (negative) to +1.0 (positive)
    arousal: float  # 0.0 (calm) to 1.0 (intense)
    signals: list[str]  # what triggered the tag
    created_at: str


# ── Keyword sets ──────────────────────────────────────────────────────────


_FRUSTRATION_KEYWORDS = re.compile(
    r"\b(broken|bug|error|crash|crashed|crashing|failed|failing)\b", re.IGNORECASE
)

_SUCCESS_KEYWORDS = re.compile(
    r"(?<!\w)(works\s*[!]|finally|got it|solved|fixed)(?!\w)", re.IGNORECASE
)

_CORRECTION_MARKERS = re.compile(
    r"\b(actually no|actually,? that'?s|wait,? no|wait,? that'?s wrong)\b|no that'?s wrong",
    re.IGNORECASE,
)

# Minimum length for ALL CAPS word to count (avoids "I", "A", "OK")
_MIN_CAPS_LENGTH = 2


# ── EmotionalTagger ──────────────────────────────────────────────────────


class EmotionalTagger:
    """Analyze and store emotional tags for memories."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_db()

    # ── Database ──────────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emotional_tags (
                    memory_id TEXT PRIMARY KEY,
                    valence REAL NOT NULL,
                    arousal REAL NOT NULL,
                    signals TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotional_arousal ON emotional_tags(arousal)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_emotional_valence ON emotional_tags(valence)"
            )
            conn.commit()
        finally:
            conn.close()

    # ── Analysis ──────────────────────────────────────────────────────

    def analyze_context(
        self,
        messages: list[dict],
        timestamps: list[str] | None = None,
    ) -> dict:
        """Analyze emotional content of messages.

        Returns dict with keys: valence, arousal, signals.
        """
        if not messages:
            return {"valence": 0.0, "arousal": 0.0, "signals": []}

        valence = 0.0
        arousal = 0.0
        signals: list[str] = []

        # Combine all message content
        all_text = " ".join(m.get("content", "") for m in messages)

        if not all_text.strip():
            return {"valence": 0.0, "arousal": 0.0, "signals": []}

        # ── Signal 1: Exclamation marks ───────────────────────────────
        excl_count = all_text.count("!")
        if excl_count > 0:
            excl_arousal = min(excl_count * 0.1, 0.5)
            arousal += excl_arousal
            signals.append("exclamation_marks")

        # ── Signal 2: ALL CAPS words ──────────────────────────────────
        words = re.findall(r"\b[A-Z]{2,}\b", all_text)
        # Filter: only words that are genuinely ALL CAPS (at least 2 chars)
        caps_words = [w for w in words if len(w) >= _MIN_CAPS_LENGTH]
        if caps_words:
            caps_arousal = min(len(caps_words) * 0.15, 0.5)
            arousal += caps_arousal
            signals.append("all_caps_words")

        # ── Signal 3: Frustration keywords ────────────────────────────
        frustration_matches = _FRUSTRATION_KEYWORDS.findall(all_text)
        if frustration_matches:
            arousal += 0.3
            valence -= 0.5
            signals.append("frustration_keywords")

        # ── Signal 4: Success keywords ────────────────────────────────
        success_matches = _SUCCESS_KEYWORDS.findall(all_text)
        if success_matches:
            arousal += 0.3
            valence += 0.7
            signals.append("success_keywords")

        # ── Signal 5: Correction markers ──────────────────────────────
        correction_matches = _CORRECTION_MARKERS.findall(all_text)
        if correction_matches:
            arousal += 0.2
            valence -= 0.3
            signals.append("correction_markers")

        # ── Signal 6: Rapid message pace ──────────────────────────────
        if timestamps and len(timestamps) >= 2:
            try:
                parsed = [datetime.fromisoformat(ts) for ts in timestamps]
                total_seconds = (parsed[-1] - parsed[0]).total_seconds()
                if total_seconds > 0:
                    msgs_per_minute = (len(timestamps) / total_seconds) * 60
                    if msgs_per_minute > 5:
                        arousal += 0.4
                        signals.append("rapid_message_pace")
            except (ValueError, TypeError):
                pass  # malformed timestamps — skip signal

        # ── Signal 7: Question clusters ───────────────────────────────
        # Check for 3+ questions in any window of 5 messages
        question_cluster_found = False
        window_size = min(5, len(messages))
        for i in range(len(messages) - window_size + 1):
            window = messages[i : i + window_size]
            q_count = sum(
                1 for m in window if "?" in m.get("content", "")
            )
            if q_count >= 3:
                question_cluster_found = True
                break
        if question_cluster_found:
            arousal += 0.2
            signals.append("question_cluster")

        # ── Clamp values ──────────────────────────────────────────────
        valence = max(-1.0, min(1.0, valence))
        arousal = max(0.0, min(1.0, arousal))

        return {"valence": valence, "arousal": arousal, "signals": signals}

    # ── Tagging ───────────────────────────────────────────────────────

    def tag_memory(
        self,
        memory_id: str,
        context_messages: list[dict],
        timestamps: list[str] | None = None,
    ) -> EmotionalTag:
        """Create emotional tag for a memory based on surrounding context."""
        analysis = self.analyze_context(context_messages, timestamps)
        now = datetime.now().isoformat()

        tag = EmotionalTag(
            memory_id=memory_id,
            valence=analysis["valence"],
            arousal=analysis["arousal"],
            signals=analysis["signals"],
            created_at=now,
        )

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO emotional_tags
                    (memory_id, valence, arousal, signals, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tag.memory_id,
                    tag.valence,
                    tag.arousal,
                    json.dumps(tag.signals),
                    tag.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return tag

    # ── Retrieval ─────────────────────────────────────────────────────

    def get_tag(self, memory_id: str) -> EmotionalTag | None:
        """Retrieve emotional tag for a memory."""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT memory_id, valence, arousal, signals, created_at "
                "FROM emotional_tags WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        return EmotionalTag(
            memory_id=row[0],
            valence=row[1],
            arousal=row[2],
            signals=json.loads(row[3]),
            created_at=row[4],
        )

    def get_high_arousal_memories(
        self, threshold: float = 0.5
    ) -> list[EmotionalTag]:
        """Find memories with high emotional arousal."""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT memory_id, valence, arousal, signals, created_at "
                "FROM emotional_tags WHERE arousal >= ? "
                "ORDER BY arousal DESC",
                (threshold,),
            ).fetchall()
        finally:
            conn.close()

        return [
            EmotionalTag(
                memory_id=r[0],
                valence=r[1],
                arousal=r[2],
                signals=json.loads(r[3]),
                created_at=r[4],
            )
            for r in rows
        ]

    def get_decay_multiplier(self, memory_id: str) -> float:
        """Return decay multiplier: 1.5x for arousal > 0.5, 1.0x otherwise."""
        tag = self.get_tag(memory_id)
        if tag is None or tag.arousal <= 0.5:
            return 1.0
        return 1.5

    def get_emotional_distribution(self) -> dict:
        """Return emotional distribution summary."""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT valence, arousal FROM emotional_tags"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "high_arousal_count": 0,
                "mean_valence": 0.0,
                "mean_arousal": 0.0,
            }

        positive = sum(1 for v, _ in rows if v > 0.1)
        negative = sum(1 for v, _ in rows if v < -0.1)
        neutral = len(rows) - positive - negative
        high_arousal = sum(1 for _, a in rows if a > 0.5)

        mean_valence = sum(v for v, _ in rows) / len(rows)
        mean_arousal = sum(a for _, a in rows) / len(rows)

        return {
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "high_arousal_count": high_arousal,
            "mean_valence": round(mean_valence, 4),
            "mean_arousal": round(mean_arousal, 4),
        }

    def get_flashbulb_memories(
        self, min_arousal: float = 0.7
    ) -> list[EmotionalTag]:
        """Return memories with very high arousal (flashbulb-quality encoding)."""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT memory_id, valence, arousal, signals, created_at "
                "FROM emotional_tags WHERE arousal >= ? "
                "ORDER BY arousal DESC",
                (min_arousal,),
            ).fetchall()
        finally:
            conn.close()

        return [
            EmotionalTag(
                memory_id=r[0],
                valence=r[1],
                arousal=r[2],
                signals=json.loads(r[3]),
                created_at=r[4],
            )
            for r in rows
        ]
