"""Base importer interface for Memeta memory import."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from memory_system.memory_ts_client import Memory


@dataclass
class ImportResult:
    """Result of an import operation."""
    imported: int
    skipped: int
    errors: list[str] = field(default_factory=list)
    memories: list[Memory] = field(default_factory=list)


@dataclass
class ImportPreview:
    """Preview of what would be imported (dry-run)."""
    would_import: int
    would_skip: int
    sample_memories: list[Memory] = field(default_factory=list)


class BaseImporter(ABC):
    """Abstract base for memory importers."""

    def __init__(self, memory_dir: Optional[Path] = None, project_id: str = "LFI"):
        from memory_system.memory_ts_client import MemoryTSClient, DEFAULT_MEMORY_DIR
        self.memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        self.project_id = project_id
        self._client = MemoryTSClient(memory_dir=self.memory_dir)
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """Set progress callback(current, total)."""
        self._progress_callback = callback

    @abstractmethod
    def import_source(self, path: Path) -> ImportResult:
        """Import memories from the given source path."""
        ...

    @abstractmethod
    def dry_run(self, path: Path) -> ImportPreview:
        """Preview what would be imported without writing."""
        ...

    def _is_duplicate(self, content: str) -> bool:
        """Check if memory with this content already exists.

        Caches existing memory hashes on first call to avoid O(n*m) list() calls.
        """
        import hashlib
        content_hash = hashlib.sha256(content.strip().encode()).hexdigest()[:16]

        if not hasattr(self, "_existing_hashes"):
            existing = self._client.list()
            self._existing_hashes = {
                hashlib.sha256(mem.content.strip().encode()).hexdigest()[:16]
                for mem in existing
            }

        return content_hash in self._existing_hashes
