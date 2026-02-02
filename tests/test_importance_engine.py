"""
Tests for importance_engine.py - TDD approach (RED phase)

Testing:
- Importance scoring (0.0-1.0 scale)
- Decay formula (0.99^days)
- Reinforcement (+15% with headroom)
- Trigger word detection
"""

import pytest
from datetime import datetime, timedelta
from src.importance_engine import (
    calculate_importance,
    apply_decay,
    apply_reinforcement,
    detect_trigger_words,
    get_importance_score
)


class TestCalculateImportance:
    """Test base importance calculation from content signals"""

    def test_high_importance_content(self):
        """Content with strong signals gets high score (0.8+)"""
        content = "CRITICAL: This pattern broke production across 3 clients"
        score = calculate_importance(content)
        assert score >= 0.8
        assert score <= 1.0

    def test_medium_importance_content(self):
        """Learning with single keyword gets medium score (0.6-0.8)"""
        content = "Discovered that users respond better to concrete examples than abstract explanations"
        score = calculate_importance(content)
        assert score >= 0.5
        assert score < 0.8

    def test_low_importance_content(self):
        """Minor observations get low score (0.4-0.6)"""
        content = "Updated logo color to blue"
        score = calculate_importance(content)
        assert score >= 0.4
        assert score < 0.6

    def test_importance_never_exceeds_one(self):
        """Even extreme content caps at 1.0"""
        content = "CRITICAL URGENT IMPORTANT BREAKING PRODUCTION DOWN"
        score = calculate_importance(content)
        assert score <= 1.0

    def test_importance_never_below_minimum(self):
        """Even trivial content has minimum threshold"""
        content = "x"
        score = calculate_importance(content)
        assert score >= 0.3  # minimum threshold


class TestApplyDecay:
    """Test decay formula: importance × (0.99 ^ days_since)"""

    def test_no_decay_same_day(self):
        """Same day = no decay"""
        original = 0.8
        days_since = 0
        decayed = apply_decay(original, days_since)
        assert decayed == original

    def test_decay_after_one_week(self):
        """1 week = 0.99^7 ≈ 0.932 multiplier"""
        original = 0.8
        days_since = 7
        decayed = apply_decay(original, days_since)
        expected = 0.8 * (0.99 ** 7)  # ≈ 0.746
        assert abs(decayed - expected) < 0.001

    def test_decay_after_30_days(self):
        """30 days = significant decay"""
        original = 0.8
        days_since = 30
        decayed = apply_decay(original, days_since)
        expected = 0.8 * (0.99 ** 30)  # ≈ 0.592
        assert abs(decayed - expected) < 0.001

    def test_decay_never_negative(self):
        """Decay never produces negative importance"""
        original = 0.5
        days_since = 1000  # extreme age
        decayed = apply_decay(original, days_since)
        assert decayed >= 0


class TestApplyReinforcement:
    """Test reinforcement: +15% with headroom (cap at 0.95)"""

    def test_reinforcement_adds_fifteen_percent(self):
        """Reinforcement adds 15% to current score"""
        current = 0.6
        reinforced = apply_reinforcement(current)
        expected = 0.6 * 1.15  # = 0.69
        assert abs(reinforced - expected) < 0.001

    def test_reinforcement_caps_at_ninety_five(self):
        """Reinforcement never exceeds 0.95 (headroom for growth)"""
        current = 0.9
        reinforced = apply_reinforcement(current)
        assert reinforced <= 0.95

    def test_reinforcement_multiple_times(self):
        """Multiple reinforcements compound but stay under cap"""
        current = 0.6
        reinforced = apply_reinforcement(current)  # → 0.69
        reinforced = apply_reinforcement(reinforced)  # → 0.7935
        reinforced = apply_reinforcement(reinforced)  # → 0.912
        assert reinforced <= 0.95

    def test_reinforcement_low_importance(self):
        """Even low importance can be reinforced"""
        current = 0.3
        reinforced = apply_reinforcement(current)
        expected = 0.3 * 1.15  # = 0.345
        assert abs(reinforced - expected) < 0.001


class TestDetectTriggerWords:
    """Test trigger word detection for importance boost"""

    def test_detects_critical_keywords(self):
        """Detects urgency keywords"""
        content = "CRITICAL: Production is down"
        triggers = detect_trigger_words(content)
        assert "CRITICAL" in triggers

    def test_detects_pattern_keywords(self):
        """Detects cross-project pattern indicators"""
        content = "Same pattern across 3 clients - users prefer simple navigation"
        triggers = detect_trigger_words(content)
        assert "pattern" in [t.lower() for t in triggers]

    def test_detects_multiple_triggers(self):
        """Finds all trigger words in content"""
        content = "URGENT pattern broke production workflow"
        triggers = detect_trigger_words(content)
        assert len(triggers) >= 2

    def test_returns_empty_for_no_triggers(self):
        """Returns empty list when no triggers found"""
        content = "Updated button color to blue"
        triggers = detect_trigger_words(content)
        assert len(triggers) == 0

    def test_case_insensitive_detection(self):
        """Trigger detection is case-insensitive"""
        content = "critical issue with Critical importance"
        triggers = detect_trigger_words(content)
        # Should find "critical" or "CRITICAL" (case variations count as one)
        trigger_lower = [t.lower() for t in triggers]
        assert trigger_lower.count("critical") >= 1


class TestGetImportanceScore:
    """Test complete importance scoring pipeline"""

    def test_complete_pipeline_new_memory(self):
        """New memory with no history"""
        content = "Client preferred direct language over marketing-speak"
        metadata = {
            "created": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat()
        }
        score = get_importance_score(content, metadata)
        assert 0.3 <= score <= 1.0

    def test_complete_pipeline_with_decay(self):
        """Old memory decays over time"""
        content = "Client preferred direct language"
        created = (datetime.now() - timedelta(days=30)).isoformat()
        last_accessed = (datetime.now() - timedelta(days=30)).isoformat()
        metadata = {
            "created": created,
            "last_accessed": last_accessed
        }
        score = get_importance_score(content, metadata)
        # Should be decayed from base
        assert score < 0.8  # assuming base would be higher

    def test_complete_pipeline_with_reinforcement(self):
        """Recently accessed memory gets reinforced"""
        content = "Client preferred direct language"
        created = (datetime.now() - timedelta(days=30)).isoformat()
        last_accessed = datetime.now().isoformat()  # accessed today
        metadata = {
            "created": created,
            "last_accessed": last_accessed,
            "access_count": 3  # multiple accesses = reinforcement
        }
        score = get_importance_score(content, metadata)
        # Should be higher than purely decayed score
        assert score > 0.3
