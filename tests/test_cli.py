"""Tests for cli.py — memeta CLI entry point with argparse subcommands."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from memory_system.cli import main


class TestCLINoArgs:
    """Tests for CLI with no arguments."""

    def test_no_args_returns_1(self):
        """Running with no args returns exit code 1."""
        result = main([])
        assert result == 1

    def test_no_args_prints_help(self, capsys):
        """Running with no args prints usage help."""
        main([])
        captured = capsys.readouterr()
        assert "memeta" in captured.out.lower() or "usage" in captured.out.lower()


class TestCLISearchParsing:
    """Tests for search subcommand argument parsing."""

    @patch("memory_system.cli._cmd_search")
    def test_search_basic_query(self, mock_search):
        """search subcommand parses query positional arg."""
        mock_search.return_value = 0
        main(["search", "python tips"])
        args = mock_search.call_args[0][0]
        assert args.query == "python tips"
        assert args.command == "search"

    @patch("memory_system.cli._cmd_search")
    def test_search_with_domain_filter(self, mock_search):
        """search --domain parses correctly."""
        mock_search.return_value = 0
        main(["search", "query", "--domain", "engineering"])
        args = mock_search.call_args[0][0]
        assert args.domain == "engineering"

    @patch("memory_system.cli._cmd_search")
    def test_search_with_tags(self, mock_search):
        """search --tag is repeatable and accumulates."""
        mock_search.return_value = 0
        main(["search", "query", "--tag", "python", "--tag", "dev"])
        args = mock_search.call_args[0][0]
        assert args.tag == ["python", "dev"]

    @patch("memory_system.cli._cmd_search")
    def test_search_with_json_output(self, mock_search):
        """search --json sets json_output flag."""
        mock_search.return_value = 0
        main(["search", "query", "--json"])
        args = mock_search.call_args[0][0]
        assert args.json_output is True

    @patch("memory_system.cli._cmd_search")
    def test_search_with_limit_and_offset(self, mock_search):
        """search --limit and --offset parse as integers."""
        mock_search.return_value = 0
        main(["search", "query", "--limit", "5", "--offset", "10"])
        args = mock_search.call_args[0][0]
        assert args.limit == 5
        assert args.offset == 10

    @patch("memory_system.cli._cmd_search")
    def test_search_defaults(self, mock_search):
        """search has correct default values for limit, offset, flags."""
        mock_search.return_value = 0
        main(["search", "query"])
        args = mock_search.call_args[0][0]
        assert args.limit == 10
        assert args.offset == 0
        assert args.json_output is False
        assert args.full is False
        assert args.ids is False

    @patch("memory_system.cli._cmd_search")
    def test_search_full_and_ids_flags(self, mock_search):
        """search --full and --ids flags parse correctly."""
        mock_search.return_value = 0
        main(["search", "query", "--full"])
        args = mock_search.call_args[0][0]
        assert args.full is True

        main(["search", "query", "--ids"])
        args = mock_search.call_args[0][0]
        assert args.ids is True

    @patch("memory_system.cli._cmd_search")
    def test_search_min_importance(self, mock_search):
        """search --min-importance parses as float."""
        mock_search.return_value = 0
        main(["search", "query", "--min-importance", "0.8"])
        args = mock_search.call_args[0][0]
        assert args.min_importance == 0.8

    @patch("memory_system.cli._cmd_search")
    def test_search_context_type(self, mock_search):
        """search --context-type parses correctly."""
        mock_search.return_value = 0
        main(["search", "query", "--context-type", "correction"])
        args = mock_search.call_args[0][0]
        assert args.context_type == "correction"


class TestCLIInitParsing:
    """Tests for init subcommand."""

    @patch("memory_system.cli._cmd_init")
    def test_init_basic(self, mock_init):
        """init subcommand dispatches correctly."""
        mock_init.return_value = 0
        result = main(["init"])
        mock_init.assert_called_once()
        assert result == 0

    @patch("memory_system.cli._cmd_init")
    def test_init_with_yes_flag(self, mock_init):
        """init --yes / -y sets skip confirmations flag."""
        mock_init.return_value = 0
        main(["init", "--yes"])
        args = mock_init.call_args[0][0]
        assert args.yes is True

        main(["init", "-y"])
        args = mock_init.call_args[0][0]
        assert args.yes is True


class TestCLIImportParsing:
    """Tests for import subcommand."""

    @patch("memory_system.cli._cmd_import")
    def test_import_markdown(self, mock_import):
        """import markdown /path parses correctly."""
        mock_import.return_value = 0
        main(["import", "markdown", "/tmp/notes.md"])
        args = mock_import.call_args[0][0]
        assert args.type == "markdown"
        assert args.path == "/tmp/notes.md"

    @patch("memory_system.cli._cmd_import")
    def test_import_claude_md(self, mock_import):
        """import claude-md /path parses correctly."""
        mock_import.return_value = 0
        main(["import", "claude-md", "/tmp/CLAUDE.md"])
        args = mock_import.call_args[0][0]
        assert args.type == "claude-md"
        assert args.path == "/tmp/CLAUDE.md"

    @patch("memory_system.cli._cmd_import")
    def test_import_project_default(self, mock_import):
        """import defaults project to 'default'."""
        mock_import.return_value = 0
        main(["import", "markdown", "/tmp/notes.md"])
        args = mock_import.call_args[0][0]
        assert args.project == "default"

    @patch("memory_system.cli._cmd_import")
    def test_import_dry_run(self, mock_import):
        """import --dry-run sets flag."""
        mock_import.return_value = 0
        main(["import", "markdown", "/tmp/notes.md", "--dry-run"])
        args = mock_import.call_args[0][0]
        assert args.dry_run is True


class TestCLIGenerateParsing:
    """Tests for generate subcommand."""

    @patch("memory_system.cli._cmd_generate")
    def test_generate_claude_md(self, mock_gen):
        """generate claude-md parses correctly."""
        mock_gen.return_value = 0
        main(["generate", "claude-md"])
        args = mock_gen.call_args[0][0]
        assert args.command == "generate"
        assert args.generate_type == "claude-md"

    @patch("memory_system.cli._cmd_generate")
    def test_generate_claude_md_with_path(self, mock_gen):
        """generate claude-md --path sets output path."""
        mock_gen.return_value = 0
        main(["generate", "claude-md", "--path", "/tmp/CLAUDE.md"])
        args = mock_gen.call_args[0][0]
        assert args.path == "/tmp/CLAUDE.md"

    @patch("memory_system.cli._cmd_generate")
    def test_generate_claude_md_defaults(self, mock_gen):
        """generate claude-md has correct defaults."""
        mock_gen.return_value = 0
        main(["generate", "claude-md"])
        args = mock_gen.call_args[0][0]
        assert args.min_importance == 0.7
        assert args.dry_run is False

    @patch("memory_system.cli._cmd_generate")
    def test_generate_no_subtype_returns_1(self, mock_gen):
        """generate with no sub-type returns 1."""
        # generate without a sub-subcommand should error
        mock_gen.return_value = 0
        result = main(["generate"])
        args = mock_gen.call_args[0][0]
        # generate_type should be None when no sub-subcommand given
        assert args.generate_type is None


class TestCLIDispatching:
    """Tests for command dispatching to the right handlers."""

    @patch("memory_system.cli._cmd_search")
    def test_search_dispatches(self, mock_search):
        """search command dispatches to _cmd_search."""
        mock_search.return_value = 0
        main(["search", "query"])
        mock_search.assert_called_once()

    @patch("memory_system.cli._cmd_init")
    def test_init_dispatches(self, mock_init):
        """init command dispatches to _cmd_init."""
        mock_init.return_value = 0
        main(["init"])
        mock_init.assert_called_once()

    @patch("memory_system.cli._cmd_import")
    def test_import_dispatches(self, mock_import):
        """import command dispatches to _cmd_import."""
        mock_import.return_value = 0
        main(["import", "markdown", "/tmp/x.md"])
        mock_import.assert_called_once()

    @patch("memory_system.cli._cmd_generate")
    def test_generate_dispatches(self, mock_gen):
        """generate command dispatches to _cmd_generate."""
        mock_gen.return_value = 0
        main(["generate", "claude-md"])
        mock_gen.assert_called_once()


# ── Integration tests (real handler execution, no mocking) ──────────────


class TestCLIInitIntegration:
    """Integration tests for init handler — exercises real InitWizard."""

    def test_init_runs_wizard_and_returns_0(self, tmp_path, capsys):
        """init handler instantiates InitWizard and runs it."""
        from memory_system.config import MemorySystemConfig

        config = MemorySystemConfig(
            memory_dir=tmp_path / "memory",
            project_id="test",
        )
        with patch("memory_system.setup_wizard.cfg", config):
            result = main(["init", "--yes"])

        captured = capsys.readouterr()
        assert result == 0
        assert "python_version" in captured.out

    def test_init_prints_check_results(self, tmp_path, capsys):
        """init output includes environment check status."""
        from memory_system.config import MemorySystemConfig

        config = MemorySystemConfig(
            memory_dir=tmp_path / "memory",
            project_id="test",
        )
        with patch("memory_system.setup_wizard.cfg", config):
            main(["init"])

        captured = capsys.readouterr()
        assert "[ok]" in captured.out or "[warn]" in captured.out


class TestCLIImportIntegration:
    """Integration tests for import handler — exercises real importers."""

    def test_import_markdown_dry_run(self, tmp_path, capsys):
        """import markdown --dry-run creates importer and returns preview."""
        md_dir = tmp_path / "notes"
        md_dir.mkdir()
        (md_dir / "note.md").write_text("# A useful note\n\nThis is important content.\n")

        result = main([
            "import", "markdown", str(md_dir),
            "--dry-run", "--project", "test",
        ])

        captured = capsys.readouterr()
        assert result == 0
        assert "Would import:" in captured.out

    def test_import_claude_md_dry_run(self, tmp_path, capsys):
        """import claude-md --dry-run parses and previews."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("## Rules\n\n- Always write tests before implementation code\n")

        result = main([
            "import", "claude-md", str(claude_md),
            "--dry-run", "--project", "test",
        ])

        captured = capsys.readouterr()
        assert result == 0
        assert "Would import:" in captured.out


class TestCLIGenerateIntegration:
    """Integration tests for generate handler — exercises real LearningsGenerator."""

    def test_generate_claude_md_dry_run(self, tmp_path, capsys):
        """generate claude-md --dry-run creates generator and returns output."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n\nExisting content.\n")

        result = main([
            "generate", "claude-md",
            "--path", str(claude_md),
            "--dry-run",
        ])

        captured = capsys.readouterr()
        assert result == 0
        assert "Memories:" in captured.out
        assert "dry run" in captured.out

    def test_generate_no_subtype_returns_error(self, capsys):
        """generate without sub-command prints error and returns 1."""
        result = main(["generate"])

        captured = capsys.readouterr()
        assert result == 1
        assert "specify" in captured.err.lower() or "sub-command" in captured.err.lower()
