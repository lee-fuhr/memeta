"""Root conftest.py - shared fixtures for all tests.

When running from a git worktree, the editable install may point to
the main worktree's memory_system package. This conftest ensures that
new modules from THIS worktree's src/ are available under the
memory_system namespace.
"""

import importlib.util
import sys
from pathlib import Path

_WORKTREE_SRC = Path(__file__).parent / "src"


def _register_worktree_module(module_name: str, filename: str):
    """Register a module from this worktree's src/ under memory_system."""
    full_name = f"memory_system.{module_name}"
    if full_name in sys.modules:
        return
    filepath = _WORKTREE_SRC / filename
    if not filepath.exists():
        return
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)


# Register new modules that only exist in this worktree
_register_worktree_module("relevance_explanation", "relevance_explanation.py")

# Also reload hybrid_search from this worktree so its import of
# relevance_explanation resolves correctly
_hs_path = _WORKTREE_SRC / "hybrid_search.py"
if _hs_path.exists():
    spec = importlib.util.spec_from_file_location(
        "memory_system.hybrid_search", str(_hs_path)
    )
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules["memory_system.hybrid_search"] = mod
        spec.loader.exec_module(mod)
        # Also update the shorthand import used by existing tests
        import memory_system
        memory_system.hybrid_search = mod
