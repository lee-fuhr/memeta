"""
Memory-ts client - Direct file operations for memory-ts integration

Memory-ts uses markdown files with YAML frontmatter stored at:
/Users/lee/.local/share/memory/LFI/memories/

Each memory is a file: {id}.md with YAML frontmatter + markdown content
"""

import ast
import json
import re
import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import time


# Default memory directory
DEFAULT_MEMORY_DIR = Path.home() / ".local/share/memory/LFI/memories"


class MemoryTSError(Exception):
    """Base exception for memory-ts client errors"""
    pass


class MemoryNotFoundError(MemoryTSError):
    """Raised when memory doesn't exist"""
    pass


@dataclass
class Memory:
    """Memory data model matching memory-ts schema v2"""
    id: str
    content: str
    importance: float
    tags: List[str]
    project_id: str
    scope: str = "project"  # project or global
    session_id: Optional[str] = None  # Track which session created this memory
    source_session_id: Optional[str] = None  # Provenance: the session that produced this memory
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())
    reasoning: str = ""
    confidence_score: float = 0.9
    context_type: str = "knowledge"
    temporal_relevance: str = "persistent"
    knowledge_domain: str = "learnings"
    status: str = "active"
    confirmations: int = 0
    contradictions: int = 0
    retrieval_weight: Optional[float] = None
    schema_version: int = 2

    def __post_init__(self):
        """Set retrieval_weight to match importance if not specified"""
        if self.retrieval_weight is None:
            self.retrieval_weight = self.importance


class MemoryTSClient:
    """
    Client for memory-ts file-based storage

    Memory-ts stores memories as markdown files with YAML frontmatter.
    This client provides CRUD operations on those files.
    """

    def __init__(self, memory_dir: Optional[Path] = None):
        """
        Initialize client

        Args:
            memory_dir: Path to memory storage (defaults to ~/.local/share/memory/LFI/memories)
        """
        self.memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Initialize temporal predictor for access logging
        self._predictor = None
        self._enable_access_logging = os.getenv('ENABLE_TEMPORAL_LOGGING', '1') == '1'

    def _get_predictor(self):
        """Lazy-load predictor to avoid circular imports"""
        if self._predictor is None and self._enable_access_logging:
            try:
                from wild.temporal_predictor import TemporalPatternPredictor
                self._predictor = TemporalPatternPredictor()
            except Exception:
                # Fail silently - logging is optional
                self._enable_access_logging = False
        return self._predictor

    def _log_access(self, memory_id: str, access_type: str, context_keywords: Optional[List[str]] = None):
        """Log memory access for temporal pattern learning"""
        if not self._enable_access_logging:
            return

        predictor = self._get_predictor()
        if predictor:
            try:
                session_id = os.getenv('CLAUDE_SESSION_ID')
                predictor.log_memory_access(
                    memory_id=memory_id,
                    access_type=access_type,
                    context_keywords=context_keywords,
                    session_id=session_id
                )
            except Exception:
                # Fail silently - logging is optional
                pass

    def _safe_memory_path(self, memory_id: str) -> Path:
        """Build memory file path with path traversal protection"""
        # Strip path separators and traversal sequences
        safe_id = re.sub(r'[/\\]', '', memory_id).replace('..', '')
        if not safe_id:
            raise ValueError(f"Invalid memory_id: {memory_id}")
        path = (self.memory_dir / f"{safe_id}.md").resolve()
        # Ensure resolved path is still under memory_dir
        if not str(path).startswith(str(self.memory_dir.resolve())):
            raise ValueError(f"Path traversal detected in memory_id: {memory_id}")
        return path

    def create(
        self,
        content: str,
        project_id: str,
        tags: List[str],
        importance: Optional[float] = None,
        scope: str = "project",
        source_session_id: Optional[str] = None,
        **kwargs
    ) -> Memory:
        """
        Create new memory

        Args:
            content: Memory content (markdown)
            project_id: Project identifier
            tags: List of tags (e.g. ["#learning", "#important"])
            importance: Importance score (0.0-1.0), auto-calculated if None
            scope: "project" or "global"
            source_session_id: Session ID that produced this memory (provenance tracking)
            **kwargs: Additional memory fields

        Returns:
            Created Memory object
        """
        # Generate unique ID (timestamp-hash format)
        timestamp = str(int(time.time() * 1000))  # milliseconds
        hash_input = f"{content}{project_id}{datetime.now().isoformat()}"
        hash_val = hashlib.md5(hash_input.encode()).hexdigest()[:6]
        memory_id = f"{timestamp}-{hash_val}"

        # Calculate importance if not provided
        if importance is None:
            from .importance_engine import calculate_importance
            importance = calculate_importance(content)

        # Create memory object
        memory = Memory(
            id=memory_id,
            content=content,
            project_id=project_id,
            tags=tags,
            importance=importance,
            scope=scope,
            source_session_id=source_session_id,
            **kwargs
        )

        # Write to file
        self._write_memory(memory)

        return memory

    def _archived_memory_path(self, memory_id: str) -> Path:
        """Build archived memory file path with path traversal protection"""
        safe_id = re.sub(r'[/\\]', '', memory_id).replace('..', '')
        if not safe_id:
            raise ValueError(f"Invalid memory_id: {memory_id}")
        path = (self.memory_dir / "archived" / f"{safe_id}.md").resolve()
        if not str(path).startswith(str(self.memory_dir.resolve())):
            raise ValueError(f"Path traversal detected in memory_id: {memory_id}")
        return path

    def get(self, memory_id: str) -> Memory:
        """
        Get memory by ID

        Checks both active and archived locations.

        Args:
            memory_id: Memory identifier

        Returns:
            Memory object

        Raises:
            MemoryNotFoundError: If memory doesn't exist
        """
        memory_file = self._safe_memory_path(memory_id)
        if not memory_file.exists():
            # Check archived location
            archived_file = self._archived_memory_path(memory_id)
            if archived_file.exists():
                memory_file = archived_file
            else:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")

        memory = self._read_memory(memory_file)

        # Log access for temporal pattern learning
        self._log_access(memory_id, 'direct')

        return memory

    def list(self, include_archived: bool = False) -> List[Memory]:
        """
        List all memories

        Args:
            include_archived: If True, include memories in archived/ subdirectory

        Returns:
            List of Memory objects
        """
        results = []

        # Active memories (top-level .md files)
        for memory_file in self.memory_dir.glob("*.md"):
            try:
                memory = self._read_memory(memory_file)
                results.append(memory)
            except Exception:
                continue

        # Archived memories
        if include_archived:
            archived_dir = self.memory_dir / "archived"
            if archived_dir.exists():
                for memory_file in archived_dir.glob("*.md"):
                    # Skip manifest files
                    if memory_file.name.endswith("-archive.md"):
                        continue
                    try:
                        memory = self._read_memory(memory_file)
                        results.append(memory)
                    except Exception:
                        continue

        return results

    def archive(self, memory_id: str, reason: str = "low_importance") -> bool:
        """
        Archive a memory by moving it to the archived/ subdirectory

        Moves the file from {memory_dir}/{id}.md to {memory_dir}/archived/{id}.md
        and updates the YAML frontmatter with archived: true.

        Args:
            memory_id: Memory to archive
            reason: Reason for archival (e.g. "low_importance", "predicted_stale")

        Returns:
            True if archived, False if already archived or not found
        """
        source_file = self._safe_memory_path(memory_id)
        dest_file = self._archived_memory_path(memory_id)

        # Already archived
        if not source_file.exists():
            if dest_file.exists():
                return False  # Already archived, idempotent
            return False  # Not found at all

        # Create archived/ directory lazily
        archived_dir = self.memory_dir / "archived"
        archived_dir.mkdir(exist_ok=True)

        # Read, update status, write to new location
        memory = self._read_memory(source_file)
        memory.status = "archived"

        # Add #archived tag if not present
        if "#archived" not in memory.tags:
            memory.tags.append("#archived")

        memory.updated = datetime.now().isoformat()

        # Write to archived location using _write_memory's atomic pattern
        # but targeting the archived directory
        self._write_memory_to(memory, dest_file)

        # Remove original file
        source_file.unlink()

        return True

    def _write_memory_to(self, memory: Memory, target_path: Path) -> None:
        """Write memory to a specific path (used for archival)"""
        import tempfile

        # Build YAML frontmatter (same as _write_memory)
        source_session_line = ""
        if memory.source_session_id is not None:
            source_session_line = f"\nsource_session_id: {memory.source_session_id}"

        frontmatter = f"""---
id: {memory.id}
created: {memory.created}
updated: {memory.updated}
reasoning: {memory.reasoning}
importance_weight: {memory.importance}
confidence_score: {memory.confidence_score}
confirmations: {memory.confirmations}
contradictions: {memory.contradictions}
context_type: {memory.context_type}
temporal_relevance: {memory.temporal_relevance}
knowledge_domain: {memory.knowledge_domain}
emotional_resonance: null
action_required: false
problem_solution_pair: true
semantic_tags: {memory.tags}
trigger_phrases: []
question_types: []
session_id: {memory.session_id or "unknown"}
project_id: {memory.project_id}
status: {memory.status}
scope: {memory.scope}
temporal_class: long_term
fade_rate: 0.03
expires_after_sessions: 0
domain: learnings
feature: null
component: null
supersedes: null
superseded_by: null
related_to: []
resolves: []
resolved_by: null
parent_id: null
child_ids: []
awaiting_implementation: false
awaiting_decision: false
blocked_by: null
blocks: []
related_files: []
retrieval_weight: {memory.retrieval_weight or memory.importance}{source_session_line}
exclude_from_retrieval: false
archived: true
schema_version: {memory.schema_version}
---

{memory.content}
"""
        # Atomic write
        temp_fd, temp_path = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp"
        )

        try:
            os.write(temp_fd, frontmatter.encode('utf-8'))
            os.close(temp_fd)
            os.replace(temp_path, target_path)
        except Exception:
            try:
                os.close(temp_fd)
            except Exception:
                pass
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def search(
        self,
        tags: Optional[List[str]] = None,
        content: Optional[str] = None,
        scope: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> List[Memory]:
        """
        Search memories by various criteria

        Args:
            tags: Filter by tags (any match)
            content: Filter by content substring
            scope: Filter by scope (project/global)
            project_id: Filter by project

        Returns:
            List of matching Memory objects
        """
        results = []

        for memory_file in self.memory_dir.glob("*.md"):
            try:
                memory = self._read_memory(memory_file)

                # Apply filters
                if tags and not any(tag in memory.tags for tag in tags):
                    continue
                if content and content.lower() not in memory.content.lower():
                    continue
                if scope and memory.scope != scope:
                    continue
                if project_id and memory.project_id != project_id:
                    continue

                results.append(memory)
            except Exception:
                # Skip files that can't be parsed
                continue

        # Log all accessed memories for temporal pattern learning
        context_keywords = []
        if content:
            context_keywords = content.split()

        for memory in results:
            self._log_access(memory.id, 'search', context_keywords)

        return results

    def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        importance: Optional[float] = None,
        tags: Optional[List[str]] = None,
        scope: Optional[str] = None,
        **kwargs
    ) -> Memory:
        """
        Update existing memory

        Args:
            memory_id: Memory to update
            content: New content (optional)
            importance: New importance (optional)
            tags: New tags (optional)
            scope: New scope (optional)
            **kwargs: Additional fields to update

        Returns:
            Updated Memory object

        Raises:
            MemoryNotFoundError: If memory doesn't exist
        """
        memory = self.get(memory_id)

        # Update fields
        if content is not None:
            memory.content = content
        if importance is not None:
            memory.importance = importance
        if tags is not None:
            memory.tags = tags
        if scope is not None:
            memory.scope = scope

        # Update additional fields from kwargs
        for key, value in kwargs.items():
            if hasattr(memory, key):
                setattr(memory, key, value)

        # Update timestamp
        memory.updated = datetime.now().isoformat()

        # Write updated memory
        self._write_memory(memory)

        return memory

    def _write_memory(self, memory: Memory) -> None:
        """Write memory to disk as markdown with YAML frontmatter"""
        memory_file = self._safe_memory_path(memory.id)

        # Build YAML frontmatter
        # Conditionally include source_session_id (omit if None)
        source_session_line = ""
        if memory.source_session_id is not None:
            source_session_line = f"\nsource_session_id: {memory.source_session_id}"

        frontmatter = f"""---
id: {memory.id}
created: {memory.created}
updated: {memory.updated}
reasoning: {memory.reasoning}
importance_weight: {memory.importance}
confidence_score: {memory.confidence_score}
confirmations: {memory.confirmations}
contradictions: {memory.contradictions}
context_type: {memory.context_type}
temporal_relevance: {memory.temporal_relevance}
knowledge_domain: {memory.knowledge_domain}
emotional_resonance: null
action_required: false
problem_solution_pair: true
semantic_tags: {memory.tags}
trigger_phrases: []
question_types: []
session_id: {memory.session_id or "unknown"}
project_id: {memory.project_id}
status: {memory.status}
scope: {memory.scope}
temporal_class: long_term
fade_rate: 0.03
expires_after_sessions: 0
domain: learnings
feature: null
component: null
supersedes: null
superseded_by: null
related_to: []
resolves: []
resolved_by: null
parent_id: null
child_ids: []
awaiting_implementation: false
awaiting_decision: false
blocked_by: null
blocks: []
related_files: []
retrieval_weight: {memory.retrieval_weight or memory.importance}{source_session_line}
exclude_from_retrieval: false
schema_version: {memory.schema_version}
---

{memory.content}
"""

        # RELIABILITY FIX: Atomic write using temp file + rename pattern
        # Prevents corruption from concurrent writes or interrupted writes
        import tempfile
        import os

        # Write to temp file first
        temp_fd, temp_path = tempfile.mkstemp(
            dir=memory_file.parent,
            prefix=f".{memory_file.name}.",
            suffix=".tmp"
        )

        try:
            # Write content to temp file
            os.write(temp_fd, frontmatter.encode('utf-8'))
            os.close(temp_fd)

            # Atomic rename (POSIX guarantees atomicity)
            os.replace(temp_path, memory_file)

        except Exception:
            # Clean up temp file on error
            try:
                os.close(temp_fd)
            except Exception:
                pass
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _read_memory(self, memory_file: Path) -> Memory:
        """Read memory from markdown file with YAML frontmatter"""
        content = memory_file.read_text()

        # Split frontmatter and content
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise MemoryTSError(f"Invalid memory file format: {memory_file}")

        frontmatter_text = parts[1]
        memory_content = parts[2].strip()

        # Parse YAML frontmatter (simple key: value parsing)
        metadata = {}
        for line in frontmatter_text.split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Parse specific types
            if key == "semantic_tags":
                # Parse list format: ["tag1", "tag2"]
                value = ast.literal_eval(value) if value.startswith("[") else []
            elif key in ("importance_weight", "confidence_score", "retrieval_weight"):
                value = float(value) if value != "null" else 0.0
            elif key in ("confirmations", "contradictions"):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 0
            elif key == "schema_version":
                value = int(value) if value.isdigit() else 2

            metadata[key] = value

        # Parse source_session_id (None if absent — backward-compatible)
        raw_source_session = metadata.get("source_session_id")
        if raw_source_session in (None, "null", ""):
            source_session_id = None
        else:
            source_session_id = str(raw_source_session)

        # Build Memory object
        return Memory(
            id=metadata.get("id", memory_file.stem),
            content=memory_content,
            importance=metadata.get("importance_weight", 0.5),
            tags=metadata.get("semantic_tags", []),
            project_id=metadata.get("project_id", "LFI"),
            scope=metadata.get("scope", "project"),
            source_session_id=source_session_id,
            created=metadata.get("created", ""),
            updated=metadata.get("updated", ""),
            reasoning=metadata.get("reasoning", ""),
            confidence_score=metadata.get("confidence_score", 0.9),
            context_type=metadata.get("context_type", "knowledge"),
            temporal_relevance=metadata.get("temporal_relevance", "persistent"),
            knowledge_domain=metadata.get("knowledge_domain", "learnings"),
            status=metadata.get("status", "active"),
            confirmations=metadata.get("confirmations", 0),
            contradictions=metadata.get("contradictions", 0),
            retrieval_weight=metadata.get("retrieval_weight"),
            schema_version=metadata.get("schema_version", 2)
        )
