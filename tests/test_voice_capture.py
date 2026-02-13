"""
Tests for voice_capture.py - Feature 44
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.multimodal.voice_capture import VoiceCapture, VoiceMemory


@pytest.fixture
def temp_db():
    """Create temporary database"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(temp_file.name)
    temp_file.close()

    yield db_path

    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def temp_audio():
    """Create temporary audio file"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    audio_path = Path(temp_file.name)
    temp_file.write(b"fake audio data")
    temp_file.close()

    yield audio_path

    if audio_path.exists():
        audio_path.unlink()


@pytest.fixture
def voice_capture(temp_db):
    """Create VoiceCapture instance"""
    return VoiceCapture(db_path=temp_db)


class TestVoiceMemoryDataclass:
    """Test VoiceMemory dataclass"""

    def test_create_voice_memory(self):
        """Can create VoiceMemory object"""
        vm = VoiceMemory(
            audio_path=Path("/test.m4a"),
            transcript="Test transcript",
            memories=[{'content': 'Test memory'}],
            duration_seconds=60.0
        )

        assert vm.audio_path == Path("/test.m4a")
        assert vm.transcript == "Test transcript"
        assert len(vm.memories) == 1
        assert vm.duration_seconds == 60.0

    def test_auto_timestamp(self):
        """created_at is auto-populated"""
        vm = VoiceMemory(
            audio_path=Path("/test.m4a"),
            transcript="Test",
            memories=[]
        )

        assert vm.created_at is not None
        assert "2026" in vm.created_at


class TestTranscription:
    """Test audio transcription"""

    @patch('subprocess.run')
    def test_transcribe_with_macwhisper(self, mock_run, voice_capture, temp_audio):
        """Transcribe using MacWhisper binary"""
        # Mock MacWhisper binary exists
        mock_whisper_bin = MagicMock()
        mock_whisper_bin.exists.return_value = True
        voice_capture.macwhisper_dir = MagicMock()
        voice_capture.macwhisper_dir.__truediv__ = lambda self, x: mock_whisper_bin

        # Mock subprocess result
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                'text': 'This is a test transcript',
                'duration': 45.2,
                'language': 'en'
            })
        )

        result = voice_capture.transcribe_audio(temp_audio)

        assert result['transcript'] == 'This is a test transcript'
        assert result['duration'] == 45.2
        assert result['language'] == 'en'

    def test_transcribe_nonexistent_file(self, voice_capture):
        """Raises error for missing audio file"""
        with pytest.raises(FileNotFoundError):
            voice_capture.transcribe_audio(Path("/nonexistent.m4a"))

    def test_transcribe_with_existing_transcript(self, voice_capture, temp_audio):
        """Falls back to existing .txt file"""
        # Create transcript file
        transcript_file = temp_audio.with_suffix(".txt")
        transcript_file.write_text("Fallback transcript text")

        # Mock no MacWhisper binary
        voice_capture.macwhisper_dir = Path("/nonexistent")

        result = voice_capture.transcribe_audio(temp_audio)

        assert result['transcript'] == "Fallback transcript text"

        # Cleanup
        transcript_file.unlink()


class TestMemoryExtraction:
    """Test memory extraction from transcripts"""

    @patch('src.multimodal.voice_capture.extract_with_llm')
    def test_extract_memories_with_llm(self, mock_llm, voice_capture):
        """Extract memories using LLM"""
        transcript = "I learned that voice memos are great for capturing ideas quickly."

        mock_llm.return_value = [
            {'content': 'Voice memos capture ideas quickly', 'importance': 0.7}
        ]

        memories = voice_capture.extract_memories_from_transcript(
            transcript,
            project_id="LFI"
        )

        assert len(memories) == 1
        assert 'importance' in memories[0]

    def test_extract_from_empty_transcript(self, voice_capture):
        """Empty transcript returns no memories"""
        memories = voice_capture.extract_memories_from_transcript("", "LFI")

        assert len(memories) == 0

    def test_extract_from_short_transcript(self, voice_capture):
        """Very short transcript returns no memories"""
        memories = voice_capture.extract_memories_from_transcript("Test", "LFI")

        assert len(memories) == 0


class TestProcessingPipeline:
    """Test complete voice memo processing"""

    @patch('src.multimodal.voice_capture.VoiceCapture.transcribe_audio')
    @patch('src.multimodal.voice_capture.VoiceCapture.extract_memories_from_transcript')
    def test_process_voice_memo(self, mock_extract, mock_transcribe, voice_capture, temp_audio):
        """Complete processing pipeline"""
        # Mock transcription
        mock_transcribe.return_value = {
            'transcript': 'Test transcript',
            'duration': 30.0,
            'language': 'en'
        }

        # Mock extraction
        mock_extract.return_value = [
            {
                'content': 'Test memory',
                'importance': 0.6,
                'tags': ['#voice-memo']
            }
        ]

        # Process (without memory-ts save for test)
        result = voice_capture.process_voice_memo(
            temp_audio,
            project_id="LFI",
            save_to_memory_ts=False
        )

        assert isinstance(result, VoiceMemory)
        assert result.transcript == 'Test transcript'
        assert result.duration_seconds == 30.0
        assert len(result.memories) == 1

    def test_process_saves_to_intelligence_db(self, voice_capture, temp_audio):
        """Processing saves to intelligence DB"""
        with patch.object(voice_capture, 'transcribe_audio') as mock_trans:
            with patch.object(voice_capture, 'extract_memories_from_transcript') as mock_extract:
                mock_trans.return_value = {'transcript': 'Test', 'duration': 10.0}
                mock_extract.return_value = [
                    {'content': 'Memory', 'importance': 0.5, 'tags': ['#test']}
                ]

                voice_capture.process_voice_memo(
                    temp_audio,
                    save_to_memory_ts=False
                )

                # Check DB
                cursor = voice_capture.db.conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM voice_memories")
                count = cursor.fetchone()[0]

                assert count >= 1


class TestVoiceSearch:
    """Test searching voice memories"""

    def test_search_voice_memories(self, voice_capture):
        """Can search voice memories by text"""
        # Insert test data
        cursor = voice_capture.db.conn.cursor()
        cursor.execute("""
            INSERT INTO voice_memories
            (audio_path, transcript, created_at, project_id, importance)
            VALUES (?, ?, ?, ?, ?)
        """, ("/test.m4a", "This is about testing voice search", "2026-02-12T10:00:00", "LFI", 0.7))

        voice_capture.db.conn.commit()

        # Search
        results = voice_capture.search_voice_memories("voice search", min_importance=0.5)

        assert len(results) >= 1
        assert "voice search" in results[0]['transcript']

    def test_search_with_project_filter(self, voice_capture):
        """Can filter search by project"""
        # Insert test data for different projects
        cursor = voice_capture.db.conn.cursor()
        cursor.execute("""
            INSERT INTO voice_memories
            (audio_path, transcript, created_at, project_id, importance)
            VALUES (?, ?, ?, ?, ?)
        """, ("/test1.m4a", "Project A memo", "2026-02-12T10:00:00", "ProjectA", 0.7))

        cursor.execute("""
            INSERT INTO voice_memories
            (audio_path, transcript, created_at, project_id, importance)
            VALUES (?, ?, ?, ?, ?)
        """, ("/test2.m4a", "Project B memo", "2026-02-12T10:00:00", "ProjectB", 0.7))

        voice_capture.db.conn.commit()

        # Search with filter
        results = voice_capture.search_voice_memories("memo", project_id="ProjectA")

        assert len(results) == 1
        assert results[0]['project_id'] == "ProjectA"


class TestContextManager:
    """Test context manager support"""

    def test_with_statement(self, temp_db):
        """Can use with statement"""
        with VoiceCapture(db_path=temp_db) as vc:
            assert vc.db is not None
