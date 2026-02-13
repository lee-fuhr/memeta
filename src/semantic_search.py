"""
Local semantic search using sentence-transformers embeddings.

No API costs - runs locally using all-MiniLM-L6-v2 (384-dim vectors).
Enables "find workspace when memory says office" type queries.

Feature 11: Experimental - may be slow on large memory sets.
"""

import numpy as np
from typing import List, Dict, Optional
import json
import os
from pathlib import Path
from collections import OrderedDict

# Lazy import - only load if semantic search is used
_model = None
_embeddings_cache = OrderedDict()  # LRU-bounded cache
_CACHE_MAX_SIZE = 1000


def get_model():
    """Lazy-load sentence-transformers model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer('all-MiniLM-L6-v2')
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
    return _model


def embed_text(text: str) -> np.ndarray:
    """
    Generate embedding for text.

    Args:
        text: Text to embed

    Returns:
        384-dim numpy array
    """
    model = get_model()
    return model.encode(text, convert_to_numpy=True)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Similarity score (0.0-1.0)
    """
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def semantic_search(
    query: str,
    memories: List[Dict],
    top_k: int = 10,
    threshold: float = 0.3
) -> List[Dict]:
    """
    Search memories using semantic similarity.

    Args:
        query: Search query
        memories: List of memory dicts with 'content' key
        top_k: Number of top results to return
        threshold: Minimum similarity score

    Returns:
        List of memories with similarity scores, sorted by relevance
    """
    # Embed query
    query_embedding = embed_text(query)

    # Embed all memories and calculate similarities
    scored_memories = []

    for memory in memories:
        content = memory.get('content', '')
        if not content:
            continue

        # Cache embeddings to avoid re-computing (LRU-bounded)
        cache_key = content[:100]  # Use first 100 chars as cache key
        if cache_key in _embeddings_cache:
            # Move to end (mark as recently used)
            _embeddings_cache.move_to_end(cache_key)
            mem_embedding = _embeddings_cache[cache_key]
        else:
            mem_embedding = embed_text(content)
            _embeddings_cache[cache_key] = mem_embedding
            # Evict oldest if over limit
            if len(_embeddings_cache) > _CACHE_MAX_SIZE:
                _embeddings_cache.popitem(last=False)

        # Calculate similarity
        similarity = cosine_similarity(query_embedding, mem_embedding)

        if similarity >= threshold:
            scored_memories.append({
                **memory,
                'similarity': float(similarity)
            })

    # Sort by similarity
    scored_memories.sort(key=lambda x: x['similarity'], reverse=True)

    return scored_memories[:top_k]


def clear_embedding_cache():
    """Clear embedding cache (useful for testing or memory management)."""
    global _embeddings_cache
    _embeddings_cache = OrderedDict()


def precompute_embeddings(memories: List[Dict]) -> Dict[str, np.ndarray]:
    """
    Precompute embeddings for a batch of memories.

    Useful for speeding up future searches.

    Args:
        memories: List of memory dicts

    Returns:
        Dict mapping content (first 100 chars) to embedding
    """
    model = get_model()

    texts = [m.get('content', '')[:100] for m in memories if m.get('content')]
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)

    cache = {}
    for text, embedding in zip(texts, embeddings):
        cache[text] = embedding

    return cache
