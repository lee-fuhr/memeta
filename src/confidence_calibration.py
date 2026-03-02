"""
Confidence calibration — Track predicted vs actual confidence.

Feature 130: Persistence layer for calibration curves.
Logs predictions and outcomes, computes binned calibration stats,
and detects implicit memory usage via word overlap heuristic.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CalibrationEvent:
    memory_id: str
    predicted_confidence: float
    actual_outcome: bool
    signal_type: str
    timestamp: str = ""


@dataclass
class CalibrationBin:
    bin_label: str
    predicted_avg: float
    actual_hit_rate: float
    sample_count: int


STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "at", "for", "and", "or", "but", "not", "it", "this", "that", "with",
    "from", "as", "by", "be", "has", "had", "have", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "i", "you",
    "he", "she", "we", "they", "me", "him", "her", "us", "them", "my",
    "your", "his", "its", "our", "their", "what", "which", "who", "whom",
    "how", "when", "where", "why", "if", "then", "so", "no", "yes",
})


def _init_calibration_table(db_path: str) -> None:
    """Create the calibration table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS confidence_calibration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            predicted_confidence REAL NOT NULL,
            actual_outcome INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_calibration_event(
    db_path: str,
    memory_id: str,
    predicted: float,
    actual_outcome: bool,
    signal_type: str,
) -> int:
    """Log a calibration event to the database.

    Returns: row ID of inserted event.
    """
    _init_calibration_table(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """
        INSERT INTO confidence_calibration_log
            (memory_id, predicted_confidence, actual_outcome, signal_type, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (memory_id, predicted, int(actual_outcome), signal_type, ts),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def get_calibration_stats(
    db_path: str, bin_size: float = 0.1
) -> dict[str, CalibrationBin]:
    """Compute calibration statistics binned by predicted confidence.

    Returns: dict mapping bin_label -> CalibrationBin.
    Empty dict if no events logged.
    """
    _init_calibration_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT predicted_confidence, actual_outcome FROM confidence_calibration_log"
    ).fetchall()
    conn.close()

    if not rows:
        return {}

    bins: dict[str, list[tuple[float, int]]] = {}
    for row in rows:
        pred = row["predicted_confidence"]
        outcome = row["actual_outcome"]
        bin_lower = int(pred / bin_size) * bin_size
        # Clamp to [0.0, 0.9] for the 0.9-1.0 bin
        bin_lower = min(bin_lower, 1.0 - bin_size)
        bin_upper = bin_lower + bin_size
        label = f"{bin_lower:.1f}-{bin_upper:.1f}"
        bins.setdefault(label, []).append((pred, outcome))

    result: dict[str, CalibrationBin] = {}
    for label, entries in bins.items():
        preds = [e[0] for e in entries]
        outcomes = [e[1] for e in entries]
        result[label] = CalibrationBin(
            bin_label=label,
            predicted_avg=sum(preds) / len(preds),
            actual_hit_rate=sum(outcomes) / len(outcomes),
            sample_count=len(entries),
        )
    return result


def detect_implicit_usage(surfaced_content: str, assistant_response: str) -> bool:
    """Detect if surfaced memory content was implicitly used in response.

    Simple heuristic: word overlap after stopword removal.
    Returns True if overlap > 0.3.
    """
    if not surfaced_content or not assistant_response:
        return False

    surfaced_words = {
        w.lower()
        for w in surfaced_content.split()
        if w.lower() not in STOPWORDS
    }
    if not surfaced_words:
        return False

    response_words = {
        w.lower()
        for w in assistant_response.split()
        if w.lower() not in STOPWORDS
    }
    overlap = len(surfaced_words & response_words)
    return overlap / len(surfaced_words) > 0.3
