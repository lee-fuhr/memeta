#!/usr/bin/env python3
"""
CLAUDE.md synthesizer runner — executed by LaunchAgent weekly (Sunday 4am).

Collects graduated corrections, confirmed preferences, and workflow patterns
from the memory system and proposes CLAUDE.md rule updates.

Bible 2.14: Two-level learning with promotion.
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CLAUDE_MD_PATH = Path.home() / "CC/.claude/CLAUDE.md"


def main() -> int:
    try:
        from memory_system.claudemd_synthesizer import (
            CLAUDEMDSynthesizer,
            CorrectionRuleSource,
            DirectiveRuleSource,
            FrustrationRuleSource,
            PreferenceRuleSource,
            WorkflowRuleSource,
        )
    except ImportError as e:
        logger.error("Failed to import CLAUDEMDSynthesizer: %s", e)
        return 1

    if not CLAUDE_MD_PATH.exists():
        logger.error("CLAUDE.md not found at %s", CLAUDE_MD_PATH)
        return 1

    try:
        # Initialize all rule sources (they read from memory files)
        sources = [
            CorrectionRuleSource(),
            DirectiveRuleSource(),
            FrustrationRuleSource(),
            PreferenceRuleSource(),
            WorkflowRuleSource(),
        ]

        synthesizer = CLAUDEMDSynthesizer(
            sources=sources,
            claude_md_path=CLAUDE_MD_PATH,
        )
        result = synthesizer.synthesize()

        rules_proposed = result.get("rules_proposed", 0)
        sources_analyzed = result.get("sources_analyzed", 0)

        if rules_proposed > 0:
            logger.info(
                "Proposed %d new CLAUDE.md rules from %d source memories",
                rules_proposed,
                sources_analyzed,
            )
            for rule in result.get("proposed_rules", []):
                summary = rule.get("summary", str(rule))[:80]
                logger.info("  → %s", summary)
        else:
            logger.info(
                "No new rules to propose (%d sources analyzed)",
                sources_analyzed,
            )

        return 0

    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
