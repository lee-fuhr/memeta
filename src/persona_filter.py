"""
Persona-aware memory filtering.

Groups projects into personas (business, technical, personal) and filters
memories so that only contextually relevant ones surface. Memories without
a persona tag are treated as universal and always included.

Usage:
    from memory_system.persona_filter import PersonaFilter

    pf = PersonaFilter()
    persona = pf.detect_persona("LFI")          # -> "business"
    relevant = pf.filter_memories(memories, "business")
"""

from typing import Dict, List, Optional

from memory_system.config import MemorySystemConfig


# ── Default persona definitions ──────────────────────────────────────────────

DEFAULT_PERSONAS: Dict[str, List[str]] = {
    "business": [
        "LFI",
        "CogentAnalytics",
        "ConnectionLab",
        "ZeroArc",
        "Imply",
        "PowerTrack",
    ],
    "technical": [
        "memory-system",
        "total-rekall",
    ],
    "personal": [
        "health",
        "family",
        "personal",
    ],
}


class PersonaFilter:
    """Filter memories by persona context."""

    def __init__(self, config: Optional[MemorySystemConfig] = None):
        """
        Initialize with optional config.

        Args:
            config: MemorySystemConfig instance (unused today but reserved
                    for future persona overrides via env vars).
        """
        self._config = config
        # Deep-copy defaults so mutations don't bleed across instances.
        self._personas: Dict[str, List[str]] = {
            name: list(projects) for name, projects in DEFAULT_PERSONAS.items()
        }

    # ── Public API ───────────────────────────────────────────────────────

    def detect_persona(self, project_id: str) -> str:
        """
        Detect which persona a project belongs to.

        Matching is case-insensitive. Returns ``'universal'`` when the
        project does not belong to any registered persona.

        Args:
            project_id: Project identifier (e.g. ``"LFI"``).

        Returns:
            Persona name or ``'universal'``.
        """
        if not project_id:
            return "universal"

        lower = project_id.lower()
        for persona_name, projects in self._personas.items():
            if lower in (p.lower() for p in projects):
                return persona_name
        return "universal"

    def filter_memories(
        self,
        memories: List[Dict],
        persona: str,
    ) -> List[Dict]:
        """
        Return memories that match *persona* or have no persona tag.

        A memory is included when:
        - It has a ``'persona'`` key equal to *persona*, OR
        - It has a ``'persona'`` key equal to ``'universal'``, OR
        - It has no ``'persona'`` key (treated as universal).

        Matching is case-insensitive.

        Args:
            memories: List of memory dicts (each should have at least
                      ``'content'``; may have ``'persona'`` and
                      ``'project_id'``).
            persona:  The persona to filter for.

        Returns:
            Filtered list (order preserved, no mutation of originals).
        """
        result: List[Dict] = []
        target = persona.lower()
        for mem in memories:
            mem_persona = mem.get("persona")
            if mem_persona is None:
                # Untagged -> universal -> always included.
                result.append(mem)
            elif mem_persona.lower() == target:
                result.append(mem)
            elif mem_persona.lower() == "universal":
                result.append(mem)
        return result

    def tag_memory(self, memory: Dict, persona: str) -> Dict:
        """
        Return a *new* dict with the ``'persona'`` field set.

        Does not mutate the original.

        Args:
            memory: Memory dict.
            persona: Persona name to assign.

        Returns:
            Shallow copy of *memory* with ``persona`` set.
        """
        tagged = dict(memory)
        tagged["persona"] = persona
        return tagged

    def get_relevant_projects(self, persona: str) -> List[str]:
        """
        Return the list of projects associated with *persona*.

        Case-insensitive lookup. Returns an empty list for unknown personas.
        """
        for name, projects in self._personas.items():
            if name.lower() == persona.lower():
                return list(projects)
        return []

    def add_persona(self, name: str, projects: List[str]) -> None:
        """
        Add or update a persona with its project list.

        Args:
            name:     Persona name (stored lowercase-normalised).
            projects: List of project identifiers.
        """
        self._personas[name] = list(projects)

    def get_all_personas(self) -> Dict[str, List[str]]:
        """
        Return a copy of the full persona registry.

        Returns:
            ``{persona_name: [project_id, ...], ...}``
        """
        return {name: list(projects) for name, projects in self._personas.items()}
