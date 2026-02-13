"""F59: Expertise Mapping

Maps which agents have expertise in which domains for optimal routing.

Usage:
    from wild.expertise_mapper import ExpertiseMapper

    mapper = ExpertiseMapper()

    # Update expertise map (usually done automatically)
    mapper.update_expertise_map()

    # Get expert for domain
    expert = mapper.get_expert_for_domain("python")

    # Get full expertise map
    expertise = mapper.map_expertise()
"""

import json
import sqlite3
import time
import uuid
from typing import Dict, List, Optional

from .intelligence_db import IntelligenceDB


class ExpertiseMapper:
    """Maps agent expertise by domain"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize expertise mapper

        Args:
            db_path: Optional path to intelligence.db (for testing)
        """
        self.db = IntelligenceDB(db_path)

    def record_expertise(
        self,
        agent_name: str,
        domain: str,
        memory_count: int = 1,
        quality: float = 3.0
    ):
        """Record or update agent expertise in domain

        Args:
            agent_name: Agent name
            domain: Domain/topic
            memory_count: Number of memories
            quality: Average quality (A=4, B=3, C=2, D=1)
        """
        timestamp = int(time.time())

        # Check if exists
        existing = self.db.conn.execute(
            """
            SELECT id, memory_count, avg_quality
            FROM agent_expertise
            WHERE agent_name = ? AND domain = ?
            """,
            (agent_name, domain)
        ).fetchone()

        if existing:
            # Update existing
            new_count = existing["memory_count"] + memory_count
            # Weighted average of quality
            new_quality = (
                (existing["avg_quality"] * existing["memory_count"] + quality * memory_count)
                / new_count
            )

            self.db.conn.execute(
                """
                UPDATE agent_expertise
                SET memory_count = ?, avg_quality = ?, last_updated = ?
                WHERE id = ?
                """,
                (new_count, new_quality, timestamp, existing["id"])
            )
        else:
            # Create new
            expertise_id = str(uuid.uuid4())
            self.db.conn.execute(
                """
                INSERT INTO agent_expertise
                (id, agent_name, domain, memory_count, avg_quality, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (expertise_id, agent_name, domain, memory_count, quality, timestamp)
            )

        self.db.conn.commit()

    def get_expert_for_domain(self, domain: str) -> Optional[str]:
        """Get best expert for a domain

        Args:
            domain: Domain/topic

        Returns:
            Agent name or None
        """
        # Score = memory_count * avg_quality
        row = self.db.conn.execute(
            """
            SELECT agent_name, (memory_count * avg_quality) as score
            FROM agent_expertise
            WHERE domain LIKE ?
            ORDER BY score DESC
            LIMIT 1
            """,
            (f"%{domain}%",)
        ).fetchone()

        if row:
            return row["agent_name"]

        return None

    def map_expertise(self) -> Dict[str, List[str]]:
        """Get full expertise map

        Returns:
            Dict mapping agent_name -> [domains]
        """
        rows = self.db.conn.execute(
            """
            SELECT agent_name, domain
            FROM agent_expertise
            ORDER BY agent_name, (memory_count * avg_quality) DESC
            """
        ).fetchall()

        expertise_map = {}
        for row in rows:
            agent = row["agent_name"]
            domain = row["domain"]

            if agent not in expertise_map:
                expertise_map[agent] = []

            expertise_map[agent].append(domain)

        return expertise_map

    def get_agent_expertise(self, agent_name: str) -> List[Dict]:
        """Get expertise for specific agent

        Args:
            agent_name: Agent name

        Returns:
            List of domain expertise records
        """
        rows = self.db.conn.execute(
            """
            SELECT domain, memory_count, avg_quality
            FROM agent_expertise
            WHERE agent_name = ?
            ORDER BY (memory_count * avg_quality) DESC
            """,
            (agent_name,)
        ).fetchall()

        return [
            {
                "domain": row["domain"],
                "memory_count": row["memory_count"],
                "avg_quality": row["avg_quality"],
                "score": row["memory_count"] * row["avg_quality"]
            }
            for row in rows
        ]

    def update_expertise_map(self):
        """Update expertise map from memory data

        Note: In real implementation, would analyze memories.
        This is a stub for MVP.
        """
        # This would scan memories and extract agent/domain relationships
        # For MVP, we just ensure the table exists
        pass

    def get_statistics(self) -> Dict:
        """Get expertise statistics

        Returns:
            Dict with statistics
        """
        # Total agents
        agents = self.db.conn.execute(
            "SELECT COUNT(DISTINCT agent_name) as count FROM agent_expertise"
        ).fetchone()

        # Total domains
        domains = self.db.conn.execute(
            "SELECT COUNT(DISTINCT domain) as count FROM agent_expertise"
        ).fetchone()

        # Total expertise records
        total = self.db.conn.execute(
            "SELECT COUNT(*) as count FROM agent_expertise"
        ).fetchone()

        return {
            "total_agents": agents["count"],
            "total_domains": domains["count"],
            "total_expertise_records": total["count"]
        }
