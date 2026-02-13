"""
Hybrid search - 70% semantic + 30% BM25 keyword matching.

Feature 14: Combine semantic understanding with keyword precision.
OpenClaw pattern - best of both worlds.

Example:
- Query: "office setup"
- Semantic finds: "workspace configuration", "desk arrangement"
- BM25 finds: exact matches for "office"
- Hybrid combines both with weighted scores
"""

from typing import List, Dict
import math
from collections import Counter


def bm25_score(
    query: str,
    document: str,
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75
) -> float:
    """
    Calculate BM25 score for document given query.

    Args:
        query: Search query
        document: Document text
        avg_doc_length: Average document length in corpus
        k1: Term frequency saturation parameter (default: 1.5)
        b: Length normalization parameter (default: 0.75)

    Returns:
        BM25 score
    """
    # Tokenize
    query_terms = query.lower().split()
    doc_terms = document.lower().split()

    # Document length
    doc_length = len(doc_terms)

    # Term frequency in document
    term_freq = Counter(doc_terms)

    # Calculate score
    score = 0.0

    for term in query_terms:
        if term not in term_freq:
            continue

        # Term frequency component
        tf = term_freq[term]
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_length / avg_doc_length))

        # For simplicity, assume all terms have same IDF (would normally compute from corpus)
        # IDF = log((N - df + 0.5) / (df + 0.5))
        # Using simplified IDF=1 for now
        idf = 1.0

        score += idf * (numerator / denominator)

    return score


def hybrid_search(
    query: str,
    memories: List[Dict],
    top_k: int = 10,
    semantic_weight: float = 0.7,
    bm25_weight: float = 0.3,
    use_semantic: bool = True
) -> List[Dict]:
    """
    Search using hybrid semantic + BM25 approach.

    Args:
        query: Search query
        memories: List of memory dicts with 'content' key
        top_k: Number of results to return
        semantic_weight: Weight for semantic score (default: 0.7)
        bm25_weight: Weight for BM25 score (default: 0.3)
        use_semantic: If False, use BM25 only (faster, no model needed)

    Returns:
        List of memories with hybrid scores
    """
    if not memories:
        return []

    # Calculate average document length for BM25
    avg_length = sum(len(m.get('content', '').split()) for m in memories) / len(memories)

    # Score all memories
    scored_memories = []

    for memory in memories:
        content = memory.get('content', '')
        if not content:
            continue

        # BM25 score
        bm25 = bm25_score(query, content, avg_length)

        # Semantic score (if enabled)
        if use_semantic:
            try:
                from .semantic_search import semantic_search
                semantic_results = semantic_search(query, [memory], top_k=1)
                semantic_score = semantic_results[0].get('similarity', 0.0) if semantic_results else 0.0
            except (ImportError, Exception):
                # Fall back to BM25 only if semantic search unavailable
                semantic_score = 0.0
                semantic_weight = 0.0
                bm25_weight = 1.0
        else:
            semantic_score = 0.0

        # Hybrid score (weighted combination)
        hybrid_score = (semantic_weight * semantic_score) + (bm25_weight * bm25)

        scored_memories.append({
            **memory,
            'hybrid_score': hybrid_score,
            'semantic_score': semantic_score,
            'bm25_score': bm25
        })

    # Sort by hybrid score
    scored_memories.sort(key=lambda x: x['hybrid_score'], reverse=True)

    return scored_memories[:top_k]


def keyword_search(
    query: str,
    memories: List[Dict],
    top_k: int = 10
) -> List[Dict]:
    """
    Pure BM25 keyword search (fast, no ML dependencies).

    Args:
        query: Search query
        memories: List of memory dicts
        top_k: Number of results

    Returns:
        List of memories with BM25 scores
    """
    return hybrid_search(
        query=query,
        memories=memories,
        top_k=top_k,
        use_semantic=False
    )
