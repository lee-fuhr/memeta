"""
Daily episodic summary — generates a YYYY-MM-DD.md summary file at end of day.

Queries session history for the day's sessions, aggregates content,
calls Claude API for a concise summary, writes to flat markdown files.

Next-session context loading: load_recent() returns the last N days of
summaries so the new session starts with yesterday's context.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import cfg
from .llm_extractor import ask_claude


# Default output directory for daily summaries
DEFAULT_SUMMARY_DIR = cfg.memory_dir / cfg.project_id / "daily-summaries"

# Maximum chars of session content to send to the LLM
MAX_CONTENT_CHARS = 6000

SUMMARY_PROMPT_TEMPLATE = """Summarize today's work sessions. Focus on:
- Key decisions made
- Topics discussed
- Open questions or next steps
- Anything unusual or notable

Be concise — max 200 words. Write in past tense. Start with the most important item.

Sessions:
{content}"""


class DailyEpisodicSummary:
    """Generate and load daily work summaries from session history."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        db_path: Optional[str] = None,
    ):
        """
        Initialize the daily summary generator.

        Args:
            output_dir: Where to write YYYY-MM-DD.md files.
                        Defaults to ~/.local/share/memory/{project}/daily-summaries/
            db_path: Path to session history SQLite database.
                     Defaults to config session_db_path.
        """
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_SUMMARY_DIR
        self.db_path = db_path or str(cfg.session_db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, target_date: Optional[date] = None) -> Path:
        """
        Generate a daily summary for the given date.

        Queries session history, aggregates content (capped at 6000 chars),
        calls Claude API, writes YYYY-MM-DD.md.

        Args:
            target_date: Date to summarise. Defaults to today.

        Returns:
            Path to the written summary file.
        """
        target_date = target_date or date.today()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        out_path = self.output_dir / f"{target_date.isoformat()}.md"

        # Gather session content for the day
        content = self._gather_sessions(target_date)

        if not content.strip():
            out_path.write_text(f"# {target_date.isoformat()}\n\nNo sessions today.\n")
            return out_path

        # Cap content length
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS]

        # Call LLM for summary
        prompt = SUMMARY_PROMPT_TEMPLATE.format(content=content)

        try:
            summary_text = ask_claude(prompt, timeout=30, max_retries=2)
            if not summary_text:
                raise RuntimeError("Empty response from LLM")
        except Exception as exc:
            summary_text = f"Summary unavailable: {exc}"

        out_path.write_text(
            f"# {target_date.isoformat()}\n\n{summary_text}\n"
        )
        return out_path

    def load_recent(self, days: int = 2) -> str:
        """
        Load the last N daily summaries and return their content.

        Args:
            days: Number of past days to load.

        Returns:
            Concatenated summary content with date headers.
            Empty string if no files exist.
        """
        if not self.output_dir.exists():
            return ""

        today = date.today()
        parts: list[str] = []

        for offset in range(days, 0, -1):
            target = today - timedelta(days=offset)
            path = self.output_dir / f"{target.isoformat()}.md"
            if path.exists():
                parts.append(path.read_text())

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gather_sessions(self, target_date: date) -> str:
        """
        Query session history DB for all sessions on target_date.

        Returns aggregated text of session names + transcript text,
        capped at MAX_CONTENT_CHARS.
        """
        start_ts = int(datetime.combine(target_date, datetime.min.time()).timestamp())
        end_ts = int(datetime.combine(target_date, datetime.max.time()).timestamp())

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, name, full_transcript_json, message_count
                FROM sessions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (start_ts, end_ts),
            )
            rows = cursor.fetchall()
            conn.close()
        except Exception:
            return ""

        if not rows:
            return ""

        parts: list[str] = []
        total_len = 0

        for row in rows:
            name = row["name"] or row["id"]
            header = f"## Session: {name}\n"

            # Extract plain text from transcript JSON
            try:
                transcript = json.loads(row["full_transcript_json"])
            except (json.JSONDecodeError, TypeError):
                transcript = []

            text_bits: list[str] = []
            for msg in transcript:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                    text_bits.append(f"{role}: {content}")

            session_text = header + "\n".join(text_bits)

            # Enforce cap
            if total_len + len(session_text) > MAX_CONTENT_CHARS:
                remaining = MAX_CONTENT_CHARS - total_len
                if remaining > 0:
                    parts.append(session_text[:remaining])
                break

            parts.append(session_text)
            total_len += len(session_text)

        return "\n\n".join(parts)


def load_daily_context() -> str:
    """
    Convenience function: load recent daily summaries for context injection.

    Returns:
        Last 2 days of daily summaries, or empty string.
    """
    return DailyEpisodicSummary().load_recent(days=2)


if __name__ == "__main__":
    summary = DailyEpisodicSummary()
    path = summary.generate()
    print(f"Daily summary written to {path}")
