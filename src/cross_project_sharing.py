"""Cross-project memory sharing - Feature 27: Share insights between clients"""
from typing import List, Dict, Optional

def tag_as_universal(memory: Dict) -> Dict:
    """Mark memory as applicable across projects."""
    if '#universal' not in memory.get('tags', []):
        memory['tags'] = memory.get('tags', []) + ['#universal']
    return memory

def get_universal_memories(all_memories: List[Dict]) -> List[Dict]:
    """Get memories tagged as universal."""
    return [m for m in all_memories if '#universal' in m.get('tags', [])]

def suggest_cross_project(memory: Dict, other_projects: List[str]) -> List[str]:
    """Suggest which projects might benefit from this memory."""
    # Would use LLM to determine relevance
    # For now, return all projects for universal memories
    if '#universal' in memory.get('tags', []):
        return other_projects
    return []

def share_to_project(memory: Dict, target_project: str) -> Dict:
    """Create copy of memory in target project with source attribution."""
    shared = memory.copy()
    shared['project_id'] = target_project
    shared['source_project'] = memory.get('project_id')
    shared['tags'] = shared.get('tags', []) + ['#shared-from-other-project']
    return shared
