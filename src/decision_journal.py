"""Decision journal - Feature 47: Track decisions and outcomes"""
from typing import Dict, Optional
from datetime import datetime

def record_decision(
    decision: str,
    options_considered: List[str],
    chosen_option: str,
    rationale: str
) -> Dict:
    """Record a decision made."""
    return {
        'type': 'decision',
        'decision': decision,
        'options': options_considered,
        'chosen': chosen_option,
        'rationale': rationale,
        'timestamp': datetime.now().isoformat(),
        'outcome': None  # Track later
    }

def track_outcome(decision_id: str, outcome: str, success: bool) -> Dict:
    """Track how decision worked out."""
    return {
        'decision_id': decision_id,
        'outcome': outcome,
        'success': success,
        'recorded_at': datetime.now().isoformat()
    }

def learn_from_decisions(decisions: List[Dict]) -> Dict:
    """Pattern: What decision patterns work?"""
    successful = [d for d in decisions if d.get('outcome', {}).get('success')]
    return {
        'total': len(decisions),
        'successful': len(successful),
        'success_rate': len(successful) / len(decisions) if decisions else 0
    }
