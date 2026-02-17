"""
Correction promotion - Auto-promote tool corrections to TOOLS.md.

When user corrects tool usage (email, calendar, notion, etc.), automatically
promote the correction to TOOLS.md as a "Learned Preference" so the agent
applies it automatically next time.

Example:
User: "No, just search inbox — not all Gmail labels"
→ Detected as correction
→ Promoted to TOOLS.md under Gmail section
→ Next time: Agent remembers to search inbox only
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional


# Tool keywords that trigger promotion
TOOL_KEYWORDS = [
    "email", "gmail", "inbox", "calendar", "todoist", "notion",
    "slack", "github", "google", "drive", "docs", "sheets",
    "meeting", "transcript", "granola"
]

# Path to the project's CLAUDE.md / TOOLS.md for correction promotion.
# Set MEMORY_SYSTEM_TOOLS_MD to an absolute path to enable this feature.
# When unset, corrections are logged but not written to any file.
_tools_md_env = os.environ.get("MEMORY_SYSTEM_TOOLS_MD")
TOOLS_MD_PATH: Path | None = Path(_tools_md_env) if _tools_md_env else None


def is_tool_correction(correction_text: str) -> bool:
    """
    Check if correction mentions tools.

    Args:
        correction_text: Correction content

    Returns:
        True if mentions tools, False otherwise
    """
    text_lower = correction_text.lower()

    for keyword in TOOL_KEYWORDS:
        if keyword in text_lower:
            return True

    return False


def extract_tool_name(correction_text: str) -> str:
    """
    Identify which tool the correction is about.

    Args:
        correction_text: Correction content

    Returns:
        Tool name (capitalized) or "General"
    """
    text_lower = correction_text.lower()

    # Priority order for multi-keyword matches
    priority_tools = {
        "gmail": "Gmail",
        "email": "Email",
        "calendar": "Calendar",
        "todoist": "Todoist",
        "notion": "Notion",
        "slack": "Slack",
        "github": "GitHub",
        "google docs": "Google Docs",
        "docs": "Google Docs",
        "drive": "Google Drive",
        "sheets": "Google Sheets",
        "meeting": "Meetings",
        "granola": "Granola",
        "transcript": "Transcripts"
    }

    for keyword, tool_name in priority_tools.items():
        if keyword in text_lower:
            return tool_name

    return "General"


def promote_to_tools_md(
    correction: str,
    tool_name: str,
    session_id: str,
    date: Optional[str] = None
) -> bool:
    """
    Add correction to TOOLS.md as learned preference.

    Args:
        correction: Correction content
        tool_name: Tool name (e.g., "Gmail", "Calendar")
        session_id: Session where correction occurred
        date: Date of correction (defaults to today)

    Returns:
        True if successfully promoted, False otherwise
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')

    if not TOOLS_MD_PATH.exists():
        print(f"⚠️  TOOLS.md not found at {TOOLS_MD_PATH}")
        return False

    try:
        # Read existing file
        tools_md = TOOLS_MD_PATH.read_text()

        # Format learned preference entry
        # Extract key phrase for title (up to first period or 80 chars)
        title_text = correction.split('.')[0] if '.' in correction else correction
        title_text = title_text[:80] if len(title_text) > 80 else title_text

        preference_entry = f"""
- **{title_text}**
  - Correction: {correction}
  - Source: Session `{session_id[:8]}` ({date})
"""

        # Find or create tool section
        tool_section = f"## {tool_name}"
        learned_section = "### Learned preferences"

        if tool_section in tools_md:
            # Tool section exists
            if learned_section in tools_md:
                # Append to existing learned preferences
                # Find the learned preferences section
                learned_start = tools_md.find(learned_section)
                if learned_start != -1:
                    # Find end of section (next ### or ##)
                    section_after = tools_md.find('\n##', learned_start + len(learned_section))
                    insert_pos = section_after if section_after != -1 else len(tools_md)

                    tools_md = (
                        tools_md[:insert_pos] +
                        preference_entry +
                        '\n' +
                        tools_md[insert_pos:]
                    )
            else:
                # Add learned preferences subsection
                section_start = tools_md.find(tool_section)
                section_end = tools_md.find('\n##', section_start + len(tool_section))
                insert_pos = section_end if section_end != -1 else len(tools_md)

                tools_md = (
                    tools_md[:insert_pos] +
                    f"\n{learned_section}\n{preference_entry}\n" +
                    tools_md[insert_pos:]
                )
        else:
            # Create new tool section at end
            tools_md += f"\n\n{tool_section}\n\n{learned_section}\n{preference_entry}\n"

        # Write back
        TOOLS_MD_PATH.write_text(tools_md)

        print(f"✅ Promoted to TOOLS.md: {title_text}")
        return True

    except Exception as e:
        print(f"❌ Failed to promote to TOOLS.md: {e}")
        return False
