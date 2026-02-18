"""
Cross-client pattern synthesizer — identify transferable patterns across
projects and generate cross-client hypotheses.

Builds on existing infrastructure:
  - pattern_transfer.py (F56): PatternTransferer, pattern_transfers table
  - cross_project_sharing.py (F27): tag_as_universal, get_universal_memories
  - Memory model: project_id, scope (project/global), semantic_tags

The synthesizer reads memories that are eligible for cross-project sharing
(scope=global, or tagged #cross_client_ok / #universal), groups them by
knowledge domain, and identifies patterns that could transfer between projects.

Usage:
    from memory_system.cross_client_synthesizer import CrossClientSynthesizer

    synth = CrossClientSynthesizer()
    report = synth.synthesize()
    print(synth.get_formatted_report())
"""

import json
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MEMORY_DIR = Path.home() / ".local/share/memory/LFI/memories"
INTELLIGENCE_DB = Path(__file__).parent.parent / "intelligence.db"

# Tags that mark a memory as eligible for cross-project sharing
CONSENT_TAGS = {"#cross_client_ok", "#universal", "cross_client_ok", "universal"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class TransferHypothesis:
    """A hypothesis about a pattern that could transfer between projects."""
    source_project: str
    target_project: str
    pattern: str
    confidence: float
    domain: str
    supporting_memories: list[str]

    def to_dict(self) -> dict:
        return {
            "source_project": self.source_project,
            "target_project": self.target_project,
            "pattern": self.pattern,
            "confidence": self.confidence,
            "domain": self.domain,
            "supporting_memories": self.supporting_memories,
        }


@dataclass
class CrossClientReport:
    """Complete synthesis report."""
    hypotheses: list[TransferHypothesis]
    projects_analyzed: list[str]
    total_memories_scanned: int

    @property
    def is_empty(self) -> bool:
        return len(self.hypotheses) == 0

    @property
    def hypothesis_count(self) -> int:
        return len(self.hypotheses)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def find_cross_project_memories(memory_dir: Optional[Path] = None) -> list[dict]:
    """Find memories eligible for cross-project sharing.

    Eligibility criteria (any of):
      - scope == "global"
      - tagged with #cross_client_ok or #universal

    Returns:
        List of dicts with id, project_id, domain, content, tags, scope
    """
    mem_dir = memory_dir or MEMORY_DIR
    if not mem_dir.exists():
        return []

    results = []
    for fpath in mem_dir.glob("*.md"):
        try:
            text = fpath.read_text()
            meta = _parse_frontmatter(text)
            if not meta:
                continue

            scope = meta.get("scope", "project")
            tags = meta.get("semantic_tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, ValueError):
                    tags = [t.strip() for t in tags.split(",")]

            # Check eligibility
            is_global = scope == "global"
            has_consent_tag = bool(set(tags) & CONSENT_TAGS)

            if not is_global and not has_consent_tag:
                continue

            # Extract body content
            body = _extract_body(text)

            results.append({
                "id": meta.get("id", fpath.stem),
                "project_id": meta.get("project_id", "unknown"),
                "domain": meta.get("knowledge_domain", "general"),
                "content": body,
                "tags": tags,
                "scope": scope,
                "importance": float(meta.get("importance_weight", 0.5)),
            })
        except Exception:
            continue

    return results


def group_by_domain(memories: list[dict]) -> dict[str, list[dict]]:
    """Group memories by knowledge domain.

    Returns:
        Dict mapping domain name to list of memories in that domain.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in memories:
        groups[m.get("domain", "general")].append(m)
    return dict(groups)


def generate_hypotheses(
    memories: list[dict],
    max_hypotheses: int = 10,
    db_path: Optional[Path] = None,
) -> list[TransferHypothesis]:
    """Generate transfer hypotheses from cross-project memories.

    For each domain that has memories from multiple projects, generates
    hypotheses about patterns that could transfer. Uses prior transfer
    effectiveness data to boost confidence when available.

    Args:
        memories: List of eligible memories (from find_cross_project_memories)
        max_hypotheses: Maximum number of hypotheses to generate
        db_path: Path to intelligence.db for prior transfer data

    Returns:
        List of TransferHypothesis sorted by confidence descending
    """
    if not memories:
        return []

    # Load prior transfer effectiveness
    prior_effectiveness = _load_prior_effectiveness(db_path)

    groups = group_by_domain(memories)
    hypotheses = []

    for domain, domain_memories in groups.items():
        # Group by project within this domain
        by_project: dict[str, list[dict]] = defaultdict(list)
        for m in domain_memories:
            by_project[m["project_id"]].append(m)

        projects = list(by_project.keys())
        if len(projects) < 2:
            continue

        # For each pair of projects, generate a hypothesis
        for i, source_proj in enumerate(projects):
            for target_proj in projects[i + 1:]:
                source_memories = by_project[source_proj]
                target_memories = by_project[target_proj]

                # Pick the highest-importance source memory as the pattern
                source_memories_sorted = sorted(
                    source_memories, key=lambda m: m["importance"], reverse=True
                )
                pattern_memory = source_memories_sorted[0]
                pattern_text = pattern_memory["content"][:200].strip()

                # Base confidence from importance
                confidence = min(pattern_memory["importance"], 0.9)

                # Boost from prior successful transfers
                boost = prior_effectiveness.get(source_proj, 0.0)
                if boost > 0:
                    confidence = min(confidence + boost * 0.2, 0.95)

                supporting = (
                    [m["id"] for m in source_memories[:3]] +
                    [m["id"] for m in target_memories[:2]]
                )

                hypotheses.append(TransferHypothesis(
                    source_project=source_proj,
                    target_project=target_proj,
                    pattern=pattern_text,
                    confidence=round(confidence, 2),
                    domain=domain,
                    supporting_memories=supporting,
                ))

    # Sort by confidence descending, limit
    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return hypotheses[:max_hypotheses]


def format_synthesis_report(report: CrossClientReport) -> str:
    """Format a CrossClientReport as human-readable text.

    Args:
        report: The report to format

    Returns:
        Formatted string suitable for terminal or notification
    """
    if report.is_empty:
        return "No cross-client patterns found. Add more global-scope memories to enable synthesis."

    lines = [f"Cross-client pattern synthesis ({report.hypothesis_count} hypotheses):"]
    lines.append(f"  Scanned {report.total_memories_scanned} memories across {len(report.projects_analyzed)} projects")
    lines.append("")

    for i, h in enumerate(report.hypotheses, 1):
        lines.append(f"  {i}. [{h.domain}] {h.source_project} -> {h.target_project} (confidence: {h.confidence})")
        lines.append(f"     Pattern: {h.pattern[:120]}")
        lines.append(f"     Supporting: {len(h.supporting_memories)} memories")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> Optional[dict]:
    """Parse YAML-like frontmatter from a memory .md file."""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            meta[key] = value

    return meta


def _extract_body(text: str) -> str:
    """Extract body content after frontmatter."""
    parts = text.split("---", 2)
    if len(parts) >= 3:
        return parts[2].strip()
    return text.strip()


def _load_prior_effectiveness(db_path: Optional[Path] = None) -> dict[str, float]:
    """Load average effectiveness ratings from prior pattern transfers.

    Returns:
        Dict mapping project name to average effectiveness (0.0-1.0)
    """
    db = db_path or INTELLIGENCE_DB
    if not Path(db).exists():
        return {}

    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            """
            SELECT from_project, AVG(effectiveness_rating) as avg_rating
            FROM pattern_transfers
            WHERE effectiveness_rating IS NOT NULL
            GROUP BY from_project
            """
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main interface class
# ---------------------------------------------------------------------------

class CrossClientSynthesizer:
    """Main interface for cross-client pattern synthesis."""

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.db_path = db_path or INTELLIGENCE_DB

    def synthesize(
        self,
        max_hypotheses: int = 10,
        record: bool = False,
    ) -> CrossClientReport:
        """Run cross-client synthesis.

        Args:
            max_hypotheses: Maximum hypotheses to generate
            record: Whether to record hypotheses as pattern transfers in DB

        Returns:
            CrossClientReport with hypotheses
        """
        memories = find_cross_project_memories(self.memory_dir)
        hypotheses = generate_hypotheses(
            memories,
            max_hypotheses=max_hypotheses,
            db_path=self.db_path,
        )

        projects = list(set(m["project_id"] for m in memories))

        report = CrossClientReport(
            hypotheses=hypotheses,
            projects_analyzed=projects,
            total_memories_scanned=len(memories),
        )

        if record and hypotheses:
            self._record_hypotheses(hypotheses)

        return report

    def get_formatted_report(self, max_hypotheses: int = 10) -> str:
        """Get human-readable synthesis report."""
        report = self.synthesize(max_hypotheses=max_hypotheses)
        return format_synthesis_report(report)

    def _record_hypotheses(self, hypotheses: list[TransferHypothesis]) -> None:
        """Record hypotheses as pattern transfers in intelligence.db."""
        if not Path(self.db_path).exists():
            return

        try:
            conn = sqlite3.connect(str(self.db_path))
            now = int(time.time())
            for h in hypotheses:
                transfer_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO pattern_transfers
                    (id, from_project, to_project, pattern_description, transferred_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (transfer_id, h.source_project, h.target_project, h.pattern, now),
                )
            conn.commit()
            conn.close()
        except Exception:
            pass
