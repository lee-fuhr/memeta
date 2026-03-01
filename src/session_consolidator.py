"""
Session consolidator - Extract memories from Claude Code sessions

Reads session JSONL files, extracts learnings using pattern detection,
scores importance, deduplicates, and saves to memory-ts.

Future enhancement: Use Anthropic API for LLM-powered extraction.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from .config import cfg
from .memory_ts_client import MemoryTSClient
from .importance_engine import calculate_importance, get_importance_score
from .extraction_patterns import is_garbage_content as _is_garbage_content
from .extraction_patterns import extract_memories_patterns as _extract_patterns
from .extraction_patterns import NORMALIZE_PATTERN
from .dedup import deduplicate as _deduplicate_memories
from .dedup import smart_dedup_decision as _smart_dedup_decision

# Imported at module level so monkeypatch can target it for tests
try:
    from .hook_state import get_session_state
except ImportError:
    def get_session_state(session_id):  # type: ignore[misc]
        return {"active_skills": []}


@dataclass
class SessionMemory:
    """Memory extracted from session"""
    content: str
    importance: float
    project_id: str
    tags: List[str] = field(default_factory=lambda: ["#learning"])
    session_id: Optional[str] = None
    id: Optional[str] = None  # Set after memory-ts create


@dataclass
class SessionQualityScore:
    """Quality metrics for a session"""
    total_memories: int
    high_value_count: int  # memories with importance >= 0.7
    quality_score: float  # 0.0-1.0 overall session quality


@dataclass
class ConsolidationResult:
    """Result of session consolidation"""
    memories_extracted: int
    memories_saved: int
    memories_deduplicated: int
    session_quality: SessionQualityScore
    saved_memories: List[SessionMemory] = field(default_factory=list)
    all_extracted: List[SessionMemory] = field(default_factory=list)
    extracted_memories: List[SessionMemory] = field(default_factory=list)  # Alias for compatibility
    contradictions_resolved: int = 0  # Number of contradictions auto-resolved


def _session_memory_factory(content: str, importance: float, project_id: str) -> SessionMemory:
    """Factory function for creating SessionMemory instances from extraction patterns."""
    return SessionMemory(content=content, importance=importance, project_id=project_id)


class SessionConsolidator:
    """
    Extract and consolidate memories from Claude Code sessions

    Processes session JSONL files, extracts learnings, scores importance,
    deduplicates against existing memories, and saves to memory-ts.
    """

    def __init__(
        self,
        session_dir: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
        project_id: str = "LFI"
    ):
        """
        Initialize consolidator

        Args:
            session_dir: Directory containing session JSONL files
            memory_dir: Directory for memory-ts storage
            project_id: Default project identifier
        """
        self.session_dir = Path(session_dir) if session_dir else cfg.session_dir
        self.memory_dir = memory_dir
        self.project_id = project_id
        self.memory_client = MemoryTSClient(memory_dir=memory_dir)

    def read_session(self, session_file: Path) -> List[Dict[str, Any]]:
        """
        Read session JSONL file

        Args:
            session_file: Path to session JSONL

        Returns:
            List of message dicts with 'role' and 'content'

        Raises:
            FileNotFoundError: If session file doesn't exist
        """
        if not session_file.exists():
            raise FileNotFoundError(f"Session file not found: {session_file}")

        messages = []
        with open(session_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        msg = json.loads(line)
                        messages.append(msg)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

        return messages

    def extract_conversation_text(self, messages: List[Dict[str, Any]]) -> str:
        """
        Extract plain text from session messages

        Handles both old format (role/content at top level)
        and new format (role/content nested in 'message' field).
        Filters out tool_use/tool_result content blocks.

        Args:
            messages: List of message dicts

        Returns:
            Combined conversation text
        """
        parts = []
        for msg in messages:
            # New format: role/content nested in 'message' field
            if 'message' in msg and isinstance(msg['message'], dict):
                role = msg['message'].get('role', '')
                content = msg['message'].get('content', '')
            # Old format: role/content at top level
            else:
                role = msg.get('role', '')
                content = msg.get('content', '')

            # Only include user and assistant messages
            if not content or role not in ('user', 'assistant'):
                continue

            # Content can be a string or a list of content blocks
            if isinstance(content, list):
                # Only keep text blocks, skip tool_use/tool_result
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '')
                        if text and not _is_garbage_content(text):
                            text_parts.append(text)
                    elif isinstance(block, str):
                        if not _is_garbage_content(block):
                            text_parts.append(block)
                if text_parts:
                    parts.append(f"{role}: {' '.join(text_parts)}")
            elif isinstance(content, str):
                if not _is_garbage_content(content):
                    parts.append(f"{role}: {content}")

        return "\n\n".join(parts)

    def extract_memories(
        self,
        conversation: str,
        use_llm: bool = False
    ) -> List[SessionMemory]:
        """
        Extract learnings from conversation

        Two extraction modes:
        1. Pattern-based (default): Fast, deterministic, no costs
        2. LLM-powered (use_llm=True): More nuanced, uses Claude intelligence

        Args:
            conversation: Full conversation text
            use_llm: If True, use LLM extraction instead of patterns

        Returns:
            List of extracted SessionMemory objects
        """
        # Skip if conversation is too short/trivial
        if len(conversation) < 50:
            return []

        # LLM extraction if requested
        if use_llm:
            return self._extract_memories_llm(conversation)

        # Otherwise use pattern-based extraction
        return _extract_patterns(conversation, self.project_id, _session_memory_factory)

    def _extract_memories_llm(self, conversation: str) -> List[SessionMemory]:
        """
        LLM-powered memory extraction (uses Claude intelligence)

        Analyzes conversation to identify:
        - User preferences and corrections
        - Technical learnings and insights
        - Process improvements and workflows
        - Client-specific patterns
        - Cross-project applicable lessons

        Args:
            conversation: Full conversation text

        Returns:
            List of extracted SessionMemory objects
        """
        try:
            # Future enhancement: Use Task tool for LLM-powered extraction
            # For now, pattern-based extraction works well
            return _extract_patterns(conversation, self.project_id, _session_memory_factory)
        except Exception:
            # Fall back to pattern extraction on any error
            return _extract_patterns(conversation, self.project_id, _session_memory_factory)

    def _smart_dedup_decision(
        self,
        new_content: str,
        existing_content: str,
        similarity: float
    ) -> str:
        """Delegate to dedup module. Kept for backward compatibility."""
        return _smart_dedup_decision(new_content, existing_content, similarity)

    def deduplicate(
        self,
        new_memories: List[SessionMemory],
        use_llm_dedup: bool = True
    ) -> List[SessionMemory]:
        """
        Remove memories that duplicate existing ones

        Enhanced with LLM-powered decisions for gray area (50-90% similarity).

        Args:
            new_memories: List of newly extracted memories
            use_llm_dedup: If True, use LLM for smarter dedup decisions

        Returns:
            Deduplicated list
        """
        existing_memories = self.memory_client.search(project_id=self.project_id)
        return _deduplicate_memories(new_memories, existing_memories, use_llm_dedup)

    def reinforce_corrections(
        self,
        new_corrections: List[SessionMemory],
        session_id: str,
    ) -> int:
        """
        Increment confirmations on existing correction memories when the same
        correction appears in a new session. Same-session dedup prevents gaming.

        Args:
            new_corrections: List of newly extracted correction memories
            session_id: Current session ID (for same-session dedup)

        Returns:
            Count of reinforced corrections
        """
        reinforced_count = 0

        # Search for existing correction memories
        existing_corrections = [
            m for m in self.memory_client.search(project_id=self.project_id)
            if m.context_type == "correction"
        ]

        if not existing_corrections:
            return 0

        for new_mem in new_corrections:
            for existing in existing_corrections:
                # Same-session dedup: skip if existing was created in this session
                if existing.source_session_id == session_id:
                    continue

                # Check similarity via word overlap (same approach as dedup.py)
                new_words = set(
                    NORMALIZE_PATTERN.sub('', new_mem.content.lower()).split()
                )
                existing_words = set(
                    NORMALIZE_PATTERN.sub('', existing.content.lower()).split()
                )
                if not new_words or not existing_words:
                    continue
                overlap = len(new_words & existing_words)
                total = len(new_words | existing_words)
                similarity = overlap / total if total else 0.0

                if similarity > 0.7:
                    # Reinforce: increment confirmations
                    self.memory_client.update(
                        existing.id,
                        confirmations=existing.confirmations + 1,
                    )
                    reinforced_count += 1
                    break  # Only reinforce one match per new correction

        return reinforced_count

    def consolidate_session(
        self,
        session_file: Path,
        use_llm: bool = True,
        skip_save: bool = False
    ) -> ConsolidationResult:
        """
        Complete consolidation pipeline for a session

        Reads session -> extracts memories (patterns + LLM) -> deduplicates -> saves

        Args:
            session_file: Path to session JSONL file
            use_llm: If True, also run LLM extraction via Claude CLI
            skip_save: If True, extract memories but don't save to memory-ts (for daily summaries)

        Returns:
            ConsolidationResult with stats
        """
        # Read session
        messages = self.read_session(session_file)
        conversation = self.extract_conversation_text(messages)

        # Extract memories (pattern-based)
        pattern_memories = self.extract_memories(conversation)

        # LLM extraction (if enabled)
        if use_llm and len(conversation) > 200:
            try:
                from .llm_extractor import extract_with_llm, combine_extractions
                llm_memories = extract_with_llm(conversation, project_id=self.project_id)
                extracted_memories = combine_extractions(pattern_memories, llm_memories)
            except Exception:
                # Fall back to pattern-only on any LLM failure
                extracted_memories = pattern_memories
        else:
            extracted_memories = pattern_memories

        # Resolve session ID and load active skills from hook state
        session_id = session_file.stem

        try:
            session_state = get_session_state(session_id)
            active_skills = session_state.get("active_skills", [])
        except Exception:
            active_skills = []

        # Reinforce existing corrections before dedup (cross-session confirmation)
        correction_memories = [
            m for m in extracted_memories if m.content.startswith("Correction: ")
        ]
        reinforced_count = 0
        if correction_memories:
            reinforced_count = self.reinforce_corrections(
                correction_memories, session_id=session_id
            )

        # Deduplicate against existing memories
        unique_memories = self.deduplicate(extracted_memories)

        # Save to memory-ts (unless skip_save=True)
        saved_count = 0
        saved_list = []
        replaced_count = 0

        if not skip_save:
            # Import contradiction detector
            from .contradiction_detector import check_contradictions

            for memory in unique_memories:
                memory.session_id = session_id

                # Determine if this is a correction memory
                is_correction = memory.content.startswith("Correction: ")

                # Build tags list: copy original + correction tag + skill tags
                tags = list(memory.tags)
                if is_correction and "#correction" not in tags:
                    tags.append("#correction")
                for skill in active_skills:
                    skill_tag = f"#skill:{skill}"
                    if skill_tag not in tags:
                        tags.append(skill_tag)
                memory.tags = tags

                # Check for contradictions with existing memories
                existing = self.memory_client.search(
                    content=memory.content,
                    project_id=self.project_id
                )

                # Convert Memory objects to dicts for contradiction checker
                existing_dicts = [
                    {'id': m.id, 'content': m.content}
                    for m in existing
                ]

                contradiction = check_contradictions(memory.content, existing_dicts)

                if contradiction.action == "replace":
                    # Archive old memory and save new one
                    old_mem = contradiction.contradicted_memory
                    try:
                        # Update old memory to archived scope
                        self.memory_client.update(
                            old_mem['id'],
                            scope="archived"
                        )
                        replaced_count += 1
                    except Exception:
                        pass  # Continue even if archive fails

                # Build extra kwargs for correction memories
                extra_kwargs = {}
                if is_correction:
                    extra_kwargs["context_type"] = "correction"
                    extra_kwargs["temporal_relevance"] = "permanent"

                # Save new memory (whether replacing or not)
                created_memory = self.memory_client.create(
                    content=memory.content,
                    project_id=memory.project_id,
                    tags=tags,
                    importance=memory.importance,
                    scope="project",  # New memories start as project-scope
                    session_id=session_id,  # Track provenance (legacy field)
                    source_session_id=session_id,  # Track provenance (new field)
                    **extra_kwargs,
                )
                memory.id = created_memory.id
                saved_list.append(memory)
                saved_count += 1

        # Calculate session quality
        quality = calculate_session_quality(extracted_memories)

        return ConsolidationResult(
            memories_extracted=len(extracted_memories),
            memories_saved=saved_count,
            memories_deduplicated=len(extracted_memories) - len(unique_memories),
            session_quality=quality,
            saved_memories=saved_list,
            all_extracted=extracted_memories,
            extracted_memories=extracted_memories,  # Populate alias for compatibility
            contradictions_resolved=replaced_count if not skip_save else 0,
        )


def extract_memories_from_session(session_file: Path, project_id: str = "LFI") -> List[SessionMemory]:
    """
    Convenience function for extracting memories from session

    Args:
        session_file: Path to session JSONL
        project_id: Project identifier

    Returns:
        List of extracted memories
    """
    consolidator = SessionConsolidator(project_id=project_id)
    messages = consolidator.read_session(session_file)
    conversation = consolidator.extract_conversation_text(messages)
    return consolidator.extract_memories(conversation)


def deduplicate_memories(
    new_memories: List[SessionMemory],
    memory_dir: Optional[Path] = None
) -> List[SessionMemory]:
    """
    Convenience function for deduplication

    Args:
        new_memories: List of new memories
        memory_dir: Memory storage directory

    Returns:
        Deduplicated list
    """
    consolidator = SessionConsolidator(memory_dir=memory_dir)
    return consolidator.deduplicate(new_memories)


def calculate_session_quality(memories: List[SessionMemory]) -> SessionQualityScore:
    """
    Calculate quality score for a session

    Quality = (high_value_count / total) * importance_average

    High value = importance >= 0.7

    Args:
        memories: List of extracted memories

    Returns:
        SessionQualityScore object
    """
    if len(memories) == 0:
        return SessionQualityScore(
            total_memories=0,
            high_value_count=0,
            quality_score=0.0
        )

    total = len(memories)
    high_value = sum(1 for m in memories if m.importance >= 0.7)
    avg_importance = sum(m.importance for m in memories) / total

    # Quality = (% high value) * average importance
    quality_score = (high_value / total) * avg_importance

    return SessionQualityScore(
        total_memories=total,
        high_value_count=high_value,
        quality_score=quality_score
    )


def load_daily_context(days: int = 2) -> str:
    """
    Load recent daily summaries for context injection into new sessions.

    Creates a DailyEpisodicSummary instance and returns the last N days
    of daily summaries concatenated with date headers.

    Args:
        days: Number of past days to load (default: 2).

    Returns:
        Concatenated summary content, or empty string if no files exist.
    """
    from .daily_episodic_summary import DailyEpisodicSummary

    return DailyEpisodicSummary().load_recent(days=days)
