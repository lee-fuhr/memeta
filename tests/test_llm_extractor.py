"""
Tests for LLM-powered memory extraction

Tests prompt generation, response parsing, and integration
with pattern-based extraction. CLI invocation is mocked.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_extractor import (
    generate_extraction_prompt,
    parse_llm_response,
    extract_with_llm,
    combine_extractions,
)
from src.session_consolidator import SessionMemory


class TestPromptGeneration:
    """Test extraction prompt creation"""

    def test_generate_prompt_includes_conversation(self):
        """Prompt should contain the conversation text"""
        conversation = "user: I prefer tabs over spaces\nassistant: Noted."
        prompt = generate_extraction_prompt(conversation)
        assert "I prefer tabs over spaces" in prompt

    def test_prompt_truncates_long_conversations(self):
        """Conversations over 15k chars should be truncated to last 15k"""
        long_convo = "x" * 30000
        prompt = generate_extraction_prompt(long_convo)
        # Prompt itself has boilerplate, but conversation portion should be <= 15k
        assert len(prompt) < 20000  # 15k convo + ~5k boilerplate max

    def test_prompt_requests_json_format(self):
        """Prompt should ask for JSON array output"""
        prompt = generate_extraction_prompt("some conversation")
        assert "JSON" in prompt
        assert "content" in prompt
        assert "importance" in prompt

    def test_prompt_includes_categories(self):
        """Prompt should specify extraction categories"""
        prompt = generate_extraction_prompt("some conversation")
        assert "preference" in prompt.lower() or "Preference" in prompt
        assert "correction" in prompt.lower() or "Correction" in prompt
        assert "technical" in prompt.lower() or "Technical" in prompt


class TestResponseParsing:
    """Test parsing LLM JSON responses"""

    def test_parse_valid_json_array(self):
        """Should parse well-formed JSON array"""
        response = json.dumps([
            {"content": "Use tabs", "importance": 0.7, "reasoning": "User preference", "category": "preference"}
        ])
        memories = parse_llm_response(response, project_id="LFI")
        assert len(memories) == 1
        assert memories[0].content == "Use tabs"
        assert memories[0].importance == 0.7

    def test_parse_json_with_markdown_fencing(self):
        """Should handle ```json fenced responses"""
        response = '```json\n[{"content": "Test", "importance": 0.8, "reasoning": "x", "category": "technical"}]\n```'
        memories = parse_llm_response(response, project_id="LFI")
        assert len(memories) == 1
        assert memories[0].content == "Test"

    def test_parse_empty_array(self):
        """Should handle empty array (no learnings)"""
        memories = parse_llm_response("[]", project_id="LFI")
        assert len(memories) == 0

    def test_parse_malformed_response(self):
        """Should return empty list for non-JSON response"""
        memories = parse_llm_response("I couldn't find any learnings.", project_id="LFI")
        assert len(memories) == 0

    def test_parse_empty_response(self):
        """Should handle empty string"""
        memories = parse_llm_response("", project_id="LFI")
        assert len(memories) == 0

    def test_importance_clamped_to_valid_range(self):
        """Importance should be clamped to 0.0-1.0"""
        response = json.dumps([
            {"content": "Test high", "importance": 1.5, "reasoning": "x", "category": "technical"},
            {"content": "Test low", "importance": -0.1, "reasoning": "x", "category": "technical"},
        ])
        memories = parse_llm_response(response, project_id="LFI")
        assert memories[0].importance == 1.0
        assert memories[1].importance == 0.0

    def test_llm_tag_applied(self):
        """LLM-extracted memories should have #llm-extracted tag"""
        response = json.dumps([
            {"content": "Test", "importance": 0.7, "reasoning": "x", "category": "technical"}
        ])
        memories = parse_llm_response(response, project_id="LFI")
        assert "#llm-extracted" in memories[0].tags

    def test_learning_tag_also_present(self):
        """LLM-extracted memories should also have #learning tag"""
        response = json.dumps([
            {"content": "Test", "importance": 0.7, "reasoning": "x", "category": "technical"}
        ])
        memories = parse_llm_response(response, project_id="LFI")
        assert "#learning" in memories[0].tags

    def test_skips_entries_missing_content(self):
        """Should skip entries without content field"""
        response = json.dumps([
            {"importance": 0.7, "reasoning": "x", "category": "technical"},
            {"content": "Valid", "importance": 0.7, "reasoning": "x", "category": "technical"},
        ])
        memories = parse_llm_response(response, project_id="LFI")
        assert len(memories) == 1
        assert memories[0].content == "Valid"


class TestCombineExtractions:
    """Test merging pattern + LLM results"""

    def test_combine_both_sources(self):
        """Should merge memories from both methods"""
        pattern_memories = [
            SessionMemory(content="Pattern finding 1", importance=0.6, project_id="LFI"),
        ]
        llm_memories = [
            SessionMemory(content="LLM finding 1", importance=0.8, project_id="LFI",
                         tags=["#learning", "#llm-extracted"]),
        ]
        combined = combine_extractions(pattern_memories, llm_memories)
        assert len(combined) == 2

    def test_deduplicate_across_methods(self):
        """Should remove duplicates between pattern and LLM results"""
        pattern_memories = [
            SessionMemory(content="User prefers tabs over spaces for indentation",
                         importance=0.6, project_id="LFI"),
        ]
        llm_memories = [
            SessionMemory(content="User prefers tabs over spaces for code indentation",
                         importance=0.8, project_id="LFI",
                         tags=["#learning", "#llm-extracted"]),
        ]
        combined = combine_extractions(pattern_memories, llm_memories)
        # Should keep only one (LLM version preferred due to higher importance)
        assert len(combined) == 1

    def test_llm_preferred_over_pattern_for_duplicates(self):
        """When deduplicated, keep the higher-importance version"""
        pattern_memories = [
            SessionMemory(content="Use tabs for indentation always",
                         importance=0.5, project_id="LFI"),
        ]
        llm_memories = [
            SessionMemory(content="Use tabs for indentation always in Python code",
                         importance=0.8, project_id="LFI",
                         tags=["#learning", "#llm-extracted"]),
        ]
        combined = combine_extractions(pattern_memories, llm_memories)
        assert len(combined) == 1
        assert combined[0].importance == 0.8

    def test_combine_empty_llm(self):
        """Should work when LLM returns nothing"""
        pattern_memories = [
            SessionMemory(content="Finding", importance=0.6, project_id="LFI"),
        ]
        combined = combine_extractions(pattern_memories, [])
        assert len(combined) == 1

    def test_combine_empty_patterns(self):
        """Should work when patterns return nothing"""
        llm_memories = [
            SessionMemory(content="Finding", importance=0.7, project_id="LFI",
                         tags=["#learning", "#llm-extracted"]),
        ]
        combined = combine_extractions([], llm_memories)
        assert len(combined) == 1


class TestExtractWithLLM:
    """Test full LLM extraction pipeline (CLI mocked)"""

    @patch("src.llm_extractor.subprocess.run")
    def test_calls_claude_cli(self, mock_run):
        """Should invoke claude -p with extraction prompt"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"content": "Test", "importance": 0.7, "reasoning": "x", "category": "technical"}]',
            stderr=""
        )
        memories = extract_with_llm("user: hello\nassistant: hi", project_id="LFI")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "claude" in call_args[0][0][0]

    @patch("src.llm_extractor.subprocess.run")
    def test_returns_parsed_memories(self, mock_run):
        """Should return parsed SessionMemory objects"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"content": "Always validate input", "importance": 0.75, "reasoning": "x", "category": "technical"}]',
            stderr=""
        )
        memories = extract_with_llm("conversation text", project_id="LFI")
        assert len(memories) == 1
        assert memories[0].content == "Always validate input"
        assert "#llm-extracted" in memories[0].tags

    @patch("src.llm_extractor.subprocess.run")
    def test_handles_cli_failure(self, mock_run):
        """Should return empty list if CLI fails"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: not authenticated"
        )
        memories = extract_with_llm("conversation text", project_id="LFI")
        assert len(memories) == 0

    @patch("src.llm_extractor.subprocess.run")
    def test_handles_cli_timeout(self, mock_run):
        """Should return empty list on timeout"""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
        memories = extract_with_llm("conversation text", project_id="LFI")
        assert len(memories) == 0

    @patch("src.llm_extractor.subprocess.run")
    def test_handles_cli_not_found(self, mock_run):
        """Should return empty list if claude CLI not installed"""
        mock_run.side_effect = FileNotFoundError("claude not found")
        memories = extract_with_llm("conversation text", project_id="LFI")
        assert len(memories) == 0
