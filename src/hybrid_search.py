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

from typing import List, Dict, Optional
import math
import numpy as np
from collections import Counter


def compute_idf(documents: List[str]) -> Dict[str, float]:
    """
    Compute IDF (Inverse Document Frequency) for all terms in the corpus.

    Uses smoothed IDF formula: log((N + 1) / (count + 1)) + 1
    where N is the total number of documents and count is the number
    of documents containing the term.

    Args:
        documents: List of document text strings

    Returns:
        Dict mapping term to IDF score
    """
    n = len(documents)
    if n == 0:
        return {}

    # Count how many documents contain each term
    doc_freq: Dict[str, int] = {}
    for doc in documents:
        # Use set to count each term once per document
        unique_terms = set(doc.lower().split())
        for term in unique_terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    # Compute IDF for each term
    idf: Dict[str, float] = {}
    for term, count in doc_freq.items():
        idf[term] = math.log((n + 1) / (count + 1)) + 1

    return idf


def normalize_scores(scores: List[float]) -> List[float]:
    """
    Normalize scores to [0, 1] range by dividing by max score.

    If all scores are zero or the list is empty, returns zeros.

    Args:
        scores: List of raw scores

    Returns:
        List of normalized scores in [0, 1]
    """
    if not scores:
        return []

    max_score = max(scores)
    if max_score == 0.0:
        return [0.0] * len(scores)

    return [s / max_score for s in scores]


def bm25_score(
    query: str,
    document: str,
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75,
    idf: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculate BM25 score for document given query.

    Args:
        query: Search query
        document: Document text
        avg_doc_length: Average document length in corpus
        k1: Term frequency saturation parameter (default: 1.5)
        b: Length normalization parameter (default: 0.75)
        idf: Optional dict mapping terms to IDF scores. If None, uses 1.0 for all terms.

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

        # Use provided IDF or fall back to 1.0
        term_idf = idf.get(term, 1.0) if idf is not None else 1.0

        score += term_idf * (numerator / denominator)

    return score


def _cosine_similarity(a, b) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        a: First vector (numpy array or list)
        b: Second vector (numpy array or list)

    Returns:
        Cosine similarity in [-1, 1]
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def hybrid_search(
    query: str,
    memories: List[Dict],
    top_k: int = 10,
    semantic_weight: float = 0.7,
    bm25_weight: float = 0.3,
    use_semantic: bool = True,
    embeddings: Optional[Dict[str, list]] = None
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
        embeddings: Optional dict mapping content (first 100 chars) to
            pre-computed embedding vectors. If provided with use_semantic=True,
            uses cosine similarity instead of calling semantic_search model.

    Returns:
        List of memories with hybrid scores
    """
    if not memories:
        return []

    # Calculate average document length for BM25
    avg_length = sum(len(m.get('content', '').split()) for m in memories) / len(memories)

    # Pre-compute IDF from corpus
    corpus_docs = [m.get('content', '') for m in memories if m.get('content', '')]
    corpus_idf = compute_idf(corpus_docs)

    # If using pre-computed embeddings, embed the query once
    query_embedding = None
    if use_semantic and embeddings is not None:
        try:
            from .semantic_search import embed_text
            query_embedding = embed_text(query)
        except (ImportError, Exception):
            query_embedding = None

    # Score all memories
    scored_memories = []
    # Track local semantic weight/bm25 weight (may be adjusted on fallback)
    local_semantic_weight = semantic_weight
    local_bm25_weight = bm25_weight

    for memory in memories:
        content = memory.get('content', '')
        if not content:
            continue

        # BM25 score (with corpus IDF)
        bm25 = bm25_score(query, content, avg_length, idf=corpus_idf)

        # Semantic score (if enabled)
        if use_semantic:
            if embeddings is not None and query_embedding is not None:
                # Use pre-computed embeddings path
                cache_key = content[:100]
                if cache_key in embeddings:
                    semantic_score = max(0.0, _cosine_similarity(query_embedding, embeddings[cache_key]))
                else:
                    semantic_score = 0.0
            else:
                try:
                    from .semantic_search import semantic_search
                    semantic_results = semantic_search(query, [memory], top_k=1)
                    semantic_score = semantic_results[0].get('similarity', 0.0) if semantic_results else 0.0
                except (ImportError, Exception):
                    # Fall back to BM25 only if semantic search unavailable
                    semantic_score = 0.0
                    local_semantic_weight = 0.0
                    local_bm25_weight = 1.0
        else:
            semantic_score = 0.0

        scored_memories.append({
            **memory,
            'semantic_score': semantic_score,
            'bm25_score': bm25
        })

    # Normalize BM25 scores to [0, 1] before weighted combination
    raw_bm25_scores = [m['bm25_score'] for m in scored_memories]
    normalized_bm25 = normalize_scores(raw_bm25_scores)

    # Compute hybrid score using normalized BM25
    for i, mem in enumerate(scored_memories):
        hybrid_score = (local_semantic_weight * mem['semantic_score']) + (local_bm25_weight * normalized_bm25[i])
        mem['hybrid_score'] = hybrid_score
        mem['bm25_score_normalized'] = normalized_bm25[i]

    # Sort by hybrid score
    scored_memories.sort(key=lambda x: x['hybrid_score'], reverse=True)

    # Add relevance explanations
    top_results = scored_memories[:top_k]
    from .relevance_explanation import add_explanations_to_results
    add_explanations_to_results(query, top_results)

    return top_results


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
