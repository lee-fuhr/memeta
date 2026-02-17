# Contributing to Total Recall

Thanks for your interest in contributing.

## Getting started

```bash
git clone https://github.com/leefuhr/total-recall
cd total-recall

python3 -m venv ~/.local/venvs/total-recall
source ~/.local/venvs/total-recall/bin/activate
pip install -e ".[test]"

# Run tests (exclude wild LLM-dependent tests)
pytest tests/ --ignore=tests/wild -q
```

## Development guidelines

- **Tests required** — all new features need tests; run `pytest tests/ --ignore=tests/wild -q` before submitting
- **Import convention** — use full package paths: `from memory_system.intelligence.summarization import ...`
- **Config over hardcoding** — use `cfg` from `memory_system.config` for any paths or project IDs; never hardcode personal paths
- **No sys.path hacks** — the package is installed via `pip install -e .`; rely on that

## Running the dashboard

```bash
pip install flask
python3 dashboard/server.py --port 7860 --project default
```

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Make your changes with tests
3. Open a pull request with a clear description of what changed and why

## Known flaky tests

Two tests depend on LLM timeouts and are pre-existing flaky:
- `tests/test_session_consolidator.py::TestDeduplication::test_deduplicate_against_existing`
- `tests/wild/test_dream_synthesizer.py::test_temporal_connection_discovery`

These are not bugs — skip them with `--ignore=tests/wild` or accept occasional failures.
