"""
Feature 32: Quality Scoring

Auto-detect low-quality memories:
- Too vague
- Duplicate content
- Unclear/ambiguous
- Missing context

Suggest improvements or archival.
"""

import sys
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass
import re

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory_ts_client import Memory


@dataclass
class QualityScore:
    """Quality assessment for a memory"""
    memory_id: str
    score: float  # 0.0-1.0 (1.0 = high quality)
    issues: List[str]
    suggestions: List[str]


class QualityScoring:
    """
    Automated quality assessment for memories.
    
    Checks:
    - Length (too short/long)
    - Specificity (vague language)
    - Clarity (complete sentences)
    - Actionability (contains verbs)
    
    Example:
        scorer = QualityScoring()
        
        assessment = scorer.assess_memory(memory)
        if assessment.score < 0.5:
            print(f"Low quality: {assessment.issues}")
            print(f"Suggestions: {assessment.suggestions}")
    """

    # Vague words that indicate low quality
    VAGUE_WORDS = [
        "maybe", "might", "possibly", "perhaps", "somewhat",
        "kind of", "sort of", "fairly", "relatively", "stuff",
        "things", "something", "somehow"
    ]
    
    # Quality thresholds
    MIN_LENGTH = 10
    MAX_LENGTH = 500
    OPTIMAL_LENGTH_MIN = 30
    OPTIMAL_LENGTH_MAX = 200

    def assess_memory(self, memory: Memory) -> QualityScore:
        """Assess quality of a single memory."""
        issues = []
        suggestions = []
        score_components = []
        
        content = memory.content.strip()
        
        # Check 1: Length
        if len(content) < self.MIN_LENGTH:
            issues.append("Too short (lacks detail)")
            suggestions.append("Add more context and specifics")
            score_components.append(0.3)
        elif len(content) > self.MAX_LENGTH:
            issues.append("Too long (should be concise)")
            suggestions.append("Split into multiple focused memories")
            score_components.append(0.7)
        elif self.OPTIMAL_LENGTH_MIN <= len(content) <= self.OPTIMAL_LENGTH_MAX:
            score_components.append(1.0)
        else:
            score_components.append(0.8)
        
        # Check 2: Vague language
        vague_count = sum(1 for word in self.VAGUE_WORDS if word in content.lower())
        if vague_count > 2:
            issues.append(f"Contains vague language ({vague_count} vague words)")
            suggestions.append("Be more specific and concrete")
            score_components.append(0.5)
        elif vague_count > 0:
            score_components.append(0.7)
        else:
            score_components.append(1.0)
        
        # Check 3: Actionability (contains verbs)
        verbs = self._count_verbs(content)
        if verbs == 0:
            issues.append("No action verbs (not actionable)")
            suggestions.append("Add what to do, not just what is")
            score_components.append(0.4)
        else:
            score_components.append(1.0)
        
        # Check 4: Complete sentences
        if not content.endswith((".", "!", "?")):
            issues.append("Incomplete sentence")
            suggestions.append("End with proper punctuation")
            score_components.append(0.8)
        else:
            score_components.append(1.0)
        
        # Check 5: Starts with capital letter
        if content and not content[0].isupper():
            issues.append("Doesn't start with capital letter")
            suggestions.append("Capitalize first word")
            score_components.append(0.9)
        else:
            score_components.append(1.0)
        
        # Calculate overall score (average of components)
        overall_score = sum(score_components) / len(score_components) if score_components else 0.5
        
        return QualityScore(
            memory_id=memory.id,
            score=overall_score,
            issues=issues,
            suggestions=suggestions
        )

    def batch_assess(self, memories: List[Memory]) -> List[QualityScore]:
        """Assess multiple memories."""
        return [self.assess_memory(m) for m in memories]

    def find_low_quality(self, memories: List[Memory], threshold: float = 0.6) -> List[QualityScore]:
        """Find memories below quality threshold."""
        assessments = self.batch_assess(memories)
        return [a for a in assessments if a.score < threshold]

    def _count_verbs(self, text: str) -> int:
        """Simple verb detection (common action words)."""
        action_verbs = [
            "use", "add", "remove", "create", "delete", "update", "fix", "test",
            "verify", "check", "validate", "ensure", "avoid", "prevent", "enable",
            "disable", "configure", "install", "run", "execute", "deploy"
        ]
        
        words = text.lower().split()
        return sum(1 for word in words if word in action_verbs)
