"""
Features 38-42: Third-party integrations

38. Obsidian sync (bidirectional markdown)
39. Notion integration (database sync)
40. Roam integration (daily notes + graph)
41. Email intelligence v2 (pattern learning)
42. Meeting intelligence (transcripts.db integration)
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from memory_system.wild.intelligence_db import IntelligenceDB
from memory_system.memory_ts_client import MemoryTSClient, Memory

# Feature 42: Meeting intelligence
TRANSCRIPTS_DB = Path.home() / "CC/LFI/_ Operations/meeting-intelligence/transcripts.db"


# ============================================================================
# Feature 38: Obsidian sync
# ============================================================================

def export_to_obsidian(vault_path: Path, memories: Optional[List[Memory]] = None,
                      memory_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> int:
    """
    Export memories to Obsidian vault as markdown files

    Args:
        vault_path: Path to Obsidian vault
        memories: Optional list of memories (if None, exports all)
        memory_dir: Optional memory-ts path
        db_path: Optional database path

    Returns:
        Number of files exported
    """
    if not vault_path.exists():
        raise ValueError(f"Obsidian vault not found: {vault_path}")

    client = MemoryTSClient(memory_dir)
    memories_to_export = memories or client.search()

    count = 0
    for mem in memories_to_export:
        # Create markdown file
        filename = f"{mem.id}.md"
        filepath = vault_path / "Memories" / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Format content
        content = f"# {mem.content[:50]}\n\n"
        content += f"{mem.content}\n\n"
        content += f"---\n"
        content += f"Tags: {' '.join(['#' + t for t in mem.tags])}\n"
        content += f"Importance: {mem.importance}\n"
        content += f"Project: [[{mem.project_id}]]\n"
        content += f"Created: {mem.created}\n"

        filepath.write_text(content)

        # Track sync state
        with IntelligenceDB(db_path) as db:
            db.conn.execute("""
                INSERT OR REPLACE INTO obsidian_sync_state
                (memory_id, obsidian_file_path, last_sync_at, sync_direction, checksum)
                VALUES (?, ?, ?, ?, ?)
            """, (mem.id, str(filepath), datetime.now().isoformat(), 'to_obsidian',
                  _checksum(content)))
            db.conn.commit()

        count += 1

    return count


def import_from_obsidian(vault_path: Path, memory_dir: Optional[Path] = None,
                        db_path: Optional[Path] = None) -> int:
    """
    Import Obsidian notes as memories

    Args:
        vault_path: Path to Obsidian vault
        memory_dir: Optional memory-ts path
        db_path: Optional database path

    Returns:
        Number of memories imported
    """
    memories_folder = vault_path / "Memories"
    if not memories_folder.exists():
        return 0

    client = MemoryTSClient(memory_dir)
    count = 0

    for filepath in memories_folder.glob("*.md"):
        content = filepath.read_text()

        # Parse frontmatter (simple implementation)
        lines = content.split('\n')
        tags = []
        importance = 0.5
        project_id = "imported"

        for line in lines:
            if line.startswith('Tags:'):
                tags = [t.strip('#') for t in line.split()[1:]]
            elif line.startswith('Importance:'):
                importance = float(line.split()[1])
            elif line.startswith('Project:'):
                project_id = line.split('[[')[1].split(']]')[0] if '[[' in line else "imported"

        # Extract main content (everything before ---)
        main_content = content.split('---')[0].strip()

        # Create memory
        mem = client.create(
            content=main_content,
            project_id=project_id,
            tags=tags,
            importance=importance
        )

        # Track sync
        with IntelligenceDB(db_path) as db:
            db.conn.execute("""
                INSERT OR REPLACE INTO obsidian_sync_state
                (memory_id, obsidian_file_path, last_sync_at, sync_direction, checksum)
                VALUES (?, ?, ?, ?, ?)
            """, (mem.id, str(filepath), datetime.now().isoformat(), 'from_obsidian',
                  _checksum(content)))
            db.conn.commit()

        count += 1

    return count


# ============================================================================
# Feature 39: Notion integration
# ============================================================================

def export_to_notion(database_id: str, memories: Optional[List[Memory]] = None,
                    memory_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> List[Dict]:
    """
    Export memories to Notion database (returns JSON for Notion API)

    Args:
        database_id: Notion database ID
        memories: Optional list of memories
        memory_dir: Optional memory-ts path
        db_path: Optional database path

    Returns:
        List of Notion-formatted page objects
    """
    client = MemoryTSClient(memory_dir)
    memories_to_export = memories or client.search()

    notion_pages = []
    for mem in memories_to_export:
        page = {
            'parent': {'database_id': database_id},
            'properties': {
                'Name': {'title': [{'text': {'content': mem.content[:100]}}]},
                'Content': {'rich_text': [{'text': {'content': mem.content}}]},
                'Importance': {'number': mem.importance},
                'Tags': {'multi_select': [{'name': t} for t in mem.tags]},
                'Project': {'rich_text': [{'text': {'content': mem.project_id}}]},
                'Created': {'date': {'start': mem.created}}
            }
        }
        notion_pages.append(page)

        # Track sync (would need actual Notion page ID from API response)
        with IntelligenceDB(db_path) as db:
            db.conn.execute("""
                INSERT OR REPLACE INTO notion_sync_state
                (memory_id, notion_page_id, notion_database_id, last_sync_at, sync_status)
                VALUES (?, ?, ?, ?, ?)
            """, (mem.id, 'pending', database_id, datetime.now().isoformat(), 'pending'))
            db.conn.commit()

    return notion_pages


# ============================================================================
# Feature 40: Roam Research integration
# ============================================================================

def export_to_roam(memories: Optional[List[Memory]] = None,
                  memory_dir: Optional[Path] = None) -> str:
    """
    Export memories as Roam Research daily notes format

    Args:
        memories: Optional list of memories
        memory_dir: Optional memory-ts path

    Returns:
        Roam-formatted markdown string
    """
    client = MemoryTSClient(memory_dir)
    memories_to_export = memories or client.search()

    # Group by date
    by_date = {}
    for mem in memories_to_export:
        date = mem.created[:10]  # YYYY-MM-DD
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(mem)

    # Format as Roam daily notes
    lines = []
    for date, mems in sorted(by_date.items()):
        lines.append(f"## {date}")
        for mem in mems:
            lines.append(f"- {mem.content} #memory #{mem.project_id}")
            lines.append(f"  - Importance:: {mem.importance}")
            lines.append(f"  - Tags:: {', '.join(['#' + t for t in mem.tags])}")

    return '\n'.join(lines)


# ============================================================================
# Feature 41: Email intelligence v2
# ============================================================================

def learn_email_pattern(correction_type: str, pattern_rule: str,
                       confidence: float = 0.8, db_path: Optional[Path] = None) -> int:
    """
    Learn email categorization pattern from user correction

    Args:
        correction_type: 'categorization' | 'threading' | 'priority'
        pattern_rule: The learned rule (e.g., "from:client@x.com → Important")
        confidence: Initial confidence score
        db_path: Optional database path

    Returns:
        Pattern ID
    """
    with IntelligenceDB(db_path) as db:
        return db.add_email_pattern(correction_type, pattern_rule, confidence)


def get_email_recommendations(email_content: str, db_path: Optional[Path] = None) -> Dict:
    """
    Get email handling recommendations based on learned patterns

    Args:
        email_content: Email content to analyze
        db_path: Optional database path

    Returns:
        Dict with recommendations
    """
    with IntelligenceDB(db_path) as db:
        patterns = db.get_email_patterns()

    recommendations = {
        'category': None,
        'priority': None,
        'thread_with': None,
        'confidence': 0.0
    }

    # Simple pattern matching (would use LLM in production)
    for pattern in patterns:
        if pattern['pattern_rule'] in email_content.lower():
            if pattern['pattern_type'] == 'categorization':
                recommendations['category'] = pattern['pattern_rule']
                recommendations['confidence'] = pattern['confidence']

    return recommendations


# ============================================================================
# Feature 42: Meeting intelligence
# ============================================================================

def link_memory_to_meeting(memory_id: str, meeting_title: str,
                          db_path: Optional[Path] = None,
                          transcripts_db: Path = TRANSCRIPTS_DB) -> Optional[int]:
    """
    Link a memory to a meeting transcript

    Args:
        memory_id: Memory ID
        meeting_title: Meeting title to search for
        db_path: Optional intelligence database path
        transcripts_db: Path to transcripts.db

    Returns:
        Link ID if successful
    """
    if not transcripts_db.exists():
        raise FileNotFoundError(f"Transcripts database not found: {transcripts_db}")

    # Query transcripts database
    conn = sqlite3.connect(str(transcripts_db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, meeting_date, participants
        FROM meetings
        WHERE title LIKE ?
        LIMIT 1
    """, (f"%{meeting_title}%",))

    meeting = cursor.fetchone()
    conn.close()

    if not meeting:
        return None

    # Create link
    with IntelligenceDB(db_path) as db:
        return db.link_memory_to_meeting(
            memory_id=memory_id,
            meeting_id=str(meeting['id']),
            meeting_date=meeting['meeting_date'],
            participants=meeting['participants'],
            relevance_score=0.8
        )


def extract_memories_from_meeting(meeting_id: int, transcripts_db: Path = TRANSCRIPTS_DB,
                                 memory_dir: Optional[Path] = None,
                                 db_path: Optional[Path] = None) -> List[Memory]:
    """
    Extract memories from a meeting transcript

    Args:
        meeting_id: Meeting ID in transcripts.db
        transcripts_db: Path to transcripts database
        memory_dir: Optional memory-ts path
        db_path: Optional intelligence database path

    Returns:
        List of created memories
    """
    if not transcripts_db.exists():
        raise FileNotFoundError(f"Transcripts database not found: {transcripts_db}")

    # Get transcript
    conn = sqlite3.connect(str(transcripts_db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT title, content, meeting_date, participants
        FROM meetings
        WHERE id = ?
    """, (meeting_id,))

    meeting = cursor.fetchone()
    conn.close()

    if not meeting:
        return []

    # Extract insights (simple keyword extraction, would use LLM in production)
    content = meeting['content'] or ""
    insights = _extract_meeting_insights(content)

    # Create memories
    client = MemoryTSClient(memory_dir)
    created_memories = []

    for insight in insights:
        mem = client.create(
            content=insight['content'],
            project_id="meetings",
            tags=['meeting', meeting['title']],
            importance=insight['importance']
        )

        # Link to meeting
        with IntelligenceDB(db_path) as db:
            db.link_memory_to_meeting(
                memory_id=mem.id,
                meeting_id=str(meeting_id),
                meeting_date=meeting['meeting_date'],
                participants=meeting['participants']
            )

        created_memories.append(mem)

    return created_memories


def _extract_meeting_insights(transcript: str) -> List[Dict]:
    """Extract key insights from meeting transcript"""
    # Simple implementation: look for decision/action phrases
    insights = []
    decision_phrases = ['decided to', 'agreed to', 'will do', 'action item', 'next step']

    for phrase in decision_phrases:
        if phrase in transcript.lower():
            # Extract sentence containing phrase (simplified)
            sentences = transcript.split('.')
            for sent in sentences:
                if phrase in sent.lower():
                    insights.append({
                        'content': sent.strip(),
                        'importance': 0.7
                    })

    return insights[:10]  # Limit to 10 insights


def _checksum(content: str) -> str:
    """Generate checksum for content"""
    import hashlib
    return hashlib.md5(content.encode()).hexdigest()
