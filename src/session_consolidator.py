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

from .memory_ts_client import MemoryTSClient
from .importance_engine import calculate_importance, get_importance_score


@dataclass
class SessionMemory:
    """Memory extracted from session"""
    content: str
    importance: float
    project_id: str
    tags: List[str] = field(default_factory=lambda: ["#learning"])
    session_id: Optional[str] = None


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
        self.session_dir = Path(session_dir) if session_dir else Path.home() / ".claude/projects"
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
        and new format (role/content nested in 'message' field)

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

            # Only include user and assistant messages with actual content
            if content and role in ('user', 'assistant'):
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

        # Pattern 1: Explicit learning statements
        learning_patterns = [
            r"(?:learned|discovered|realized|found out|noticed) that ([^.!?]+[.!?])",
            r"(?:key insight|important to note|worth remembering):? ([^.!?]+[.!?])",
            r"(?:pattern|trend) (?:I noticed|observed|saw):? ([^.!?]+[.!?])"
        ]

        for pattern in learning_patterns:
            matches = re.finditer(pattern, conversation, re.IGNORECASE)
            for match in matches:
                learning_content = match.group(1).strip()
                if len(learning_content) > 20:  # Substantial content
                    importance = calculate_importance(learning_content)
                    if importance >= 0.5:  # Threshold for saving
                        memories.append(SessionMemory(
                            content=learning_content,
                            importance=importance,
                            project_id=self.project_id
                        ))

        # Pattern 2: User corrections (important signals)
        correction_patterns = [
            r"user:.*?(?:actually|correction|no,|wrong|mistake|should be|meant to say) ([^.!?]+[.!?])",
            r"user:.*?(?:better way|instead try|prefer) ([^.!?]+[.!?])"
        ]

        for pattern in correction_patterns:
            matches = re.finditer(pattern, conversation, re.IGNORECASE | re.DOTALL)
            for match in matches:
                correction_content = match.group(1).strip()
                if len(correction_content) > 15:
                    # Corrections get boosted importance
                    base_importance = calculate_importance(correction_content)
                    boosted_importance = min(0.95, base_importance * 1.2)
                    memories.append(SessionMemory(
                        content=f"Correction: {correction_content}",
                        importance=boosted_importance,
                        project_id=self.project_id
                    ))

        # Pattern 3: Problem-solution pairs
        problem_solution_pattern = r"(?:problem|issue|challenge):.*?([^.!?]+[.!?]).*?(?:solution|fix|approach):.*?([^.!?]+[.!?])"
        matches = re.finditer(problem_solution_pattern, conversation, re.IGNORECASE | re.DOTALL)
        for match in matches:
            problem = match.group(1).strip()
            solution = match.group(2).strip()
            if len(problem) > 10 and len(solution) > 10:
                content = f"Problem: {problem} Solution: {solution}"
                importance = calculate_importance(content)
                if importance >= 0.6:
                    memories.append(SessionMemory(
                        content=content,
                        importance=importance,
                        project_id=self.project_id
                    ))

        # Pattern 4: Assistant insights in response to questions
        # Look for substantial assistant responses that provide guidance
        assistant_insights = re.finditer(
            r"assistant:.*?([A-Z][^.!?]{30,}[.!?])",
            conversation,
            re.DOTALL
        )

        insight_count = 0
        for match in assistant_insights:
            if insight_count >= 3:  # Limit to top insights per session
                break

            insight = match.group(1).strip()

            # Filter out trivial responses
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

    def deduplicate(self, new_memories: List[SessionMemory]) -> List[SessionMemory]:
        """
        Remove memories that duplicate existing ones

        Uses fuzzy matching - if >80% of words overlap, consider duplicate

        Args:
            new_memories: List of newly extracted memories

        Returns:
            Deduplicated list
        """
        existing_memories = self.memory_client.search(project_id=self.project_id)

        def normalize_text(text: str) -> set:
            """Normalize text for comparison - strip punctuation, lowercase"""
            # Remove punctuation
            text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
            # Split and remove empty strings
            words = [w for w in text_clean.split() if w]
            return set(words)

        unique_memories = []

        for new_mem in new_memories:
            is_duplicate = False
            new_words = normalize_text(new_mem.content)

            # Skip empty memories
            if len(new_words) == 0:
                continue

            for existing in existing_memories:
                existing_words = normalize_text(existing.content)

                if len(existing_words) == 0:
                    continue

                # Calculate bidirectional similarity
                overlap = len(new_words & existing_words)
                new_similarity = overlap / len(new_words) if len(new_words) > 0 else 0
                existing_similarity = overlap / len(existing_words) if len(existing_words) > 0 else 0

                # Consider duplicate if either direction is >70% similar
                # This catches "short version of existing" and "existing is short version of new"
                if new_similarity >= 0.7 or existing_similarity >= 0.7:
                    # Too similar - likely duplicate
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique_memories.append(new_mem)

        return unique_memories

    def consolidate_session(
        self,
        session_file: Path,
        use_llm: bool = True
    ) -> ConsolidationResult:
        """
        Complete consolidation pipeline for a session

        Reads session → extracts memories (patterns + LLM) → deduplicates → saves

        Args:
            session_file: Path to session JSONL file
            use_llm: If True, also run LLM extraction via Claude CLI

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

        # Save to memory-ts
        session_id = session_file.stem
        saved_count = 0

        for memory in unique_memories:
            memory.session_id = session_id
            self.memory_client.create(
                content=memory.content,
                project_id=memory.project_id,
                tags=memory.tags,
                importance=memory.importance,
                scope="project",  # New memories start as project-scope
                session_id=session_id  # Track provenance
            )
            saved_count += 1

        # Calculate session quality
        quality = calculate_session_quality(extracted_memories)

        return ConsolidationResult(
            memories_extracted=len(extracted_memories),
            memories_saved=saved_count,
            memories_deduplicated=len(extracted_memories) - len(unique_memories),
            session_quality=quality
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
