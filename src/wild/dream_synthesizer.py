"""
Feature 75: Dream Synthesis (Hidden Connections)

Nightly process that finds non-obvious connections across ALL memories.

Unlike standard clustering (explicit keyword overlap), dream synthesis finds:
- Conceptual parallels across different domains
- Contradictory patterns that need resolution
- Missing pieces (A + B exists, but C is missing)
- Emergent patterns from weak signals

Process:
1. Load all memories (project + global scope)
2. Build semantic relationship graph
3. Find non-obvious connections using:
   - Semantic similarity (beyond keywords)
   - Temporal co-occurrence (appear in same time window)
   - Causal chains (A led to B, B led to C → A-C connection)
   - Contradiction resolution (conflicting memories → synthesis)
4. Generate insights: "These 5 memories from different projects share hidden pattern X"
5. Present as morning briefing: "While you slept, I connected these dots..."

Integration: Runs nightly (3am), outputs to synthesis queue for review
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict, Counter
import re


@dataclass
class MemoryNode:
    """A memory in the relationship graph"""
    id: str
    content: str
    project: str
    tags: List[str]
    importance: float
    created_at: datetime


@dataclass
class Connection:
    """A discovered connection between memories"""
    memory_ids: List[str]
    connection_type: str  # 'semantic', 'temporal', 'causal', 'contradiction'
    strength: float  # 0.0-1.0
    evidence: str  # Why they're connected
    insight: str  # What this connection reveals


@dataclass
class Synthesis:
    """A synthesized insight from multiple connections"""
    id: str
    title: str
    insight: str
    supporting_memories: List[str]
    connections: List[Connection]
    novelty_score: float  # How non-obvious is this? (0.0-1.0)
    confidence: float  # How confident are we? (0.0-1.0)
    projects_spanned: List[str]
    created_at: datetime


class DreamSynthesizer:
    """
    Finds hidden connections across memories while you sleep.

    Discovery strategies:
    1. Semantic bridging: memories with overlapping concepts but different keywords
    2. Temporal clustering: memories from different projects in same time window
    3. Causal chain inference: A→B, B→C implies A→C relationship
    4. Contradiction synthesis: opposing memories → identify context difference

    Runs nightly at 3am, generates synthesis queue for morning review.
    """

    # Discovery thresholds
    SEMANTIC_THRESHOLD = 0.6  # Minimum similarity for connection
    TEMPORAL_WINDOW = timedelta(days=7)  # Co-occurrence window
    MIN_SUPPORT = 3  # Minimum memories to form synthesis
    NOVELTY_THRESHOLD = 0.5  # Minimum novelty to surface
    MAX_MEMORIES = 1000  # PERFORMANCE FIX: Limit to top N memories (prevents O(n²) explosion)

    def __init__(self, db_path: str = None, memory_db_path: str = None):
        """Initialize synthesizer with database"""
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "intelligence.db"
        if memory_db_path is None:
            memory_db_path = Path(__file__).parent.parent.parent / "fsrs.db"

        self.db_path = str(db_path)
        self.memory_db_path = str(memory_db_path)
        self._init_db()

    def _init_db(self):
        """Create tables for synthesis tracking"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dream_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_ids TEXT NOT NULL,  -- JSON array
                    connection_type TEXT NOT NULL CHECK(connection_type IN ('semantic', 'temporal', 'causal', 'contradiction')),
                    strength REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    insight TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dream_syntheses (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    insight TEXT NOT NULL,
                    supporting_memories TEXT NOT NULL,  -- JSON array
                    connection_ids TEXT NOT NULL,  -- JSON array
                    novelty_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    projects_spanned TEXT NOT NULL,  -- JSON array
                    created_at TEXT NOT NULL,
                    reviewed INTEGER DEFAULT 0,
                    reviewed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS synthesis_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    synthesis_id TEXT NOT NULL,
                    priority REAL NOT NULL,  -- novelty * confidence
                    queued_at TEXT NOT NULL,
                    presented INTEGER DEFAULT 0,
                    presented_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_connections_type ON dream_connections(connection_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_syntheses_created ON dream_syntheses(created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_priority ON synthesis_queue(priority DESC, presented)")

    def run_nightly_synthesis(self) -> List[Synthesis]:
        """
        Main nightly synthesis process.

        Steps:
        1. Load all memories
        2. Discover connections
        3. Generate syntheses
        4. Queue for morning review

        Returns:
            List of generated syntheses
        """
        # Load memories from memory-ts database
        memories = self._load_memories()

        if len(memories) < self.MIN_SUPPORT:
            return []  # Not enough data

        # Discover connections
        connections = []
        connections.extend(self._discover_semantic_connections(memories))
        connections.extend(self._discover_temporal_connections(memories))
        connections.extend(self._discover_causal_chains(memories))
        connections.extend(self._discover_contradictions(memories))

        # Save connections
        for conn in connections:
            self._save_connection(conn)

        # Generate syntheses from connections
        syntheses = self._generate_syntheses(connections, memories)

        # Queue high-novelty syntheses for review
        for synthesis in syntheses:
            if synthesis.novelty_score >= self.NOVELTY_THRESHOLD:
                self._queue_synthesis(synthesis)

        return syntheses

    def _load_memories(self) -> List[MemoryNode]:
        """
        Load memories from memory-ts database.

        PERFORMANCE FIX: Limits to top MAX_MEMORIES (default 1000) by importance + recency.

        Prevents O(n²) explosion:
        - Before: 10K memories = 100M comparisons = mathematically infeasible
        - After: 1K memories = 1M comparisons = ~30s processing

        Selection strategy:
        - Top 70% by importance (high-value memories)
        - Top 30% by recency (recent context)
        """
        try:
            # Try to load from memory-ts client
            from memory_ts_client import MemoryTSClient

            client = MemoryTSClient(project_id="LFI")
            all_memories = client.search()  # Get all

            if not all_memories:
                return []

            # Sort by composite score: importance (70%) + recency (30%)
            now = datetime.now().timestamp()

            def score_memory(mem):
                # Importance component (0.0-1.0)
                importance_score = mem.importance

                # Recency component (0.0-1.0) - memories from last 30 days score highest
                days_old = (now - mem.created.timestamp()) / 86400
                recency_score = max(0.0, 1.0 - (days_old / 30))

                # Composite
                return (importance_score * 0.7) + (recency_score * 0.3)

            scored_memories = [(mem, score_memory(mem)) for mem in all_memories]
            scored_memories.sort(key=lambda x: x[1], reverse=True)

            # Take top MAX_MEMORIES
            top_memories = [mem for mem, score in scored_memories[:self.MAX_MEMORIES]]

            # Convert to MemoryNode
            nodes = []
            for mem in top_memories:
                nodes.append(MemoryNode(
                    id=mem.id,
                    content=mem.content,
                    project=mem.project_id or "global",
                    tags=mem.tags or [],
                    importance=mem.importance,
                    created_at=mem.created
                ))

            print(f"📊 Dream Mode: Selected {len(nodes)} memories (from {len(all_memories)} total)")
            return nodes

        except Exception as e:
            print(f"⚠️  Failed to load memories: {e}")
            return []

    def _discover_semantic_connections(self, memories: List[MemoryNode]) -> List[Connection]:
        """Find semantically similar memories with different surface keywords"""
        connections = []

        # Build word vectors (simplified - real version would use embeddings)
        vectors = {}
        for memory in memories:
            words = set(self._extract_keywords(memory.content))
            vectors[memory.id] = words

        # Compare all pairs
        for i, mem1 in enumerate(memories):
            for mem2 in memories[i+1:]:
                # Skip if same project (looking for cross-project insights)
                if mem1.project == mem2.project:
                    continue

                # Calculate semantic similarity (Jaccard for simplicity)
                words1 = vectors[mem1.id]
                words2 = vectors[mem2.id]

                if not words1 or not words2:
                    continue

                intersection = words1 & words2
                union = words1 | words2
                similarity = len(intersection) / len(union)

                if similarity >= self.SEMANTIC_THRESHOLD:
                    connections.append(Connection(
                        memory_ids=[mem1.id, mem2.id],
                        connection_type='semantic',
                        strength=similarity,
                        evidence=f"Shared concepts: {', '.join(list(intersection)[:5])}",
                        insight=f"Similar pattern in {mem1.project} and {mem2.project}"
                    ))

        return connections

    def _discover_temporal_connections(self, memories: List[MemoryNode]) -> List[Connection]:
        """Find memories that occurred in same time window across projects"""
        connections = []

        # Group by time windows
        windows = defaultdict(list)
        for memory in memories:
            window_key = memory.created_at.date().isocalendar()[:2]  # (year, week)
            windows[window_key].append(memory)

        # Find co-occurring memories from different projects
        for window_memories in windows.values():
            if len(window_memories) < 2:
                continue

            projects = set(m.project for m in window_memories)
            if len(projects) < 2:
                continue  # All same project

            # Check for thematic overlap
            all_keywords = Counter()
            for m in window_memories:
                all_keywords.update(self._extract_keywords(m.content))

            # Most common keywords are the theme
            theme_keywords = [k for k, count in all_keywords.most_common(3) if count >= 2]

            if theme_keywords:
                memory_ids = [m.id for m in window_memories if any(k in m.content.lower() for k in theme_keywords)]

                if len(memory_ids) >= 2:
                    connections.append(Connection(
                        memory_ids=memory_ids,
                        connection_type='temporal',
                        strength=0.7,
                        evidence=f"Co-occurred around {window_memories[0].created_at.strftime('%Y-%m-%d')}",
                        insight=f"Theme '{', '.join(theme_keywords)}' emerged across {len(projects)} projects simultaneously"
                    ))

        return connections

    def _discover_causal_chains(self, memories: List[MemoryNode]) -> List[Connection]:
        """Infer causal relationships from sequence and content"""
        connections = []

        # Look for causal language
        causal_patterns = [
            r'because of (.+)',
            r'led to (.+)',
            r'caused (.+)',
            r'resulted in (.+)',
            r'therefore (.+)',
        ]

        for memory in memories:
            for pattern in causal_patterns:
                match = re.search(pattern, memory.content, re.IGNORECASE)
                if match:
                    effect = match.group(1)

                    # Find memories about the effect
                    effect_keywords = set(self._extract_keywords(effect))

                    for other in memories:
                        if other.id == memory.id:
                            continue

                        other_keywords = set(self._extract_keywords(other.content))
                        if effect_keywords & other_keywords:
                            connections.append(Connection(
                                memory_ids=[memory.id, other.id],
                                connection_type='causal',
                                strength=0.6,
                                evidence=f"Causal language: '{match.group(0)[:50]}...'",
                                insight=f"Causal chain detected: {memory.project} → {other.project}"
                            ))

        return connections

    def _discover_contradictions(self, memories: List[MemoryNode]) -> List[Connection]:
        """Find contradictory memories that need synthesis"""
        connections = []

        # Contradiction indicators
        contradiction_pairs = [
            (['always', 'must', 'should'], ['never', 'avoid', 'don\'t']),
            (['works', 'effective', 'good'], ['fails', 'broken', 'bad']),
            (['increase', 'more', 'higher'], ['decrease', 'less', 'lower']),
        ]

        for i, mem1 in enumerate(memories):
            for mem2 in memories[i+1:]:
                # Check for contradictory language about similar topics
                words1 = set(self._extract_keywords(mem1.content))
                words2 = set(self._extract_keywords(mem2.content))

                # Must have topic overlap
                if not (words1 & words2):
                    continue

                # Check for contradictory language
                mem1_lower = mem1.content.lower()
                mem2_lower = mem2.content.lower()

                for positive_words, negative_words in contradiction_pairs:
                    has_positive_1 = any(w in mem1_lower for w in positive_words)
                    has_negative_1 = any(w in mem1_lower for w in negative_words)
                    has_positive_2 = any(w in mem2_lower for w in positive_words)
                    has_negative_2 = any(w in mem2_lower for w in negative_words)

                    # Contradiction if opposite patterns
                    if (has_positive_1 and has_negative_2) or (has_negative_1 and has_positive_2):
                        connections.append(Connection(
                            memory_ids=[mem1.id, mem2.id],
                            connection_type='contradiction',
                            strength=0.8,
                            evidence=f"Contradictory stances on: {', '.join(list(words1 & words2)[:3])}",
                            insight=f"Context difference between {mem1.project} and {mem2.project}?"
                        ))
                        break

        return connections

    def _generate_syntheses(self, connections: List[Connection], memories: List[MemoryNode]) -> List[Synthesis]:
        """Generate higher-level syntheses from connections"""
        syntheses = []

        # Group connections by type
        by_type = defaultdict(list)
        for conn in connections:
            by_type[conn.connection_type].append(conn)

        # Generate synthesis for each cluster
        for conn_type, conns in by_type.items():
            if len(conns) < self.MIN_SUPPORT:
                continue

            # Collect all involved memories
            memory_ids = set()
            for conn in conns:
                memory_ids.update(conn.memory_ids)

            memory_map = {m.id: m for m in memories if m.id in memory_ids}
            projects = set(m.project for m in memory_map.values())

            # Generate insight based on connection type
            if conn_type == 'semantic':
                insight = f"Found {len(conns)} semantic parallels across {len(projects)} projects"
                title = "Cross-project pattern detection"
            elif conn_type == 'temporal':
                insight = f"{len(conns)} themes emerged simultaneously across projects"
                title = "Synchronized evolution"
            elif conn_type == 'causal':
                insight = f"Detected {len(conns)} causal chains spanning projects"
                title = "Cascading effects"
            elif conn_type == 'contradiction':
                insight = f"{len(conns)} apparent contradictions need context resolution"
                title = "Context-dependent patterns"
            else:
                continue

            # Calculate novelty (how non-obvious?)
            # Higher novelty for cross-project, low keyword overlap
            avg_strength = sum(c.strength for c in conns) / len(conns)
            project_diversity = len(projects) / max(1, len(memory_ids))
            novelty = (1 - avg_strength) * 0.5 + project_diversity * 0.5

            # Confidence based on number of supporting connections
            confidence = min(1.0, len(conns) / 10)

            synthesis = Synthesis(
                id=f"syn_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{conn_type}",
                title=title,
                insight=insight,
                supporting_memories=list(memory_ids),
                connections=conns,
                novelty_score=novelty,
                confidence=confidence,
                projects_spanned=list(projects),
                created_at=datetime.now()
            )

            syntheses.append(synthesis)
            self._save_synthesis(synthesis)

        return syntheses

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text"""
        # Remove common stop words
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during',
            'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has', 'had', 'do',
            'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
            'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how'
        }

        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        return [w for w in words if w not in stop_words]

    def get_morning_briefing(self, limit: int = 5) -> List[Synthesis]:
        """Get top syntheses for morning review"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT s.id, s.title, s.insight, s.supporting_memories,
                       s.connection_ids, s.novelty_score, s.confidence,
                       s.projects_spanned, s.created_at
                FROM synthesis_queue q
                JOIN dream_syntheses s ON q.synthesis_id = s.id
                WHERE q.presented = 0
                ORDER BY q.priority DESC
                LIMIT ?
            """, (limit,)).fetchall()

        import json

        return [
            Synthesis(
                id=r[0], title=r[1], insight=r[2],
                supporting_memories=json.loads(r[3]),
                connections=[],  # Would load if needed
                novelty_score=r[5],
                confidence=r[6],
                projects_spanned=json.loads(r[7]),
                created_at=datetime.fromisoformat(r[8])
            )
            for r in rows
        ]

    def mark_presented(self, synthesis_id: str):
        """Mark synthesis as presented to user"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE synthesis_queue
                SET presented = 1, presented_at = ?
                WHERE synthesis_id = ?
            """, (datetime.now().isoformat(), synthesis_id))

    def _save_connection(self, connection: Connection):
        """Save connection to database"""
        import json

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO dream_connections
                (memory_ids, connection_type, strength, evidence, insight, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                json.dumps(connection.memory_ids),
                connection.connection_type,
                connection.strength,
                connection.evidence,
                connection.insight,
                datetime.now().isoformat()
            ))

    def _save_synthesis(self, synthesis: Synthesis):
        """Save synthesis to database"""
        import json

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO dream_syntheses
                (id, title, insight, supporting_memories, connection_ids,
                 novelty_score, confidence, projects_spanned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                synthesis.id, synthesis.title, synthesis.insight,
                json.dumps(synthesis.supporting_memories),
                json.dumps([]),  # Would save connection IDs
                synthesis.novelty_score,
                synthesis.confidence,
                json.dumps(synthesis.projects_spanned),
                synthesis.created_at.isoformat()
            ))

    def _queue_synthesis(self, synthesis: Synthesis):
        """Add synthesis to morning review queue"""
        priority = synthesis.novelty_score * synthesis.confidence

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO synthesis_queue
                (synthesis_id, priority, queued_at)
                VALUES (?, ?, ?)
            """, (synthesis.id, priority, datetime.now().isoformat()))
