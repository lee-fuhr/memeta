"""CLI entry point for memeta.

Provides the ``memeta`` command with argparse subcommands:

- ``memeta init``           — run setup wizard
- ``memeta search "query"`` — search memories
- ``memeta import <type>``  — import from external sources
- ``memeta generate``       — generate outputs (e.g. CLAUDE.md learnings)
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the appropriate subcommand.

    Args:
        argv: Argument list. Defaults to ``sys.argv[1:]`` when *None*.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = argparse.ArgumentParser(
        prog="memeta",
        description="Memeta memory system CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ── init ─────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser("init", help="Initialize memeta")
    init_parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmations"
    )

    # ── search ───────────────────────────────────────────────────────────
    search_parser = subparsers.add_parser("search", help="Search memories")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--domain", help="Filter by domain")
    search_parser.add_argument(
        "--tag", action="append", help="Filter by tag (repeatable)"
    )
    search_parser.add_argument(
        "--min-importance", type=float, help="Minimum importance"
    )
    search_parser.add_argument("--context-type", help="Filter by context type")
    search_parser.add_argument(
        "--limit", type=int, default=10, help="Max results"
    )
    search_parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset"
    )
    search_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON output"
    )
    search_parser.add_argument(
        "--full", action="store_true", help="Full memory output"
    )
    search_parser.add_argument(
        "--ids", action="store_true", help="IDs only output"
    )

    # ── import ───────────────────────────────────────────────────────────
    import_parser = subparsers.add_parser("import", help="Import memories")
    import_parser.add_argument(
        "type", choices=["markdown", "claude-md"], help="Import type"
    )
    import_parser.add_argument("path", help="Source path")
    import_parser.add_argument(
        "--project", default="LFI", help="Project ID"
    )
    import_parser.add_argument(
        "--dry-run", action="store_true", help="Preview only"
    )

    # ── generate ─────────────────────────────────────────────────────────
    gen_parser = subparsers.add_parser("generate", help="Generate outputs")
    gen_sub = gen_parser.add_subparsers(dest="generate_type")

    claude_parser = gen_sub.add_parser(
        "claude-md", help="Generate CLAUDE.md learnings"
    )
    claude_parser.add_argument("--path", help="CLAUDE.md path")
    claude_parser.add_argument(
        "--min-importance", type=float, default=0.7
    )
    claude_parser.add_argument("--dry-run", action="store_true")

    # ── Parse and dispatch ───────────────────────────────────────────────
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "init":
        return _cmd_init(args)
    elif args.command == "search":
        return _cmd_search(args)
    elif args.command == "import":
        return _cmd_import(args)
    elif args.command == "generate":
        return _cmd_generate(args)

    return 0


# ── Subcommand handlers ─────────────────────────────────────────────────


def _cmd_init(args: argparse.Namespace) -> int:
    """Run the setup wizard."""
    try:
        from memory_system.setup_wizard import InitWizard
    except ImportError:
        print("Error: setup_wizard module not available.", file=sys.stderr)
        return 1

    wizard = InitWizard(auto_confirm=args.yes)
    result = wizard.run()

    for check in result.checks:
        status = "ok" if check.passed else ("warn" if not check.required else "FAIL")
        print(f"  [{status}] {check.name}: {check.message}")

    if result.directories_created:
        print(f"\nDirectories created: {len(result.directories_created)}")

    if result.config_path:
        print(f"Config: {result.config_path}")

    for w in result.warnings:
        print(f"  Warning: {w}", file=sys.stderr)

    for e in result.errors:
        print(f"  Error: {e}", file=sys.stderr)

    return 0 if result.success else 1


def _cmd_search(args: argparse.Namespace) -> int:
    """Execute a memory search and print results."""
    try:
        from memory_system.search_cli import SearchCLI
    except ImportError:
        print("Error: search_cli module not available.", file=sys.stderr)
        return 1

    cli = SearchCLI()
    results = cli.execute_search(
        query=args.query,
        domain=args.domain,
        tags=args.tag,
        min_importance=args.min_importance,
        context_type=args.context_type,
        limit=args.limit,
        offset=args.offset,
    )

    if args.json_output:
        print(cli.format_json(results))
    elif args.full:
        print(cli.format_full(results))
    elif args.ids:
        output = cli.format_ids(results)
        if output:
            print(output)
    else:
        print(cli.format_table(results, args.query))

    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    """Import memories from an external source."""
    from pathlib import Path

    path = Path(args.path)

    try:
        if args.type == "markdown":
            from memory_system.importers.markdown_importer import MarkdownDirectoryImporter
            importer = MarkdownDirectoryImporter(project_id=args.project)
        elif args.type == "claude-md":
            from memory_system.importers.claude_md_importer import ClaudeMdImporter
            importer = ClaudeMdImporter(project_id=args.project)
        else:
            print(f"Error: unknown import type '{args.type}'.", file=sys.stderr)
            return 1
    except ImportError:
        print(f"Error: importer for '{args.type}' not available.", file=sys.stderr)
        return 1

    if args.dry_run:
        preview = importer.dry_run(path)
        print(f"Would import: {preview.would_import}")
        print(f"Would skip: {preview.would_skip}")
        if preview.sample_memories:
            print(f"\nSample ({len(preview.sample_memories)}):")
            for mem in preview.sample_memories:
                print(f"  - {mem.content[:80]}")
        return 0

    result = importer.import_source(path)
    print(f"Imported: {result.imported}")
    print(f"Skipped: {result.skipped}")
    if result.errors:
        for err in result.errors:
            print(f"  Error: {err}", file=sys.stderr)
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    """Generate outputs from memory data."""
    if not hasattr(args, "generate_type") or args.generate_type is None:
        print("Error: specify a generate sub-command (e.g. 'claude-md').", file=sys.stderr)
        return 1

    if args.generate_type == "claude-md":
        try:
            from memory_system.learnings_generator import LearningsGenerator
            from pathlib import Path
        except ImportError:
            print("Error: learnings_generator module not available.", file=sys.stderr)
            return 1

        claude_md_path = Path(args.path) if getattr(args, "path", None) else None
        gen = LearningsGenerator(
            claude_md_path=claude_md_path,
            min_importance=args.min_importance,
        )
        result = gen.apply_to_claude_md(dry_run=args.dry_run)

        print(f"Memories: {result['memory_count']}")
        if args.dry_run:
            print("(dry run — no changes written)")
            print(result["content"])
        elif result.get("written"):
            print(f"Written to: {gen.claude_md_path}")
        elif result.get("error"):
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1

        return 0

    return 1
