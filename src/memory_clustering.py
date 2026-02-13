"""Memory clustering & topic detection - Feature 24"""
import numpy as np
from typing import List, Dict
from collections import defaultdict

def cluster_memories(memories: List[Dict], n_clusters: int = 10) -> Dict:
    """Cluster memories by semantic similarity using K-means."""
    try:
        from sklearn.cluster import KMeans
        from semantic_search import embed_text
        embeddings = np.array([embed_text(m['content']) for m in memories])
        kmeans = KMeans(n_clusters=min(n_clusters, len(memories)), random_state=42)
        labels = kmeans.fit_predict(embeddings)
        clusters = defaultdict(list)
        for mem, label in zip(memories, labels):
            clusters[int(label)].append(mem)
        return dict(clusters)
    except ImportError:
        return {}

def generate_topic_label(cluster_memories: List[Dict]) -> str:
    """Generate topic label for cluster using LLM."""
    from llm_extractor import ask_claude
    sample = '\n'.join([f"- {m['content']}" for m in cluster_memories[:5]])
    return ask_claude(f"Generate 2-4 word topic label:\n{sample}\n\nTopic:", timeout=10).strip()
