# F29: Memory Import/Export - Implementation Plan

**Status:** Planning Complete
**Estimated Time:** 8 hours
**Test Count:** 15 tests planned

---

## Problem Statement

Users cannot:
- Move memories between systems
- Backup memories in portable format
- Import existing notes from Obsidian/Roam/Notion
- Share memory collections with others
- Recover from system corruption

Without import/export, memories are locked in the system.

---

## Goals

1. Export memories to JSON/CSV formats
2. Import from JSON (universal format)
3. Import from Obsidian markdown vaults
4. Import from Notion exports
5. Intelligent deduplication during import
6. Maintain provenance (source system, import date)
7. Conflict resolution strategies

---

## Database Schema

```sql
CREATE TABLE import_history (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,  -- json, obsidian, roam, notion
    file_path TEXT,
    memory_count INTEGER,
    duplicates_found INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX idx_import_source ON import_history(source_system);
CREATE INDEX idx_import_date ON import_history(created_at DESC);
```

---

## API Design

### Core Methods

```python
class MemoryImportExport:
    """
    Import/export memories in various formats.

    Supported formats:
    - JSON: Universal interchange format
    - CSV: Spreadsheet-compatible format
    - Obsidian: Markdown vault import
    - Notion: Export ZIP import
    """

    def __init__(self, memory_client: Optional[MemoryTSClient] = None):
        """Initialize importer/exporter"""

    # === Export Methods ===

    def export_to_json(
        self,
        output_path: Path,
        project_id: Optional[str] = None,
        include_metadata: bool = True
    ) -> int:
        """
        Export memories to JSON file.

        Format:
        {
          "export_metadata": {
            "timestamp": "2026-02-13T18:00:00Z",
            "memory_count": 150,
            "project_id": "proj-1",
            "system_version": "0.4.0"
          },
          "memories": [
            {
              "id": "mem-001",
              "content": "...",
              "tags": ["tag1", "tag2"],
              "project_id": "proj-1",
              "importance": 0.8,
              "created_at": "2026-01-15T10:30:00Z",
              "embedding": [0.1, 0.2, ...]  // Optional
            },
            ...
          ]
        }

        Args:
            output_path: Path to output JSON file
            project_id: Export only this project (optional)
            include_metadata: Include system metadata (default: True)

        Returns:
            Number of memories exported
        """

    def export_to_csv(
        self,
        output_path: Path,
        project_id: Optional[str] = None
    ) -> int:
        """
        Export memories to CSV file.

        Columns: id, content, tags, project_id, importance, created_at

        Args:
            output_path: Path to output CSV file
            project_id: Export only this project (optional)

        Returns:
            Number of memories exported
        """

    # === Import Methods ===

    def import_from_json(
        self,
        file_path: Path,
        merge_strategy: str = "dedupe",
        project_id: Optional[str] = None
    ) -> dict:
        """
        Import memories from JSON file.

        Merge strategies:
        - "dedupe": Skip duplicates (default)
        - "update": Update existing memories
        - "keep_both": Import everything, create duplicates

        Args:
            file_path: Path to JSON file
            merge_strategy: How to handle duplicates
            project_id: Assign all imports to this project (optional)

        Returns:
            {
              "imported": 120,
              "skipped": 5,
              "updated": 3,
              "errors": 2,
              "import_id": "import-uuid"
            }
        """

    def import_from_obsidian(
        self,
        vault_path: Path,
        project_id: Optional[str] = None,
        include_dailies: bool = False
    ) -> dict:
        """
        Import from Obsidian vault.

        Algorithm:
        1. Scan vault for .md files
        2. Extract YAML frontmatter (tags, dates)
        3. Convert markdown to plain text
        4. Extract wikilinks [[...]] as related memories
        5. Import each note as a memory

        Args:
            vault_path: Path to Obsidian vault root
            project_id: Assign all imports to this project
            include_dailies: Import daily notes (default: False)

        Returns:
            {
              "imported": 150,
              "skipped": 10,
              "errors": 0,
              "import_id": "import-uuid"
            }
        """

    def import_from_notion(
        self,
        export_zip: Path,
        project_id: Optional[str] = None
    ) -> dict:
        """
        Import from Notion export ZIP.

        Algorithm:
        1. Extract ZIP to temp directory
        2. Parse CSV export (if present)
        3. Parse markdown files
        4. Extract properties from Notion blocks
        5. Import as memories

        Args:
            export_zip: Path to Notion export ZIP file
            project_id: Assign all imports to this project

        Returns:
            {
              "imported": 200,
              "skipped": 15,
              "errors": 5,
              "import_id": "import-uuid"
            }
        """

    def import_from_csv(
        self,
        file_path: Path,
        column_mapping: Optional[dict] = None,
        project_id: Optional[str] = None
    ) -> dict:
        """
        Import from CSV file.

        Default column mapping:
        - "content" or "note" → content
        - "tags" → tags (comma-separated)
        - "project" → project_id
        - "importance" → importance
        - "date" or "created" → created_at

        Args:
            file_path: Path to CSV file
            column_mapping: Custom column mapping (optional)
            project_id: Assign all imports to this project

        Returns:
            Import statistics dict
        """

    # === Utility Methods ===

    def get_import_history(self, limit: int = 10) -> List[dict]:
        """Get recent import history"""

    def validate_json_export(self, file_path: Path) -> dict:
        """
        Validate JSON export file format.

        Returns:
            {
              "valid": True/False,
              "memory_count": 150,
              "errors": ["Missing required field: content", ...]
            }
        """

    def _detect_duplicate(self, memory_content: str) -> Optional[str]:
        """
        Detect if memory already exists.

        Uses:
        1. Exact content match (SHA-256 hash)
        2. High semantic similarity (>0.9)

        Returns:
            Existing memory ID or None
        """

    def _log_import(
        self,
        source_system: str,
        file_path: str,
        memory_count: int,
        duplicates_found: int
    ) -> str:
        """Log import to database, return import_id"""
```

---

## Data Formats

### JSON Export Format

```json
{
  "export_metadata": {
    "timestamp": "2026-02-13T18:00:00Z",
    "memory_count": 150,
    "project_id": "proj-1",
    "system_version": "0.4.0"
  },
  "memories": [
    {
      "id": "mem-001",
      "content": "Important project insight about architecture decisions.",
      "tags": ["architecture", "decisions"],
      "project_id": "proj-1",
      "importance": 0.8,
      "created_at": "2026-01-15T10:30:00Z",
      "embedding": null
    }
  ]
}
```

### CSV Export Format

```csv
id,content,tags,project_id,importance,created_at
mem-001,"Important insight","tag1,tag2",proj-1,0.8,2026-01-15T10:30:00Z
```

### Obsidian Note Format

```markdown
---
tags: [project, architecture]
created: 2026-01-15
---

# Architecture Decisions

Important project insight about microservices.

Related: [[previous-decision]], [[team-discussion]]
```

---

## Integration Points

### Dependencies
- **MemoryTSClient**: Create/search memories
- **IntelligenceDB**: Store import history
- **Semantic Search**: Detect duplicates

### Consumers
- **Backup Scripts**: Nightly JSON exports
- **Migration Tools**: Move from other systems
- **Collaboration**: Share memory collections

---

## Test Plan

### Export Tests (4 tests)
1. `test_export_to_json_basic` - Export all memories to JSON
2. `test_export_to_json_project_filter` - Export single project
3. `test_export_to_csv` - CSV format with proper escaping
4. `test_export_empty_database` - Export with no memories → empty file

### JSON Import Tests (4 tests)
5. `test_import_from_json_basic` - Basic JSON import
6. `test_import_dedupe_strategy` - Skip duplicates
7. `test_import_update_strategy` - Update existing memories
8. `test_import_invalid_json` - Malformed JSON → error dict

### Obsidian Import Tests (3 tests)
9. `test_import_from_obsidian_vault` - Full vault import
10. `test_import_obsidian_frontmatter` - YAML metadata extraction
11. `test_import_obsidian_skip_dailies` - Skip daily notes folder

### CSV Import Tests (2 tests)
12. `test_import_from_csv_basic` - CSV with default columns
13. `test_import_from_csv_custom_mapping` - Custom column mapping

### Utility Tests (2 tests)
14. `test_get_import_history` - Recent imports
15. `test_detect_duplicate` - Exact and semantic matching

---

## Edge Cases & Error Handling

1. **Empty export** → Create valid JSON with empty memories array
2. **Malformed JSON** → Return error dict with parse errors
3. **Missing required fields** → Skip row, log error
4. **Duplicate imports** → Follow merge strategy
5. **Large files** → Stream processing (don't load all in memory)
6. **Invalid dates** → Use current timestamp
7. **Special characters** → Proper CSV escaping
8. **Binary content** → Skip, log warning
9. **Circular wikilinks** → Flatten to list of link names
10. **Notion nested blocks** → Flatten to plain text

---

## Performance Considerations

**At scale:**
- Batch imports: 1000 memories per transaction
- Stream large files: Don't load entire file into memory
- Parallel processing: Import chunks in parallel
- Progress callbacks: Report progress every 100 memories

**Optimization:**
- Pre-compute content hashes for duplicate detection
- Cache semantic embeddings during import
- Use bulk insert for large imports

---

## Success Criteria

1. ✅ Export 10K memories to JSON in <5 seconds
2. ✅ Import 10K memories from JSON in <60 seconds
3. ✅ Correctly parse Obsidian YAML frontmatter
4. ✅ Detect 100% of exact duplicates
5. ✅ Detect >90% of semantic duplicates (similarity >0.9)
6. ✅ All 15 tests passing
7. ✅ No data loss during export/import round trip

---

## Future Enhancements

- **Roam Research import:** Parse JSON export
- **Logseq import:** Markdown with block refs
- **Evernote import:** ENEX format
- **Google Keep import:** JSON export
- **Incremental sync:** Only import new/changed memories
- **Conflict UI:** Visual diff for merge conflicts
- **Encryption:** Export with password protection
- **Compression:** Export as .tar.gz

---

## Implementation Checklist

- [ ] Create `src/intelligence/import_export.py`
- [ ] Add `import_history` table to IntelligenceDB
- [ ] Implement JSON export
- [ ] Implement CSV export
- [ ] Implement JSON import with dedupe
- [ ] Implement Obsidian import
- [ ] Implement Notion import (basic)
- [ ] Implement CSV import
- [ ] Implement duplicate detection
- [ ] Create `tests/intelligence/test_import_export.py`
- [ ] Write all 15 tests
- [ ] Run and verify tests passing
- [ ] Update CHANGELOG.md
- [ ] Update SHOWCASE.md
- [ ] Update PLAN.md
- [ ] Commit changes
