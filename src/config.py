"""
Centralized configuration for memory-system.

All hardcoded paths, project IDs, and tunable constants live here.
Override any value via environment variables:

    MEMORY_SYSTEM_MEMORY_DIR   — base memory directory
    MEMORY_SYSTEM_PROJECT_ID   — default project identifier
    MEMORY_SYSTEM_FSRS_DB      — path to FSRS scheduler database
    MEMORY_SYSTEM_INTEL_DB     — path to intelligence database
    MEMORY_SYSTEM_CLUSTER_DB   — path to cluster database
    MEMORY_SYSTEM_SESSION_DIR  — Claude session files directory

Usage:
    from memory_system.config import cfg

    db = cfg.fsrs_db_path
    project = cfg.project_id
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    """Read an env var or return the default."""
    return os.environ.get(key, default)


def _path(key: str, default: Path) -> Path:
    """Read an env var as a Path or return the default."""
    raw = os.environ.get(key)
    return Path(raw) if raw else default


@dataclass(frozen=True)
class MemorySystemConfig:
    """Frozen configuration — load once at import time."""

    # ── Base directories ──────────────────────────────────────────────────
    memory_dir: Path = field(
        default_factory=lambda: _path(
            "MEMORY_SYSTEM_MEMORY_DIR",
            Path.home() / ".local/share/memory",
        )
    )

    session_dir: Path = field(
        default_factory=lambda: _path(
            "MEMORY_SYSTEM_SESSION_DIR",
            Path.home() / ".claude/projects",
        )
    )

    # ── Project ───────────────────────────────────────────────────────────
    project_id: str = field(
        default_factory=lambda: _env("MEMORY_SYSTEM_PROJECT_ID", "default")
    )

    # ── Runtime databases (relative to project root by default) ───────────
    # These paths are resolved lazily so callers can still pass explicit
    # db_path arguments when they need isolation (e.g. tests).
    @property
    def project_memory_dir(self) -> Path:
        return self.memory_dir / self.project_id

    @property
    def session_db_path(self) -> Path:
        return _path(
            "MEMORY_SYSTEM_SESSION_DB",
            self.project_memory_dir / "session-history.db",
        )

    @property
    def shared_db_path(self) -> Path:
        return _path(
            "MEMORY_SYSTEM_SHARED_DB",
            self.project_memory_dir / "shared.db",
        )

    @property
    def fsrs_db_path(self) -> Path:
        return _path(
            "MEMORY_SYSTEM_FSRS_DB",
            # Falls back to a sibling of the package root when not set.
            # Callers that know their project root should pass db_path explicitly.
            Path.home() / ".local/share/memory" / "fsrs.db",
        )

    @property
    def intelligence_db_path(self) -> Path:
        return _path(
            "MEMORY_SYSTEM_INTEL_DB",
            Path.home() / ".local/share/memory" / "intelligence.db",
        )

    @property
    def cluster_db_path(self) -> Path:
        return _path(
            "MEMORY_SYSTEM_CLUSTER_DB",
            Path.home() / ".local/share/memory" / "clusters.db",
        )

    # ── Tunable constants ─────────────────────────────────────────────────
    max_pre_compaction_facts: int = field(
        default_factory=lambda: int(_env("MEMORY_SYSTEM_MAX_FACTS", "5"))
    )

    cache_ttl_seconds: int = field(
        default_factory=lambda: int(_env("MEMORY_SYSTEM_CACHE_TTL", "86400"))
    )


# Module-level singleton — import this everywhere.
cfg = MemorySystemConfig()
