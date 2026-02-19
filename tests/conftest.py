"""
Conftest for cross-project-sharing worktree.

The editable install points to a different worktree, so new modules
in this worktree's src/ aren't automatically discoverable. This
conftest patches the import path so that modules unique to this
worktree can be found.
"""
import sys
from pathlib import Path

# Insert this worktree's src/ at the front of sys.path so that
# `from memory_system.cross_project_sharing_db import ...` resolves here
# when the module doesn't exist in the editable-install target.
_src = str(Path(__file__).resolve().parent.parent / "src")

# We need to register the new module under memory_system namespace.
# The editable finder already maps memory_system -> some other worktree's src/.
# For new modules, we import memory_system and add our src to its __path__.
import memory_system
if _src not in memory_system.__path__:
    memory_system.__path__.insert(0, _src)
