"""
Feature 31: Auto-Summarization — re-export from merged implementation.

All logic has been merged into intelligence/summarization.py (Feature 26+31).
This module re-exports the public API so existing imports continue to work.

    from memory_system.automation.summarization import AutoSummarization, TopicSummary
"""

from memory_system.intelligence.summarization import (
    MemorySummarizer as AutoSummarization,
    TopicSummary,
)

__all__ = ["AutoSummarization", "TopicSummary"]
