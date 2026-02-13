"""
Feature 45: Image memory capture

Screenshots/images → OCR + vision analysis → searchable memories
Uses Claude vision API for rich context extraction
"""

import base64
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from ..intelligence_db import IntelligenceDB
from ..importance_engine import calculate_importance
from ..memory_ts_client import MemoryTSClient


@dataclass
class ImageMemory:
    """Image converted to searchable memory"""
    image_path: Path
    ocr_text: str
    vision_insights: str
    memories: List[Dict]
    created_at: str = None
    project_id: str = "LFI"

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class ImageCapture:
    """
    Image memory capture system

    Workflow:
    1. Extract text via OCR (tesseract)
    2. Analyze with Claude vision API
    3. Extract structured insights
    4. Save to memory-ts + intelligence DB
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize image capture

        Args:
            db_path: Intelligence database path
        """
        self.db = IntelligenceDB(db_path)
        self.memory_client = MemoryTSClient()

    def ocr_image(self, image_path: Path) -> str:
        """
        Extract text from image using OCR

        Args:
            image_path: Path to image file

        Returns:
            Extracted text

        Raises:
            FileNotFoundError: If image doesn't exist
            RuntimeError: If OCR fails
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Try tesseract OCR
        try:
            result = subprocess.run(
                ["tesseract", str(image_path), "stdout"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                # Tesseract not available or failed
                return ""

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Fallback: return empty (vision analysis can still work)
            return ""

    def analyze_with_vision(self, image_path: Path, ocr_text: str = "") -> str:
        """
        Analyze image using Claude vision API

        Args:
            image_path: Path to image
            ocr_text: Optional OCR text for context

        Returns:
            Vision analysis insights

        Raises:
            FileNotFoundError: If image doesn't exist
        """
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Read and encode image
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Determine media type
        suffix = image_path.suffix.lower()
        media_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        media_type = media_type_map.get(suffix, 'image/png')

        # Build prompt
        prompt = """Analyze this image and extract key insights:

1. What is the main subject/content?
2. What information or data is shown?
3. What decisions, problems, or solutions are visible?
4. What's important to remember about this?
"""

        if ocr_text:
            prompt += f"\nOCR text extracted:\n{ocr_text}\n\nUse this to enhance your analysis."

        # Call Claude via CLI (following llm_extractor pattern)
        try:
            # Use claude CLI with vision support
            result = subprocess.run(
                [
                    "claude",
                    "-p", prompt,
                    "--image", str(image_path)
                ],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                # Fallback: use OCR text if available
                if ocr_text:
                    return f"OCR extracted: {ocr_text}"
                else:
                    return "Image captured (vision analysis unavailable)"

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            # Fallback to OCR
            if ocr_text:
                return f"OCR extracted: {ocr_text}"
            else:
                raise RuntimeError(f"Vision analysis failed: {e}")

    def extract_memories_from_image(
        self,
        ocr_text: str,
        vision_insights: str,
        project_id: str = "LFI",
        session_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Extract structured memories from image analysis

        Args:
            ocr_text: Text extracted via OCR
            vision_insights: Claude vision analysis
            project_id: Project scope
            session_id: Optional session ID

        Returns:
            List of memories
        """
        combined_text = f"{vision_insights}\n\n{ocr_text}".strip()

        if not combined_text or len(combined_text) < 20:
            return []

        # Extract key insights as bullet points
        insights = []

        for line in vision_insights.split('\n'):
            line = line.strip()
            if line and len(line) > 20:
                # Skip numbered lists and headers
                if line[0].isdigit() or line.endswith(':'):
                    continue

                insights.append({
                    'content': line,
                    'importance': calculate_importance(line),
                    'tags': ['#screenshot', '#visual'],
                    'project_id': project_id
                })

        return insights[:5]  # Top 5 insights

    def process_image(
        self,
        image_path: Path,
        project_id: str = "LFI",
        session_id: Optional[str] = None,
        save_to_memory_ts: bool = True
    ) -> ImageMemory:
        """
        Complete image processing pipeline

        Args:
            image_path: Path to image file
            project_id: Project scope
            session_id: Optional session ID
            save_to_memory_ts: Whether to save to memory-ts

        Returns:
            ImageMemory object with analysis

        Raises:
            FileNotFoundError: If image doesn't exist
        """
        # Step 1: OCR
        ocr_text = self.ocr_image(image_path)

        # Step 2: Vision analysis
        vision_insights = self.analyze_with_vision(image_path, ocr_text)

        # Step 3: Extract memories
        memories = self.extract_memories_from_image(
            ocr_text,
            vision_insights,
            project_id=project_id,
            session_id=session_id
        )

        # Step 4: Save to intelligence DB
        cursor = self.db.conn.cursor()

        for memory in memories:
            memory_id = None

            # Save to memory-ts if requested
            if save_to_memory_ts:
                try:
                    memory_id = self.memory_client.create(
                        content=memory['content'],
                        tags=memory.get('tags', ['#screenshot']),
                        project_id=project_id,
                        importance=memory['importance'],
                        session_id=session_id
                    )
                except Exception as e:
                    print(f"Warning: Failed to save to memory-ts: {e}")

            # Save to intelligence DB
            cursor.execute("""
                INSERT INTO image_memories
                (image_path, ocr_text, vision_analysis, memory_id, created_at, project_id, tags, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(image_path),
                ocr_text,
                vision_insights,
                memory_id,
                datetime.now().isoformat(),
                project_id,
                json.dumps(memory.get('tags', ['#screenshot'])),
                memory['importance']
            ))

        self.db.conn.commit()

        return ImageMemory(
            image_path=image_path,
            ocr_text=ocr_text,
            vision_insights=vision_insights,
            memories=memories,
            project_id=project_id
        )

    def search_image_memories(
        self,
        query: str,
        project_id: Optional[str] = None,
        min_importance: float = 0.0
    ) -> List[Dict]:
        """
        Search image memories by text content

        Args:
            query: Search query
            project_id: Optional project filter
            min_importance: Minimum importance threshold

        Returns:
            List of matching image memories
        """
        cursor = self.db.conn.cursor()

        sql = """
            SELECT * FROM image_memories
            WHERE (ocr_text LIKE ? OR vision_analysis LIKE ?)
            AND importance >= ?
        """
        params = [f"%{query}%", f"%{query}%", min_importance]

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
