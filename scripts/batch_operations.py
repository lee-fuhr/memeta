#!/usr/bin/env python3
"""
Batch memory operations - Bulk import/export/tag/archive via CLI.

Feature 20: Efficient bulk operations on memories.

Usage:
  python batch_operations.py export --output memories.json
  python batch_operations.py import --input memories.json
  python batch_operations.py tag --tag "#client-work" --query "client"
  python batch_operations.py archive --older-than 365
"""

import json
import argparse
from datetime import datetime, timedelta

from memory_system.memory_ts_client import MemoryTSClient


def export_memories(output_file: str, project_id: str = "LFI"):
    """Export all memories to JSON."""
    client = MemoryTSClient(project_id=project_id)
    memories = client.list()

    # Convert to dicts
    memory_dicts = []
    for mem in memories:
        memory_dicts.append({
            'id': mem.id,
            'content': mem.content,
            'importance': mem.importance,
            'tags': mem.tags,
            'scope': mem.scope,
            'project_id': mem.project_id,
            'session_id': getattr(mem, 'session_id', None),
            'created': mem.created.isoformat() if hasattr(mem.created, 'isoformat') else str(mem.created)
        })

    # Write to file
    with open(output_file, 'w') as f:
        json.dump(memory_dicts, f, indent=2)

    print(f"✅ Exported {len(memory_dicts)} memories to {output_file}")


def import_memories(input_file: str, project_id: str = "LFI"):
    """Import memories from JSON."""
    client = MemoryTSClient(project_id=project_id)

    with open(input_file) as f:
        memory_dicts = json.load(f)

    imported = 0
    for mem_dict in memory_dicts:
        try:
            client.create(
                content=mem_dict['content'],
                project_id=mem_dict.get('project_id', project_id),
                importance=mem_dict.get('importance', 0.7),
                tags=mem_dict.get('tags', []),
                scope=mem_dict.get('scope', 'project'),
                session_id=mem_dict.get('session_id')
            )
            imported += 1
        except Exception as e:
            print(f"⚠️  Failed to import: {mem_dict.get('content', '')[:50]}... - {e}")

    print(f"✅ Imported {imported}/{len(memory_dicts)} memories")


def bulk_tag(tag: str, query: str, project_id: str = "LFI"):
    """Add tag to all memories matching query."""
    client = MemoryTSClient(project_id=project_id)
    memories = client.search(query=query, project_id=project_id)

    tagged = 0
    for mem in memories:
        if tag not in mem.tags:
            new_tags = mem.tags + [tag]
            client.update(mem.id, tags=new_tags)
            tagged += 1

    print(f"✅ Tagged {tagged} memories with {tag}")


def bulk_archive(older_than_days: int, project_id: str = "LFI"):
    """Archive memories older than N days."""
    client = MemoryTSClient(project_id=project_id)
    all_memories = client.list()

    cutoff = datetime.now() - timedelta(days=older_than_days)
    archived = 0

    for mem in all_memories:
        created = mem.created
        if isinstance(created, str):
            created = datetime.fromisoformat(created)

        if created < cutoff:
            client.update(mem.id, scope="archived")
            archived += 1

    print(f"✅ Archived {archived} memories older than {older_than_days} days")


def main():
    parser = argparse.ArgumentParser(description="Batch memory operations")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Export command
    export_parser = subparsers.add_parser('export', help='Export memories to JSON')
    export_parser.add_argument('--output', required=True, help='Output file path')
    export_parser.add_argument('--project', default='LFI', help='Project ID')

    # Import command
    import_parser = subparsers.add_parser('import', help='Import memories from JSON')
    import_parser.add_argument('--input', required=True, help='Input file path')
    import_parser.add_argument('--project', default='LFI', help='Project ID')

    # Tag command
    tag_parser = subparsers.add_parser('tag', help='Add tag to matching memories')
    tag_parser.add_argument('--tag', required=True, help='Tag to add')
    tag_parser.add_argument('--query', required=True, help='Search query')
    tag_parser.add_argument('--project', default='LFI', help='Project ID')

    # Archive command
    archive_parser = subparsers.add_parser('archive', help='Archive old memories')
    archive_parser.add_argument('--older-than', type=int, required=True, help='Days threshold')
    archive_parser.add_argument('--project', default='LFI', help='Project ID')

    args = parser.parse_args()

    if args.command == 'export':
        export_memories(args.output, args.project)
    elif args.command == 'import':
        import_memories(args.input, args.project)
    elif args.command == 'tag':
        bulk_tag(args.tag, args.query, args.project)
    elif args.command == 'archive':
        bulk_archive(args.older_than, args.project)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
