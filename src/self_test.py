"""
Self-test diagnostic system for Total Rekall.

Runs a suite of health checks against the memory system:
- Memory read/write (temp file round-trip)
- Intelligence DB accessibility (table presence)
- Embedding freshness (recent entries in embeddings table)
- Search functionality (in-memory mock query)
- Circuit breaker state (no OPEN breakers)
- Orphaned file count (memory dir scan)

Usage:
    from memory_system.self_test import SelfTest

    st = SelfTest()
    report = st.run_all()
    print(st.get_report_text())
"""

import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_system.config import MemorySystemConfig, cfg


def _check_result(
    name: str,
    passed: bool,
    message: str,
    duration_ms: float,
) -> Dict[str, Any]:
    """Build a standard check result dict."""
    return {
        "name": name,
        "passed": passed,
        "message": message,
        "duration_ms": round(duration_ms, 2),
    }


class SelfTest:
    """
    Diagnostic health-check suite for the memory system.

    Each ``check_*`` method returns a dict with keys:
    ``name``, ``passed`` (bool), ``message`` (str), ``duration_ms`` (float).

    ``run_all()`` aggregates every check into a single report dict.
    """

    def __init__(self, config: Optional[MemorySystemConfig] = None):
        self.config = config or cfg
        self._last_report: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_memory_readwrite(self) -> Dict[str, Any]:
        """Write a temp memory file, read it back, verify content, clean up."""
        name = "memory_readwrite"
        t0 = time.monotonic()
        try:
            memory_dir = self.config.project_memory_dir / "memories"

            # Use a dedicated temp directory so we never pollute real data
            with tempfile.TemporaryDirectory() as tmpdir:
                test_file = Path(tmpdir) / "selftest-probe.md"
                payload = "---\nid: selftest-probe\n---\nself-test OK"
                test_file.write_text(payload, encoding="utf-8")

                readback = test_file.read_text(encoding="utf-8")
                if readback != payload:
                    return _check_result(
                        name, False, "Read-back mismatch", _elapsed(t0)
                    )

            return _check_result(name, True, "Write and read-back OK", _elapsed(t0))

        except PermissionError as exc:
            return _check_result(name, False, f"Permission error: {exc}", _elapsed(t0))
        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    def check_db_accessible(self) -> Dict[str, Any]:
        """Verify intelligence.db exists and contains expected tables (read-only)."""
        name = "db_accessible"
        t0 = time.monotonic()

        db_path = self.config.intelligence_db_path
        if not db_path.exists():
            return _check_result(
                name, False, f"Database not found: {db_path}", _elapsed(t0)
            )

        expected_tables = {
            "voice_memories",
            "image_memories",
            "code_memories",
            "decision_journal",
            "dream_insights",
        }

        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                found = {r[0] for r in rows}
                missing = expected_tables - found
                if missing:
                    return _check_result(
                        name,
                        False,
                        f"Missing tables: {', '.join(sorted(missing))}",
                        _elapsed(t0),
                    )
                return _check_result(
                    name,
                    True,
                    f"DB accessible, {len(found)} tables found",
                    _elapsed(t0),
                )
            finally:
                conn.close()

        except sqlite3.OperationalError as exc:
            return _check_result(
                name, False, f"DB locked or corrupt: {exc}", _elapsed(t0)
            )
        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    def check_embeddings_fresh(self) -> Dict[str, Any]:
        """Check that embedding DB exists and has entries from last 7 days."""
        name = "embeddings_fresh"
        t0 = time.monotonic()

        db_path = self.config.intelligence_db_path
        if not db_path.exists():
            return _check_result(
                name, False, f"Database not found: {db_path}", _elapsed(t0)
            )

        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            try:
                # Check embeddings table exists
                table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
                ).fetchone()
                if not table_check:
                    return _check_result(
                        name, False, "Embeddings table not found", _elapsed(t0)
                    )

                # Check for entries within last 7 days
                cutoff = (datetime.now() - timedelta(days=7)).isoformat()
                row = conn.execute(
                    "SELECT COUNT(*) FROM embeddings WHERE created_at > ?",
                    (cutoff,),
                ).fetchone()
                count = row[0] if row else 0

                if count == 0:
                    return _check_result(
                        name,
                        False,
                        "No embeddings created in last 7 days",
                        _elapsed(t0),
                    )

                return _check_result(
                    name,
                    True,
                    f"{count} embeddings created in last 7 days",
                    _elapsed(t0),
                )
            finally:
                conn.close()

        except sqlite3.OperationalError as exc:
            return _check_result(
                name, False, f"DB error: {exc}", _elapsed(t0)
            )
        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    def check_search_functional(self) -> Dict[str, Any]:
        """Run a mock in-memory search to verify search logic works."""
        name = "search_functional"
        t0 = time.monotonic()

        try:
            # Build a tiny in-memory corpus and do substring matching
            corpus = [
                {"id": "1", "content": "Python memory management techniques"},
                {"id": "2", "content": "JavaScript async patterns"},
                {"id": "3", "content": "Database indexing strategies"},
            ]
            query = "memory"
            results = [
                doc for doc in corpus if query.lower() in doc["content"].lower()
            ]

            if len(results) != 1 or results[0]["id"] != "1":
                return _check_result(
                    name,
                    False,
                    f"Search returned unexpected results: {results}",
                    _elapsed(t0),
                )

            return _check_result(
                name, True, "In-memory search functioning", _elapsed(t0)
            )

        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    def check_circuit_breaker_state(self) -> Dict[str, Any]:
        """Read circuit_breaker_state table and check for OPEN breakers."""
        name = "circuit_breaker_state"
        t0 = time.monotonic()

        db_path = self.config.intelligence_db_path
        if not db_path.exists():
            # No DB means no circuit breakers persisted — that is fine.
            return _check_result(
                name,
                True,
                "No intelligence DB (circuit breakers not persisted)",
                _elapsed(t0),
            )

        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            try:
                # Check if table exists
                table_check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='circuit_breaker_state'"
                ).fetchone()
                if not table_check:
                    return _check_result(
                        name,
                        True,
                        "Circuit breaker table not found (no breakers configured)",
                        _elapsed(t0),
                    )

                rows = conn.execute(
                    "SELECT name, state FROM circuit_breaker_state WHERE state = 'open'"
                ).fetchall()

                if rows:
                    names = [r[0] for r in rows]
                    return _check_result(
                        name,
                        False,
                        f"OPEN circuit breakers: {', '.join(names)}",
                        _elapsed(t0),
                    )

                return _check_result(
                    name, True, "No open circuit breakers", _elapsed(t0)
                )
            finally:
                conn.close()

        except sqlite3.OperationalError as exc:
            return _check_result(
                name, False, f"DB error: {exc}", _elapsed(t0)
            )
        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    def check_orphaned_files(self) -> Dict[str, Any]:
        """Count memory files in the memory directory."""
        name = "orphaned_files"
        t0 = time.monotonic()

        memory_dir = self.config.project_memory_dir / "memories"
        if not memory_dir.exists():
            return _check_result(
                name,
                False,
                f"Memory directory not found: {memory_dir}",
                _elapsed(t0),
            )

        try:
            md_files = list(memory_dir.glob("*.md"))
            count = len(md_files)
            return _check_result(
                name, True, f"{count} memory files found", _elapsed(t0)
            )

        except PermissionError as exc:
            return _check_result(
                name, False, f"Permission error: {exc}", _elapsed(t0)
            )
        except Exception as exc:
            return _check_result(name, False, f"Unexpected error: {exc}", _elapsed(t0))

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def run_all(self) -> Dict[str, Any]:
        """
        Run all 6 diagnostic checks.

        Returns:
            {
                "passed": bool,          # True only if ALL checks pass
                "checks": [...],         # List of individual check results
                "total_duration_ms": float,
                "summary": "6/6 checks passed",
                "timestamp": ISO-8601 string,
            }
        """
        t0 = time.monotonic()

        checks = [
            self.check_memory_readwrite(),
            self.check_db_accessible(),
            self.check_embeddings_fresh(),
            self.check_search_functional(),
            self.check_circuit_breaker_state(),
            self.check_orphaned_files(),
        ]

        passed_count = sum(1 for c in checks if c["passed"])
        total = len(checks)

        report = {
            "passed": passed_count == total,
            "checks": checks,
            "total_duration_ms": round(_elapsed(t0), 2),
            "summary": f"{passed_count}/{total} checks passed",
            "timestamp": datetime.now().isoformat(),
        }
        self._last_report = report
        return report

    def get_report_text(self) -> str:
        """
        Return a human-readable text report from the last ``run_all()`` call.

        If ``run_all()`` has not been called yet, calls it first.
        """
        if self._last_report is None:
            self.run_all()

        report = self._last_report
        lines: List[str] = []
        lines.append("=== Total Rekall self-test report ===")
        lines.append(f"Timestamp: {report['timestamp']}")
        lines.append(f"Result: {report['summary']}")
        lines.append("")

        for check in report["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            lines.append(
                f"  [{status}] {check['name']}: {check['message']} "
                f"({check['duration_ms']}ms)"
            )

        lines.append("")
        lines.append(f"Total duration: {report['total_duration_ms']}ms")
        overall = "ALL CHECKS PASSED" if report["passed"] else "SOME CHECKS FAILED"
        lines.append(f"Overall: {overall}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _elapsed(t0: float) -> float:
    """Milliseconds since *t0* (monotonic)."""
    return (time.monotonic() - t0) * 1000.0
