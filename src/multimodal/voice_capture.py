"""
Feature 44: Voice memory capture

Transcribe voice memos → extract insights → tag → save to memory-ts
Uses MacWhisper integration from _ Operations/macwhisper/
"""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from ..intelligence_db import IntelligenceDB
from ..llm_extractor import extract_with_llm
from ..importance_engine import calculate_importance
from ..memory_ts_client import MemoryTSClient


@dataclass
class VoiceMemory:
    """Voice memo converted to memory"""
    audio_path: Path
    transcript: str
    memories: List[Dict]
    duration_seconds: Optional[float] = None
    created_at: str = None
    project_id: str = "LFI"

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class VoiceCapture:
    """
    Voice memory capture system

    Workflow:
    1. Transcribe audio file (MacWhisper or local Whisper)
    2. Extract insights using LLM
    3. Score importance
    4. Save to memory-ts + intelligence DB
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        macwhisper_dir: Optional[Path] = None
    ):
        """
        Initialize voice capture

        Args:
            db_path: Intelligence database path
            macwhisper_dir: MacWhisper operation directory
        """
        self.db = IntelligenceDB(db_path)

        if macwhisper_dir is None:
            # Default to _ Operations/macwhisper/
            macwhisper_dir = Path(__file__).parent.parent.parent.parent / "macwhisper"
        self.macwhisper_dir = Path(macwhisper_dir)

        self.memory_client = MemoryTSClient()

    def transcribe_audio(self, audio_path: Path) -> Dict[str, any]:
        """
        Transcribe audio file using MacWhisper

        Args:
            audio_path: Path to audio file (m4a, mp3, wav, etc.)

        Returns:
            Dict with transcript and metadata

        Raises:
            FileNotFoundError: If audio file doesn't exist
            RuntimeError: If transcription fails
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Check if MacWhisper is available
        whisper_bin = self.macwhisper_dir / "whisper"

        if whisper_bin.exists():
            # Use MacWhisper binary
            try:
                result = subprocess.run(
                    [str(whisper_bin), str(audio_path), "--output-format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )

                if result.returncode != 0:
                    raise RuntimeError(f"MacWhisper failed: {result.stderr}")

                data = json.loads(result.stdout)
                return {
                    "transcript": data.get("text", ""),
                    "duration": data.get("duration", 0),
                    "language": data.get("language", "en")
                }
            except subprocess.TimeoutExpired:
                raise RuntimeError("Transcription timeout (>5 minutes)")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid MacWhisper output: {e}")
        else:
            # Fallback: Check for existing transcript file
            transcript_path = audio_path.with_suffix(".txt")
            if transcript_path.exists():
                return {
                    "transcript": transcript_path.read_text(),
                    "duration": None,
                    "language": "en"
                }
            else:
                raise RuntimeError(
                    f"MacWhisper not found at {whisper_bin} and no transcript file at {transcript_path}"
                )

    def extract_memories_from_transcript(
        self,
        transcript: str,
        project_id: str = "LFI",
        session_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Extract memories from voice transcript using LLM

        Args:
            transcript: Transcribed text
            project_id: Project scope
            session_id: Optional session ID for provenance

        Returns:
            List of extracted memories with importance scores
        """
        if not transcript or len(transcript.strip()) < 20:
            return []

        # Use LLM extractor with voice-specific prompt
        prompt = f"""Extract key insights and learnings from this voice memo transcript.

Focus on:
- Decisions made
- Problems identified
- Solutions discovered
- Action items or commitments
- Important context or observations

Transcript:
{transcript}

Return a list of distinct insights, one per line."""

        try:
            memories = extract_with_llm(
                prompt,
                project_id=project_id,
                session_id=session_id
            )

            # Score importance for each memory
            for memory in memories:
                memory['importance'] = calculate_importance(
                    memory.get('content', ''),
                    project_id=project_id
                )

            return memories

        except Exception as e:
            # Fallback: Simple sentence extraction
            sentences = [s.strip() for s in transcript.split('.') if len(s.strip()) > 30]
            return [
                {
                    'content': sentence + '.',
                    'importance': 0.5,
                    'tags': ['#voice-memo'],
                    'project_id': project_id
                }
                for sentence in sentences[:5]  # Top 5 sentences
            ]

    def process_voice_memo(
        self,
        audio_path: Path,
        project_id: str = "LFI",
        session_id: Optional[str] = None,
        save_to_memory_ts: bool = True
    ) -> VoiceMemory:
        """
        Complete voice memo processing pipeline

        Args:
            audio_path: Path to audio file
            project_id: Project scope
            session_id: Optional session ID
            save_to_memory_ts: Whether to save to memory-ts

        Returns:
            VoiceMemory object with all extracted data

        Raises:
            FileNotFoundError: If audio file doesn't exist
            RuntimeError: If transcription fails
        """
        # Step 1: Transcribe
        transcription = self.transcribe_audio(audio_path)
        transcript = transcription['transcript']
        duration = transcription.get('duration')

        # Step 2: Extract memories
        memories = self.extract_memories_from_transcript(
            transcript,
            project_id=project_id,
            session_id=session_id
        )

        # Step 3: Save to intelligence DB
        cursor = self.db.conn.cursor()

        for memory in memories:
            memory_id = None

            # Save to memory-ts if requested
            if save_to_memory_ts:
                try:
                    memory_id = self.memory_client.create(
                        content=memory['content'],
                        tags=memory.get('tags', ['#voice-memo']),
                        project_id=project_id,
                        importance=memory['importance'],
                        session_id=session_id
                    )
                except Exception as e:
                    # Log but don't fail on memory-ts errors
                    print(f"Warning: Failed to save to memory-ts: {e}")

            # Save to intelligence DB
            cursor.execute("""
                INSERT INTO voice_memories
                (audio_path, transcript, memory_id, duration_seconds, created_at, project_id, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(audio_path),
                transcript,
                memory_id,
                duration,
                datetime.now().isoformat(),
                project_id,
                json.dumps(memory.get('tags', ['#voice-memo'])),
                memory['importance']
            ))

        self.db.conn.commit()

        # Return structured result
        return VoiceMemory(
            audio_path=audio_path,
            transcript=transcript,
            memories=memories,
            duration_seconds=duration,
            project_id=project_id
        )

    def search_voice_memories(
        self,
        query: str,
        project_id: Optional[str] = None,
        min_importance: float = 0.0
    ) -> List[Dict]:
        """
        Search voice memories by text content

        Args:
            query: Search query
            project_id: Optional project filter
            min_importance: Minimum importance threshold

        Returns:
            List of matching voice memories
        """
        cursor = self.db.conn.cursor()

        sql = """
            SELECT * FROM voice_memories
            WHERE transcript LIKE ?
            AND importance >= ?
        """
        params = [f"%{query}%", min_importance]

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)

        sql += " ORDER BY importance DESC, created_at DESC"

        cursor.execute(sql, params)

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        self.db.close()

    def __enter__(self):
        """Context manager support"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close on context exit"""
        self.close()
