"""
Session consolidator - Extract memories from Claude Code sessions

Reads session JSONL files, extracts learnings using pattern detection,
scores importance, deduplicates, and saves to memory-ts.

Future enhancement: Use Anthropic API for LLM-powered extraction.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from .config import cfg
from .memory_ts_client import MemoryTSClient
from .importance_engine import calculate_importance, get_importance_score

# Pre-compiled regex patterns for memory extraction
_LEARNING_PATTERNS = [
    re.compile(r"(?:learned|discovered|realized|found out|noticed) that ([^.!?]+[.!?])", re.IGNORECASE),
    re.compile(r"(?:key insight|important to note|worth remembering):? ([^.!?]+[.!?])", re.IGNORECASE),
    re.compile(r"(?:pattern|trend) (?:I noticed|observed|saw):? ([^.!?]+[.!?])", re.IGNORECASE),
]
_CORRECTION_PATTERNS = [
    re.compile(r"user:.*?(?:actually|correction|no,|wrong|mistake|should be|meant to say) ([^.!?]+[.!?])", re.IGNORECASE | re.DOTALL),
    re.compile(r"user:.*?(?:better way|instead try|prefer) ([^.!?]+[.!?])", re.IGNORECASE | re.DOTALL),
]
_PROBLEM_SOLUTION_PATTERN = re.compile(
    r"(?:problem|issue|challenge):.*?([^.!?]+[.!?]).*?(?:solution|fix|approach):.*?([^.!?]+[.!?])",
    re.IGNORECASE | re.DOTALL,
)
_ASSISTANT_INSIGHT_PATTERN = re.compile(r"assistant:.*?([A-Z][^.!?]{30,}[.!?])", re.DOTALL)
_NORMALIZE_PATTERN = re.compile(r'[^\w\s]')

# Garbage detection patterns
_TOOL_CALL_MARKERS = ('toolu_', 'tool_use', 'tool_result', "'input': {", '"input": {', "'name': '")
_LINE_NUMBER_PATTERN = re.compile(r'\d+[→\t].*\d+[→\t].*\d+[→\t]')
_JSON_CHARS = set('{}[]\'"')


def _is_garbage_content(text: str) -> bool:
    """Check if extracted content is garbage (tool calls, JSON, line numbers)."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 30:
        return True
    # Tool call artifacts
    for marker in _TOOL_CALL_MARKERS:
        if marker in stripped:
            return True
    # Line number dumps (3+ consecutive)
    if _LINE_NUMBER_PATTERN.search(stripped):
        return True
    # High ratio of JSON-like characters (>20%)
    json_count = sum(1 for c in stripped if c in _JSON_CHARS)
    if json_count / len(stripped) > 0.20:
        return True
    return False


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
        memories = []

        # Skip if conversation is too short/trivial
        if len(conversation) < 50:
            return memories

        # LLM extraction if requested
        if use_llm:
            return self._extract_memories_llm(conversation)

        # Otherwise use pattern-based extraction
        return self._extract_memories_patterns(conversation)

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
        # Prepare extraction prompt
        prompt = f"""Analyze this Claude Code session and extract learnings worth remembering.

CONVERSATION:
{conversation[:10000]}  # Limit to first 10k chars to avoid token limits

EXTRACT:
- User preferences ("I prefer X", "Don't do Y")
- Corrections (user corrected me about something)
- Technical insights (patterns, solutions, approaches)
- Process learnings (workflows that worked/failed)
- Client-specific patterns (if mentioned)

FORMAT each learning as JSON:
{{
  "content": "The actual learning in 1-2 sentences",
  "importance": 0.5-0.95 (0.5=minor, 0.7=useful, 0.9=critical),
  "reason": "Why this is worth remembering"
}}

Return ONLY a JSON array of learnings, nothing else.
If no significant learnings, return empty array []."""

        try:
            # Here we would call Claude (myself) to analyze
            # Since we're running IN Claude Code, we can use the Task tool
            # But for now, fall back to pattern extraction
            # TODO: Implement via Task tool invocation
            return self._extract_memories_patterns(conversation)
        except Exception:
            # Fall back to pattern extraction on any error
            return self._extract_memories_patterns(conversation)

    def _extract_memories_patterns(self, conversation: str) -> List[SessionMemory]:
        """
        Pattern-based memory extraction (fast, deterministic)

        Uses regex patterns to identify learning moments:
        - Corrections (user corrects assistant)
        - Explicit learnings ("I learned that...", "discovered that...")
        - Patterns across multiple exchanges
        - Problem-solution pairs

        Args:
            conversation: Full conversation text

        Returns:
            List of extracted SessionMemory objects
        """
        memories = []

        # Pattern 1: Explicit learning statements (pre-compiled)
        for pattern in _LEARNING_PATTERNS:
            matches = pattern.finditer(conversation)
            for match in matches:
                learning_content = match.group(1).strip()
                if len(learning_content) > 50 and len(learning_content) < 2000 and not _is_garbage_content(learning_content):
                    importance = calculate_importance(learning_content)
                    if importance >= 0.5:  # Threshold for saving
                        memories.append(SessionMemory(
                            content=learning_content,
                            importance=importance,
                            project_id=self.project_id
                        ))

        # Pattern 2: User corrections (important signals, pre-compiled)
        for pattern in _CORRECTION_PATTERNS:
            matches = pattern.finditer(conversation)
            for match in matches:
                correction_content = match.group(1).strip()
                if len(correction_content) > 50 and len(correction_content) < 2000 and not _is_garbage_content(correction_content):
                    # Corrections get boosted importance
                    base_importance = calculate_importance(correction_content)
                    boosted_importance = min(0.95, base_importance * 1.2)
                    memories.append(SessionMemory(
                        content=f"Correction: {correction_content}",
                        importance=boosted_importance,
                        project_id=self.project_id
                    ))

        # Pattern 3: Problem-solution pairs (pre-compiled)
        matches = _PROBLEM_SOLUTION_PATTERN.finditer(conversation)
        for match in matches:
            problem = match.group(1).strip()
            solution = match.group(2).strip()
            if len(problem) > 20 and len(solution) > 20 and not _is_garbage_content(problem) and not _is_garbage_content(solution):
                content = f"Problem: {problem} Solution: {solution}"
                importance = calculate_importance(content)
                if importance >= 0.6:
                    memories.append(SessionMemory(
                        content=content,
                        importance=importance,
                        project_id=self.project_id
                    ))

        # Pattern 4: Assistant insights in response to questions (pre-compiled)
        assistant_insights = _ASSISTANT_INSIGHT_PATTERN.finditer(conversation)

        insight_count = 0
        for match in assistant_insights:
            if insight_count >= 3:  # Limit to top insights per session
                break

            insight = match.group(1).strip()

            # Filter out trivial responses and garbage
            if _is_garbage_content(insight):
                continue
            if len(insight) > 2000:
                continue
            if any(phrase in insight.lower() for phrase in [
                "let me", "i'll", "here's", "sure", "okay", "got it"
            ]):
                continue

            # Check for learning indicators (expanded list)
            if any(indicator in insight.lower() for indicator in [
                "better to", "key is", "important", "pattern", "approach",
                "when you", "if you", "works well", "effective", "i've found",
                "rather than", "instead of", "acknowledge", "reframe", "ask",
                "often hide", "surface", "recommend"
            ]):
                importance = calculate_importance(insight)
                if importance >= 0.5:  # Lower threshold to catch more insights
                    memories.append(SessionMemory(
                        content=insight,
                        importance=importance,
                        project_id=self.project_id
                    ))
                    insight_count += 1

        return memories

    def _smart_dedup_decision(
        self,
        new_content: str,
        existing_content: str,
        similarity: float
    ) -> str:
        """
        LLM-powered dedup decision for gray area (50-90% similarity).

        With fallback: If LLM times out, use stricter similarity threshold (>0.75 = duplicate).

        Args:
            new_content: New memory content
            existing_content: Existing memory content
            similarity: Word overlap similarity (0.0-1.0)

        Returns:
            "DUPLICATE" | "UPDATE" | "NEW"
        """
        # Fast path: obvious cases
        if similarity < 0.5:
            return "NEW"
        if similarity > 0.9:
            return "DUPLICATE"

        # Gray area (50-90%) - ask LLM with fallback
        from .llm_extractor import ask_claude

        prompt = f"""Compare these two memories:

New: {new_content}
Existing: {existing_content}

Is the new memory:
- DUPLICATE (same fact, skip it)
- UPDATE (refinement or replacement of existing)
- NEW (genuinely new information)

Answer with ONE WORD ONLY."""

        decision = ask_claude(prompt, timeout=30, max_retries=2).strip().upper()

        # LLM fallback: Use stricter similarity threshold when LLM fails
        if not decision:
            # Timeout or failure - use conservative similarity-based decision
            if similarity > 0.75:
                return "DUPLICATE"
            else:
                return "NEW"

        if "DUPLICATE" in decision:
            return "DUPLICATE"
        elif "UPDATE" in decision:
            return "UPDATE"
        else:
            return "NEW"

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

        # Pre-compute normalized word sets and content mapping
        existing_data = []
        for existing in existing_memories:
            text_clean = _NORMALIZE_PATTERN.sub(' ', existing.content.lower())
            words = frozenset(w for w in text_clean.split() if w)
            if words:
                existing_data.append({
                    'words': words,
                    'content': existing.content,
                    'id': existing.id
                })

        unique_memories = []

        for new_mem in new_memories:
            text_clean = _NORMALIZE_PATTERN.sub(' ', new_mem.content.lower())
            new_words = frozenset(w for w in text_clean.split() if w)

            # Skip empty memories
            if not new_words:
                continue

            is_duplicate = False
            new_len = len(new_words)
            best_match_similarity = 0.0
            best_match_content = None

            for existing in existing_data:
                # Calculate bidirectional similarity
                overlap = len(new_words & existing['words'])
                new_similarity = overlap / new_len
                existing_similarity = overlap / len(existing['words'])
                max_similarity = max(new_similarity, existing_similarity)

                # Track best match for LLM decision
                if max_similarity > best_match_similarity:
                    best_match_similarity = max_similarity
                    best_match_content = existing['content']

                # Definite duplicate if >90% similar
                if max_similarity >= 0.9:
                    is_duplicate = True
                    break

            # Gray area (50-90%) - use LLM if enabled
            if not is_duplicate and use_llm_dedup and best_match_similarity >= 0.5:
                decision = self._smart_dedup_decision(
                    new_mem.content,
                    best_match_content,
                    best_match_similarity
                )

                if decision == "DUPLICATE":
                    is_duplicate = True

            if not is_duplicate:
                unique_memories.append(new_mem)

        return unique_memories

    def consolidate_session(
        self,
        session_file: Path,
        use_llm: bool = True,
        skip_save: bool = False
    ) -> ConsolidationResult:
        """
        Complete consolidation pipeline for a session

        Reads session → extracts memories (patterns + LLM) → deduplicates → saves

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

        # Deduplicate against existing memories
        unique_memories = self.deduplicate(extracted_memories)

        # Save to memory-ts (unless skip_save=True)
        session_id = session_file.stem
        saved_count = 0
        saved_list = []
        replaced_count = 0

        if not skip_save:
            # Import contradiction detector
            from .contradiction_detector import check_contradictions

            for memory in unique_memories:
                memory.session_id = session_id

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

                # Save new memory (whether replacing or not)
                created_memory = self.memory_client.create(
                    content=memory.content,
                    project_id=memory.project_id,
                    tags=memory.tags,
                    importance=memory.importance,
                    scope="project",  # New memories start as project-scope
                    session_id=session_id,  # Track provenance (legacy field)
                    source_session_id=session_id  # Track provenance (new field)
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
