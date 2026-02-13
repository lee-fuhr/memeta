"""Advanced memory capture - Features 44-46: Voice, Image, Code"""
from pathlib import Path
from typing import Dict, List

# Feature 44: Voice memory capture
def transcribe_voice_memo(audio_path: Path) -> str:
    """Transcribe voice memo to text (would use Whisper API)."""
    return f"Transcribed: {audio_path.name}"  # Simplified

def extract_from_audio(audio_path: Path) -> List[Dict]:
    """Voice memo → memories."""
    transcript = transcribe_voice_memo(audio_path)
    from llm_extractor import extract_with_llm
    return extract_with_llm(transcript, project_id="LFI")

# Feature 45: Image memory
def ocr_screenshot(image_path: Path) -> str:
    """Extract text from screenshot (would use OCR)."""
    return f"OCR of {image_path.name}"

def index_screenshot(image_path: Path, content: str) -> Dict:
    """Make screenshot searchable."""
    return {
        'type': 'image',
        'path': str(image_path),
        'ocr_text': content,
        'tags': ['#screenshot']
    }

# Feature 46: Code memory
def extract_code_pattern(code_snippet: str, language: str) -> Dict:
    """Remember code solution."""
    return {
        'type': 'code',
        'language': language,
        'snippet': code_snippet,
        'tags': ['#code-pattern']
    }

def search_code_memories(query: str, code_memories: List[Dict]) -> List[Dict]:
    """Find how I solved X before."""
    return [m for m in code_memories if query.lower() in m.get('snippet', '').lower()]
