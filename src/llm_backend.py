"""
LLM backend for memory system.

Two modes:
1. API mode (fast, preferred): Uses Google GenAI SDK with GEMINI_API_KEY env var
2. CLI mode (slow fallback): Shells out to `gemini -p` (~20s startup per call)

Set GEMINI_API_KEY in environment for fast mode.
Get a free key at: https://aistudio.google.com/apikey

Previously used `claude -p` which broke from subprocess context (empty stdout).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

GEMINI_BIN = "/opt/homebrew/bin/gemini"
GEMINI_MODEL = "gemini-2.5-flash"
_ENV_FILE = Path(__file__).parent.parent / ".env"

# Cached API client
_genai_client = None


def _load_env_file():
    """Load .env file from project root if it exists."""
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


def _get_genai_client():
    """Get or create a cached GenAI client. Returns None if no API key."""
    global _genai_client
    if _genai_client is not None:
        return _genai_client

    _load_env_file()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        _genai_client = genai.Client(api_key=api_key)
        return _genai_client
    except ImportError:
        logger.debug("google-genai not installed, falling back to CLI")
        return None
    except Exception as e:
        logger.debug("GenAI client init failed: %s", e)
        return None


def _call_api(prompt: str, timeout: int = 30) -> str | None:
    """Call Gemini API via SDK. Returns response text or None."""
    client = _get_genai_client()
    if not client:
        return None

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": 0.2,
                "max_output_tokens": 4096,
            },
        )
        text = response.text.strip() if response.text else None
        if text:
            text = strip_code_fence(text)
        return text
    except Exception as e:
        logger.debug("GenAI API error: %s", e)
        return None


def _call_cli(prompt: str, timeout: int = 60) -> str | None:
    """Call Gemini CLI. Returns response text or None. ~20s startup overhead."""
    try:
        result = subprocess.run(
            [GEMINI_BIN, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug("Gemini CLI error: %s", e)
    return None


def run_llm_prompt(
    prompt: str,
    timeout: int = 30,
    retries: int = 2,
    retry_delay: float = 2.0,
) -> str:
    """
    Send a prompt to the LLM backend and return the response text.

    Uses API mode if GEMINI_API_KEY is set (fast, <2s per call).
    Falls back to CLI mode (~20s per call).

    Args:
        prompt: The prompt to send
        timeout: Timeout per attempt in seconds
        retries: Number of retry attempts
        retry_delay: Base delay between retries (doubles each attempt)

    Returns:
        Response text (empty string on failure)
    """
    # Pick backend
    use_api = _get_genai_client() is not None
    call_fn = _call_api if use_api else _call_cli
    effective_timeout = timeout if use_api else max(timeout, 60)

    delay = retry_delay
    for attempt in range(retries):
        result = call_fn(prompt, timeout=effective_timeout)
        if result:
            return result

        if attempt < retries - 1:
            logger.debug(
                "LLM attempt %d/%d failed (%s mode), retrying in %.0fs",
                attempt + 1, retries, "api" if use_api else "cli", delay,
            )
            time.sleep(delay)
            delay *= 2

    return ""


def run_llm_batch(
    prompts: list[str],
    timeout: int = 30,
    delay_between: float = 0.1,
) -> list[str]:
    """
    Run multiple prompts and return results in order.

    In API mode: fast sequential calls with minimal delay.
    In CLI mode: sequential with longer delays to avoid rate limits.

    Args:
        prompts: List of prompts to process
        timeout: Timeout per prompt
        delay_between: Delay between calls (overridden to 3s in CLI mode)

    Returns:
        List of response strings (empty string for failures)
    """
    use_api = _get_genai_client() is not None
    effective_delay = delay_between if use_api else max(delay_between, 3.0)

    results = []
    for i, prompt in enumerate(prompts):
        result = run_llm_prompt(prompt, timeout=timeout, retries=2)
        results.append(result)
        if i < len(prompts) - 1:
            time.sleep(effective_delay)

    return results


def strip_code_fence(text: str) -> str:
    """Remove markdown code fencing from LLM output."""
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return text
