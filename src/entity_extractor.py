"""
Entity extraction and linking system (Spec 18).

Extracts persons, tools, and projects from memory text.
Links entities to memory IDs via a junction table.
Supports aliases and case-insensitive lookups.

No LLM calls — pure regex / pattern matching.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Known entity patterns
# ---------------------------------------------------------------------------

TOOL_PATTERNS: List[str] = [
    "Python", "JavaScript", "React", "Webflow", "Claude", "FAISS",
    "SQLite", "Flask", "Notion", "Todoist", "Gmail", "Slack",
    "TypeScript", "Node", "Next.js", "Vue", "Angular", "Django",
    "FastAPI", "PostgreSQL", "Redis", "Docker", "Git", "GitHub",
    "VS Code", "Cursor", "Vercel", "Supabase", "Stripe",
]

PROJECT_PATTERNS: List[str] = [
    "Connection Lab", "Cogent Analytics", "ZeroArc", "Imply",
    "PowerTrack", "Total Rekall", "LFI",
]

# Words that commonly start sentences but are not person names.
_COMMON_WORDS = {
    "the", "a", "an", "this", "that", "these", "those", "it", "its",
    "my", "our", "your", "his", "her", "their", "we", "he", "she",
    "they", "i", "you", "me", "us", "and", "or", "but", "if", "so",
    "then", "very", "also", "just", "not", "no", "yes", "all", "any",
    "each", "every", "some", "many", "much", "more", "most", "few",
    "new", "old", "big", "good", "bad", "first", "last", "long",
    "great", "little", "own", "other", "right", "high", "low",
    "next", "same", "able", "used", "using", "after", "before",
    "when", "where", "how", "what", "which", "who", "whom", "why",
    "here", "there", "now", "only", "well", "back", "even", "still",
    "see", "get", "set", "run", "let", "try", "keep", "make",
    "take", "come", "go", "work", "need", "want", "look", "use",
    "find", "give", "tell", "may", "will", "can", "should", "would",
    "could", "shall", "must", "has", "had", "have", "was", "were",
    "been", "being", "do", "does", "did", "done", "for", "from",
    "with", "about", "into", "over", "between", "through", "during",
    "without", "within", "along", "across", "behind", "beyond",
    "above", "below", "upon", "under", "around", "among",
    "however", "therefore", "meanwhile", "instead", "otherwise",
    "assigned", "discussed", "talked", "built", "created", "added",
    "updated", "fixed", "moved", "note", "notes", "meeting",
    "project", "today", "yesterday", "tomorrow", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december",
    "memory", "session", "task", "feature", "sprint", "review",
}

# Build case-insensitive lookup sets for fast matching
_TOOL_LOWER = {t.lower(): t for t in TOOL_PATTERNS}
_PROJECT_LOWER = {p.lower(): p for p in PROJECT_PATTERNS}

# Pre-compile regexes
_RE_AT_MENTION = re.compile(r"@(\w+)")
_RE_PROPER_NOUN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
)


class EntityExtractor:
    """
    Extract and link named entities from memory text.

    Stores entities in SQLite with a junction table to memory IDs.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(
                Path.home() / ".local/share/memory" / "entities.db"
            )
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        cur = self.conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                type TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS memory_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                mention_text TEXT,
                position INTEGER,
                UNIQUE(memory_id, entity_id),
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )
        """)

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_me_memory "
            "ON memory_entities(memory_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_me_entity "
            "ON memory_entities(entity_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type "
            "ON entities(type)"
        )

        self.conn.commit()

    # ------------------------------------------------------------------
    # Extraction (pure, no DB side-effects)
    # ------------------------------------------------------------------

    def extract_entities(self, text: str) -> List[Dict]:
        """
        Extract entities from *text*.

        Returns a list of dicts, each with keys:
            name, type, mention_text, position
        """
        if not text:
            return []

        results: List[Dict] = []
        seen_spans: List[tuple] = []  # (start, end) to avoid overlaps

        def _overlaps(start: int, end: int) -> bool:
            for s, e in seen_spans:
                if start < e and end > s:
                    return True
            return False

        def _add(name: str, etype: str, mention: str, pos: int) -> None:
            end = pos + len(mention)
            if not _overlaps(pos, end):
                results.append({
                    "name": name,
                    "type": etype,
                    "mention_text": mention,
                    "position": pos,
                })
                seen_spans.append((pos, end))

        # 1. Projects (multi-word, match first to avoid partial person matches)
        for proj in PROJECT_PATTERNS:
            pattern = re.compile(re.escape(proj), re.IGNORECASE)
            for m in pattern.finditer(text):
                _add(proj, "project", m.group(), m.start())

        # 2. Tools (word-boundary, case-insensitive)
        for tool in TOOL_PATTERNS:
            pattern = re.compile(
                r"\b" + re.escape(tool) + r"\b", re.IGNORECASE
            )
            for m in pattern.finditer(text):
                _add(tool, "tool", m.group(), m.start())

        # 3. @mentions -> person
        for m in _RE_AT_MENTION.finditer(text):
            _add(m.group(1), "person", m.group(), m.start())

        # 4. Proper nouns (two+ capitalized words) -> person
        for m in _RE_PROPER_NOUN.finditer(text):
            candidate = m.group()
            # Skip if any word is a common English word
            words = candidate.split()
            if any(w.lower() in _COMMON_WORDS for w in words):
                continue
            # Skip if already captured as tool or project
            if not _overlaps(m.start(), m.end()):
                _add(candidate, "person", candidate, m.start())

        # Sort by position for deterministic output
        results.sort(key=lambda e: e["position"])
        return results

    # ------------------------------------------------------------------
    # Linking
    # ------------------------------------------------------------------

    def link_memory(self, memory_id: str, content: str) -> int:
        """
        Extract entities from *content* and link them to *memory_id*.

        Returns the number of distinct entities linked.
        """
        entities = self.extract_entities(content)
        if not entities:
            return 0

        now = datetime.now().isoformat()
        linked = 0

        for ent in entities:
            # Upsert entity
            entity_id = self._upsert_entity(
                ent["name"], ent["type"], now
            )

            # Insert junction (ignore duplicate)
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO memory_entities "
                    "(memory_id, entity_id, mention_text, position) "
                    "VALUES (?, ?, ?, ?)",
                    (memory_id, entity_id, ent["mention_text"], ent["position"]),
                )
                linked += 1
            except sqlite3.IntegrityError:
                pass

        self.conn.commit()
        return linked

    def _upsert_entity(self, name: str, etype: str, now: str) -> int:
        """Insert or update entity, return its id."""
        cur = self.conn.cursor()

        # Try insert
        try:
            cur.execute(
                "INSERT INTO entities (name, type, aliases_json, first_seen, last_seen) "
                "VALUES (?, ?, '[]', ?, ?)",
                (name, etype, now, now),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Already exists — update last_seen
            cur.execute(
                "UPDATE entities SET last_seen = ? WHERE name = ? COLLATE NOCASE",
                (now, name),
            )
            row = cur.execute(
                "SELECT id FROM entities WHERE name = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            return row["id"]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_memories_by_entity(self, name: str) -> List[str]:
        """
        Return memory IDs linked to entity *name* (case-insensitive).

        Also searches aliases.
        """
        cur = self.conn.cursor()

        # Direct name match
        row = cur.execute(
            "SELECT id, aliases_json FROM entities WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()

        # If not found by name, search aliases
        if row is None:
            rows = cur.execute(
                "SELECT id, aliases_json FROM entities"
            ).fetchall()
            for r in rows:
                aliases = json.loads(r["aliases_json"])
                if any(a.lower() == name.lower() for a in aliases):
                    row = r
                    break

        if row is None:
            return []

        entity_id = row["id"]
        links = cur.execute(
            "SELECT DISTINCT memory_id FROM memory_entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()

        return [lnk["memory_id"] for lnk in links]

    def add_alias(self, entity_name: str, alias: str) -> bool:
        """
        Add *alias* to entity identified by *entity_name*.

        Returns True on success, False if entity not found.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT id, aliases_json FROM entities WHERE name = ? COLLATE NOCASE",
            (entity_name,),
        ).fetchone()

        if row is None:
            return False

        aliases = json.loads(row["aliases_json"])
        if alias not in aliases:
            aliases.append(alias)
            cur.execute(
                "UPDATE entities SET aliases_json = ? WHERE id = ?",
                (json.dumps(aliases), row["id"]),
            )
            self.conn.commit()
        return True

    def get_entity(self, name: str) -> Optional[Dict]:
        """
        Return entity dict or None.

        Case-insensitive lookup by name.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "aliases": json.loads(row["aliases_json"]),
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
        }

    def get_all_entities(self) -> List[Dict]:
        """Return all entities as list of dicts."""
        cur = self.conn.cursor()
        rows = cur.execute("SELECT * FROM entities ORDER BY name").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "aliases": json.loads(r["aliases_json"]),
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            }
            for r in rows
        ]

    def get_stats(self) -> Dict:
        """
        Return summary statistics.

        Keys: total_entities, total_links, by_type
        """
        cur = self.conn.cursor()

        total_entities = cur.execute(
            "SELECT COUNT(*) FROM entities"
        ).fetchone()[0]

        total_links = cur.execute(
            "SELECT COUNT(*) FROM memory_entities"
        ).fetchone()[0]

        type_rows = cur.execute(
            "SELECT type, COUNT(*) as cnt FROM entities GROUP BY type"
        ).fetchall()

        by_type = {r["type"]: r["cnt"] for r in type_rows}

        return {
            "total_entities": total_entities,
            "total_links": total_links,
            "by_type": by_type,
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
