"""Third-party integrations - Features 38-42"""
import json
from pathlib import Path
from typing import List, Dict

# Feature 38: Obsidian sync
def export_to_obsidian(memories: List[Dict], vault_path: Path) -> int:
    """Export memories as markdown notes to Obsidian vault."""
    count = 0
    for mem in memories:
        filename = f"{mem['id']}.md"
        content = f"# {mem['content'][:50]}\n\n{mem['content']}\n\n"
        content += f"Tags: {' '.join(mem.get('tags', []))}\n"
        content += f"Importance: {mem['importance']}\n"
        (vault_path / filename).write_text(content)
        count += 1
    return count

# Feature 39: Notion integration  
def export_to_notion_json(memories: List[Dict]) -> List[Dict]:
    """Format memories for Notion database import."""
    return [{
        'Name': {'title': [{'text': {'content': m['content'][:100]}}]},
        'Content': {'rich_text': [{'text': {'content': m['content']}}]},
        'Importance': {'number': m['importance']},
        'Tags': {'multi_select': [{'name': t} for t in m.get('tags', [])]}
    } for m in memories]

# Feature 40: Roam Research sync
def export_to_roam(memories: List[Dict]) -> str:
    """Export as Roam daily notes format."""
    lines = []
    for mem in memories:
        lines.append(f"- {mem['content']} #memory")
        lines.append(f"  - Importance:: {mem['importance']}")
    return '\n'.join(lines)

# Feature 41: Email intelligence v2
def learn_from_email_corrections(corrections: List[Dict]) -> Dict:
    """Build email categorization rules from corrections."""
    rules = {}
    for corr in corrections:
        if 'email' in corr.get('content', '').lower():
            # Extract pattern
            rules[corr['id']] = corr['content']
    return rules

# Feature 42: Meeting intelligence integration
def link_memory_to_meeting(memory: Dict, meeting_id: str) -> Dict:
    """Connect memory to meeting transcript."""
    memory['meeting_id'] = meeting_id
    memory['tags'] = memory.get('tags', []) + ['#from-meeting']
    return memory
