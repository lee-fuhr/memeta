"""Import memories from a directory of markdown files."""
from pathlib import Path

from memory_system.importers.base import BaseImporter, ImportResult, ImportPreview
from memory_system.memory_ts_client import Memory


class MarkdownDirectoryImporter(BaseImporter):
    """Imports .md files from a directory as individual memories."""

    def import_source(self, path: Path) -> ImportResult:
        """Import all .md files from directory.

        Recursively scans for .md files, parses frontmatter if present,
        extracts content, and creates memory entries via the client.
        """
        md_files = sorted(path.rglob("*.md"))
        total = len(md_files)

        imported = 0
        skipped = 0
        errors: list[str] = []
        memories: list[Memory] = []

        for i, md_file in enumerate(md_files):
            try:
                content, metadata = self._read_file(md_file)
            except (UnicodeDecodeError, ValueError):
                skipped += 1
                if self._progress_callback:
                    self._progress_callback(i + 1, total)
                continue

            if not content or not content.strip():
                skipped += 1
                if self._progress_callback:
                    self._progress_callback(i + 1, total)
                continue

            if self._is_duplicate(content):
                skipped += 1
                if self._progress_callback:
                    self._progress_callback(i + 1, total)
                continue

            importance = metadata.get("importance")
            if importance is not None:
                importance = float(importance)
            else:
                importance = self._guess_importance(content)

            tags = self._resolve_tags(metadata, md_file.name)

            domain = metadata.get("domain", "learnings")
            context_type = metadata.get("type", "knowledge")

            try:
                mem = self._client.create(
                    content=content,
                    project_id=self.project_id,
                    tags=tags,
                    importance=importance,
                    context_type=context_type,
                    knowledge_domain=domain,
                )
                memories.append(mem)
                imported += 1
            except Exception as exc:
                errors.append(f"{md_file.name}: {exc}")

            if self._progress_callback:
                self._progress_callback(i + 1, total)

        return ImportResult(
            imported=imported,
            skipped=skipped,
            errors=errors,
            memories=memories,
        )

    def dry_run(self, path: Path) -> ImportPreview:
        """Preview import without writing."""
        md_files = sorted(path.rglob("*.md"))

        would_import = 0
        would_skip = 0
        samples: list[Memory] = []

        for md_file in md_files:
            try:
                content, metadata = self._read_file(md_file)
            except (UnicodeDecodeError, ValueError):
                would_skip += 1
                continue

            if not content or not content.strip():
                would_skip += 1
                continue

            if self._is_duplicate(content):
                would_skip += 1
                continue

            would_import += 1

            if len(samples) < 5:
                importance = metadata.get("importance")
                if importance is not None:
                    importance = float(importance)
                else:
                    importance = self._guess_importance(content)

                tags = self._resolve_tags(metadata, md_file.name)

                samples.append(
                    Memory(
                        id=f"preview-{would_import}",
                        content=content,
                        importance=importance,
                        tags=tags,
                        project_id=self.project_id,
                    )
                )

        return ImportPreview(
            would_import=would_import,
            would_skip=would_skip,
            sample_memories=samples,
        )

    def _read_file(self, filepath: Path) -> tuple[str, dict]:
        """Read a markdown file, returning (content, metadata).

        Parses YAML frontmatter if present. Raises UnicodeDecodeError
        for binary files or ValueError for unparseable frontmatter.
        """
        raw = filepath.read_text(encoding="utf-8")

        metadata: dict = {}
        content = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                content = parts[2].strip()
                metadata = self._parse_frontmatter(frontmatter_text)

        return content, metadata

    def _parse_frontmatter(self, text: str) -> dict:
        """Parse simple YAML frontmatter into a dict."""
        result: dict = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Parse list values (safe: no eval)
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                if inner:
                    value = [item.strip().strip("'\"") for item in inner.split(",")]
                else:
                    value = []
            # Parse numeric values only for known numeric fields
            elif isinstance(value, str) and key in ("importance", "confidence", "priority"):
                try:
                    value = float(value)
                except ValueError:
                    pass

            result[key] = value
        return result

    def _guess_importance(self, content: str) -> float:
        """Guess importance from content characteristics."""
        score = 0.5  # baseline
        if len(content) > 500:
            score += 0.1
        if content.count("#") >= 3:
            score += 0.1
        if "```" in content:
            score += 0.1
        return min(score, 0.95)

    def _tags_from_filename(self, filename: str) -> list[str]:
        """Extract tags from filename patterns."""
        tags = ["#imported", "#source:markdown"]
        name = filename.lower().replace(".md", "")
        if "guide" in name or "how-to" in name:
            tags.append("#guide")
        if "api" in name:
            tags.append("#api")
        if "config" in name or "setup" in name:
            tags.append("#configuration")
        return tags

    def _resolve_tags(self, metadata: dict, filename: str) -> list[str]:
        """Combine frontmatter tags with filename-derived tags."""
        tags = self._tags_from_filename(filename)
        fm_tags = metadata.get("tags", [])
        if isinstance(fm_tags, list):
            for t in fm_tags:
                if t not in tags:
                    tags.append(t)
        return tags
