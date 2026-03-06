"""
Project ID resolver - derives meaningful project IDs from Claude project directory names

Claude Code stores sessions in ~/.claude/projects/{encoded-path}/{session}.jsonl
The encoded path uses dashes instead of path separators.
This module maps those encoded paths to meaningful project IDs.
"""

import re

# Known project directory mappings
# Keys are the encoded directory names from ~/.claude/projects/
# (dashes replace path separators, e.g. "/Users/you/Projects/myapp" → "-Users-you-Projects-myapp")
# Add your own project paths here to give them meaningful IDs.
PROJECT_MAPPING: dict[str, str] = {}


def resolve_project_id(project_dir_name: str) -> str:
    """
    Resolve a Claude project directory name to a meaningful project ID.

    Lookup order:
    1. Exact match in PROJECT_MAPPING
    2. Decode path and extract last meaningful path segment
    3. Fallback to "default"

    Args:
        project_dir_name: The directory name from ~/.claude/projects/
                         e.g. "-Users-you-Projects-myapp"

    Returns:
        Meaningful project ID string
    """
    if not project_dir_name:
        return "default"

    # 1. Exact match
    if project_dir_name in PROJECT_MAPPING:
        return PROJECT_MAPPING[project_dir_name]

    # 2. Decode path and extract segment after CC/
    # Encoded format: dashes replace path separators
    # e.g. "-Users-you-Projects-SomeProject" → extract "SomeProject"
    decoded = _decode_project_path(project_dir_name)
    if decoded:
        return decoded

    # 3. Fallback
    return "default"


def _decode_project_path(dir_name: str) -> str:
    """
    Attempt to decode an encoded project path and extract the project segment.

    Looks for the pattern CC/{project} in the decoded path.

    Args:
        dir_name: Encoded directory name

    Returns:
        Project ID string or empty string if decoding fails
    """
    # Try to find CC- in the encoded name and take what follows
    match = re.search(r'-CC-(.+)$', dir_name)
    if not match:
        return ""

    after_cc = match.group(1)

    # Take the first segment (before any further dashes that look like path separators)
    # But preserve dashes within names like "Passive-Income"
    # Heuristic: segments after CC that start with a capital letter are project names
    # Sub-paths have additional dashes followed by more segments

    # Split on pattern that looks like path separator (dash followed by uppercase or underscore)
    # e.g. "Passive-Income" stays together but "MyProject---subdir" splits
    parts = re.split(r'---', after_cc, maxsplit=1)
    project_name = parts[0]

    if not project_name:
        return ""

    return project_name
