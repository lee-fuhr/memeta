#!/usr/bin/env bash
# memeta.sh — CLI wrapper that activates the venv and runs memeta commands
# Usage: ./scripts/memeta.sh <command> [args...]
# Examples:
#   ./scripts/memeta.sh search "how does clustering work"
#   ./scripts/memeta.sh test
#   ./scripts/memeta.sh dashboard
#   ./scripts/memeta.sh maintenance

set -euo pipefail

VENV_DIR="${MEMETA_VENV:-$HOME/.local/venvs/memory-system}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: venv not found at $VENV_DIR"
    echo "Create it with: python3 -m venv $VENV_DIR && $VENV_DIR/bin/pip install -e '.[test]'"
    exit 1
fi

# Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    test)
        cd "$PROJECT_DIR"
        python -m pytest tests/ -q --ignore=tests/wild --tb=short "$@"
        ;;
    test-verbose)
        cd "$PROJECT_DIR"
        python -m pytest tests/ -v --ignore=tests/wild --tb=long "$@"
        ;;
    test-wild)
        cd "$PROJECT_DIR"
        python -m pytest tests/wild/ -v --tb=short "$@"
        ;;
    dashboard)
        cd "$PROJECT_DIR"
        python dashboard/server.py "$@"
        ;;
    maintenance)
        cd "$PROJECT_DIR"
        python scripts/run_daily_maintenance.py "$@"
        ;;
    nightly)
        cd "$PROJECT_DIR"
        python scripts/nightly_maintenance_master.py "$@"
        ;;
    consolidate)
        cd "$PROJECT_DIR"
        python scripts/consolidation_worker.py "$@"
        ;;
    search)
        cd "$PROJECT_DIR"
        python -c "
from memory_system.hybrid_search import HybridSearch
hs = HybridSearch()
results = hs.search('$*', top_k=10)
for r in results:
    print(f'{r.score:.3f}  {r.memory_id}  {r.title}')
"
        ;;
    help|--help|-h)
        echo "memeta.sh — CLI wrapper for the Memeta memory system"
        echo ""
        echo "Usage: $0 <command> [args...]"
        echo ""
        echo "Commands:"
        echo "  test            Run test suite (excludes wild tests)"
        echo "  test-verbose    Run test suite with verbose output"
        echo "  test-wild       Run experimental/wild tests only"
        echo "  dashboard       Start the Flask dashboard on :8766"
        echo "  maintenance     Run daily maintenance scripts"
        echo "  nightly         Run nightly maintenance master"
        echo "  consolidate     Run memory consolidation worker"
        echo "  search <query>  Search memories with hybrid search"
        echo "  help            Show this help message"
        echo ""
        echo "Any other command is passed directly to the memeta CLI:"
        echo "  $0 add --type insight --content '...'"
        echo ""
        echo "Environment:"
        echo "  MEMETA_VENV     Override venv path (default: ~/.local/venvs/memory-system)"
        ;;
    *)
        # Pass through to memeta CLI
        memeta "$COMMAND" "$@"
        ;;
esac
