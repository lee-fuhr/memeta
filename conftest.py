"""Root conftest.py - shared fixtures for all tests.

Patches the memory_system package path so that modules unique to this
worktree (e.g. self_test.py) are importable alongside the editable install
from the main worktree.
"""

import sys
from pathlib import Path

# Insert this worktree's src/ at the FRONT of memory_system.__path__
# so local modules shadow / supplement the editable-install mapping.
_local_src = str(Path(__file__).parent / "src")

import memory_system  # noqa: E402

if _local_src not in memory_system.__path__:
    memory_system.__path__.insert(0, _local_src)
