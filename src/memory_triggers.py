"""Memory-triggered automations - Feature 28-32"""
from typing import Dict, List, Callable
import re

class MemoryTrigger:
    """When memory X detected, execute action Y"""
    def __init__(self, pattern: str, action: Callable, name: str):
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.action = action
        self.name = name
    
    def matches(self, memory: Dict) -> bool:
        return bool(self.pattern.search(memory.get('content', '')))
    
    def execute(self, memory: Dict):
        return self.action(memory)

# Feature 28: Memory-triggered automations
def create_deadline_trigger():
    """When memory mentions deadline, add to Todoist"""
    def action(mem):
        # Would integrate with Todoist
        print(f"Add to Todoist: {mem['content']}")
    return MemoryTrigger(r'deadline|due\s+\w+\s+\d', action, "deadline_to_todoist")

# Feature 29: Smart memory alerts  
def check_expiring_memories(memories: List[Dict], days_threshold: int = 7) -> List[Dict]:
    """Alert on memories expiring soon."""
    from datetime import datetime, timedelta
    cutoff = datetime.now() + timedelta(days=days_threshold)
    return [m for m in memories if m.get('expiration_date') and 
            datetime.fromisoformat(m['expiration_date']) < cutoff]

# Feature 30: Memory-aware search
def contextual_search(query: str, context: Dict) -> str:
    """Parse natural language query with context."""
    # "Find memories about X from last month"
    # "What did I learn about Y while working on Z?"
    return query  # Would parse with LLM

# Feature 31: Auto-summarization of topics
def summarize_topic(topic: str, memories: List[Dict]) -> str:
    """Generate narrative from all memories on topic."""
    from llm_extractor import ask_claude
    contents = '\n'.join([f"- {m['content']}" for m in memories[:20]])
    return ask_claude(f"Summarize everything about {topic}:\n{contents}", timeout=30)

# Feature 32: Memory quality scoring
def score_quality(memory: Dict) -> float:
    """Score 0-1 based on clarity, specificity, usefulness."""
    content = memory.get('content', '')
    score = 0.5
    if len(content) < 20: score -= 0.3  # Too short
    if len(content) > 500: score -= 0.2  # Too long
    if content.count(' ') < 3: score -= 0.2  # Too vague
    if any(word in content.lower() for word in ['specifically', 'because', 'example']):
        score += 0.2  # Good specificity
    return max(0.0, min(1.0, score))
