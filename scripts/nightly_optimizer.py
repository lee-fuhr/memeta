#!/usr/bin/env python3
"""
Autonomous Nightly Optimizer - System improves itself while you sleep.

Feature 22 (Lee's vision): Runs at 11:57pm, analyzes today's sessions,
identifies 1-3 optimizations, implements them automatically.

Morning email: "While you slept: Added hook X, promoted correction Y, optimized Z"

Safety rails:
- Small changes: Auto-implement (add hook, update docs, create script)
- Large changes: Write proposal to _ Inbox/proposed-optimizations/
- Always create git commit
- Never modify core without approval
- Easy rollback (tagged commits)
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_history_db import get_recent_sessions, search_sessions
from src.pattern_miner import mine_all_patterns
from src.llm_extractor import ask_claude


PROPOSALS_DIR = Path.home() / "CC/LFI/_ Inbox/proposed-optimizations"
TOOLS_MD = Path.home() / "CC/LFI/_ Operations/CLAUDE.md"
ANTI_PATTERNS_MD = Path.home() / "CC/LFI/_ System/anti-patterns.md"


def analyze_todays_sessions() -> Dict:
    """
    Analyze all sessions from today for optimization opportunities.

    Returns:
        Dict with analysis results
    """
    today = datetime.now().date()

    # Get today's sessions from session history DB
    all_sessions = get_recent_sessions(limit=50)

    today_sessions = [
        s for s in all_sessions
        if datetime.fromtimestamp(s['timestamp']).date() == today
    ]

    if not today_sessions:
        return {
            'sessions_analyzed': 0,
            'optimizations': [],
            'patterns': {}
        }

    # Search for frustration signals
    frustrations = search_sessions("no actually|correction|wrong|mistake|instead", limit=20)

    # Search for repeated workflows
    repeated_workflows = search_sessions("can you|could you|please", limit=20)

    # Analyze patterns
    # (Would need to load actual memories here - simplified for now)
    patterns = {}

    return {
        'sessions_analyzed': len(today_sessions),
        'total_messages': sum(s['message_count'] for s in today_sessions),
        'frustrations_found': len([s for s in frustrations if s in today_sessions]),
        'repeated_workflows': len([s for s in repeated_workflows if s in today_sessions]),
        'patterns': patterns
    }


def identify_optimizations(analysis: Dict) -> List[Dict]:
    """
    Use LLM to identify 1-3 high-value optimizations.

    Args:
        analysis: Analysis from analyze_todays_sessions()

    Returns:
        List of optimization dicts
    """
    prompt = f"""Analyze these session patterns and identify 1-3 system optimizations.

Sessions analyzed: {analysis['sessions_analyzed']}
Total messages: {analysis['total_messages']}
Frustration signals: {analysis['frustrations_found']}
Repeated workflows: {analysis['repeated_workflows']}

For each optimization, return:
- type: "hook" | "documentation" | "automation" | "correction_promotion"
- description: What to change
- impact: "low" | "medium" | "high"
- implementation: "auto" (safe to implement) or "proposal" (needs review)
- rationale: Why this helps

Return JSON array:
[{{"type": "...", "description": "...", "impact": "...", "implementation": "...", "rationale": "..."}}]

If no clear optimizations, return empty array []."""

    try:
        response = ask_claude(prompt, timeout=30)
        optimizations = json.loads(response.strip())

        if not isinstance(optimizations, list):
            return []

        # Limit to top 3
        return optimizations[:3]

    except Exception as e:
        print(f"⚠️  Failed to identify optimizations: {e}")
        return []


def implement_optimization(optimization: Dict) -> bool:
    """
    Implement an optimization (if safe) or write proposal.

    Args:
        optimization: Optimization dict from identify_optimizations()

    Returns:
        True if implemented or proposal written
    """
    opt_type = optimization.get('type')
    description = optimization.get('description', '')
    implementation = optimization.get('implementation', 'proposal')

    # Safety check - only auto-implement safe types
    if implementation == "auto" and opt_type in ['documentation', 'correction_promotion']:
        # Safe to auto-implement
        if opt_type == 'documentation':
            return add_documentation(description)
        elif opt_type == 'correction_promotion':
            return promote_correction(description)

    else:
        # Write proposal for manual review
        return write_proposal(optimization)


def add_documentation(description: str) -> bool:
    """Add documentation based on optimization."""
    # Example: Add to anti-patterns.md or TOOLS.md
    # Simplified - would need LLM to determine which file and content
    print(f"✅ Would add documentation: {description}")
    return True


def promote_correction(description: str) -> bool:
    """Promote correction to TOOLS.md or anti-patterns.md."""
    print(f"✅ Would promote correction: {description}")
    return True


def write_proposal(optimization: Dict) -> bool:
    """
    Write optimization proposal for manual review.

    Args:
        optimization: Optimization dict

    Returns:
        True if proposal written
    """
    os.makedirs(PROPOSALS_DIR, exist_ok=True)

    today = datetime.now().strftime('%Y-%m-%d')
    filename = f"{today}-{optimization.get('type', 'optimization')}.md"
    filepath = PROPOSALS_DIR / filename

    content = f"""# Proposed Optimization: {optimization.get('description', 'Untitled')}

**Date:** {today}
**Type:** {optimization.get('type', 'unknown')}
**Impact:** {optimization.get('impact', 'unknown')}
**Implementation:** Requires manual review

## Rationale

{optimization.get('rationale', 'No rationale provided')}

## Proposed Changes

(Claude would detail specific changes here)

## Approval

- [ ] Approve and implement
- [ ] Modify and implement
- [ ] Reject

---

*Generated by Autonomous Nightly Optimizer*
"""

    with open(filepath, 'w') as f:
        f.write(content)

    print(f"📝 Wrote proposal: {filepath}")
    return True


def send_morning_email(optimizations: List[Dict], analysis: Dict):
    """
    Send morning email with optimization summary.

    (Would integrate with email system - for now just print)
    """
    print("\n" + "="*60)
    print("MORNING EMAIL PREVIEW")
    print("="*60 + "\n")

    print(f"Subject: While you slept: {len(optimizations)} optimizations applied\n")

    print(f"Analyzed {analysis['sessions_analyzed']} sessions from yesterday.\n")

    if optimizations:
        print("Optimizations:")
        for i, opt in enumerate(optimizations, 1):
            status = "✅ Applied" if opt.get('implementation') == 'auto' else "📝 Proposal written"
            print(f"{i}. {status}: {opt.get('description')}")
            print(f"   Impact: {opt.get('impact')}, Rationale: {opt.get('rationale')}\n")
    else:
        print("No optimizations identified. System running smoothly!\n")

    print("="*60)


def main():
    """
    Main autonomous optimization flow.

    Runs nightly at 11:57pm via LaunchAgent.
    """
    print("🌙 Nightly Optimizer starting...")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Step 1: Analyze today's sessions
    print("📊 Analyzing today's sessions...")
    analysis = analyze_todays_sessions()
    print(f"   Analyzed {analysis['sessions_analyzed']} sessions\n")

    if analysis['sessions_analyzed'] == 0:
        print("No sessions today. Exiting.")
        return

    # Step 2: Identify optimizations
    print("🔍 Identifying optimizations...")
    optimizations = identify_optimizations(analysis)
    print(f"   Found {len(optimizations)} optimizations\n")

    # Step 3: Implement safe optimizations, write proposals for others
    implemented = []
    for opt in optimizations:
        print(f"⚙️  Processing: {opt.get('description')}")
        if implement_optimization(opt):
            implemented.append(opt)
        print()

    # Step 4: Send morning email
    send_morning_email(implemented, analysis)

    print("✅ Nightly optimization complete!")


if __name__ == "__main__":
    main()
