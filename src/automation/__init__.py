"""
Automation Layer - Features 28-32

Smart triggers, alerts, search, summarization, and quality scoring.
"""

from .alerts import SmartAlerts, Alert, AlertDigest
from .quality import QualityScoring, QualityScore
from .search import MemoryAwareSearch, SearchQuery, SearchResult
from .summarization import AutoSummarization, TopicSummary
from .triggers import MemoryTriggers, Trigger, TriggerExecution

__all__ = [
    # Alerts (F29)
    'SmartAlerts',
    'Alert',
    'AlertDigest',

    # Quality (F32)
    'QualityScoring',
    'QualityScore',

    # Search (F30)
    'MemoryAwareSearch',
    'SearchQuery',
    'SearchResult',

    # Summarization (F31)
    'AutoSummarization',
    'TopicSummary',

    # Triggers (F28)
    'MemoryTriggers',
    'Trigger',
    'TriggerExecution',
]
