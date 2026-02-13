"""Memory relationships graph - Feature 25: Connect related memories"""
from typing import List, Dict, Tuple

def add_relationship(mem_a_id: str, mem_b_id: str, rel_type: str) -> Dict:
    """Add relationship: 'led_to' | 'contradicts' | 'references' | 'supports'"""
    return {'from': mem_a_id, 'to': mem_b_id, 'type': rel_type, 'weight': 1.0}

def find_related_memories(memory_id: str, relationships: List[Dict]) -> List[str]:
    """Find all memories connected to this one."""
    related = set()
    for rel in relationships:
        if rel['from'] == memory_id:
            related.add(rel['to'])
        elif rel['to'] == memory_id:
            related.add(rel['from'])
    return list(related)

def build_graph(memories: List[Dict], relationships: List[Dict]) -> Dict:
    """Build graph structure for visualization."""
    return {
        'nodes': [{'id': m['id'], 'label': m['content'][:50]} for m in memories],
        'edges': [{'source': r['from'], 'target': r['to'], 'type': r['type']} for r in relationships]
    }
