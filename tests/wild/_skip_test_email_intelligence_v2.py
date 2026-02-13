"""
Feature 41: Email Intelligence v2 Tests

Email sentiment analysis, action item extraction,
relationship health signals from email patterns.
"""

import pytest
import tempfile
from pathlib import Path

from src.wild.integrations import (
    analyze_email_sentiment,
    extract_email_actions,
    detect_email_patterns
)


class TestEmailSentiment:
    """Tests for email sentiment analysis"""

    def test_sentiment_positive(self):
        """Detects positive sentiment in email"""
        email = {
            'subject': 'Great work!',
            'body': 'Really impressed with the results. Excited to continue.'
        }
        sentiment = analyze_email_sentiment(email)
        assert sentiment['sentiment'] == 'positive'

    def test_sentiment_frustrated(self):
        """Detects frustration in email"""
        email = {
            'subject': 'Issue with deliverables',
            'body': 'This is the third time we\'ve had problems. Very frustrating.'
        }
        sentiment = analyze_email_sentiment(email)
        assert sentiment['sentiment'] == 'frustrated'


class TestActionExtraction:
    """Tests for action item extraction"""

    def test_extract_actions_from_email(self):
        """Extracts action items from email body"""
        email = {
            'body': 'Please send the report by Friday. Also, schedule a follow-up call.'
        }
        actions = extract_email_actions(email)
        assert len(actions) >= 1


class TestEmailPatterns:
    """Tests for email pattern detection"""

    def test_detect_patterns_no_history(self):
        """Handles no email history gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            patterns = detect_email_patterns(
                contact_email='test@example.com',
                db_path=db_path
            )
            assert patterns['status'] == 'no_data'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
