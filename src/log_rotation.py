"""
Log rotation for hook event logs

Rotates JSONL log files when they exceed a configurable line threshold.
Archives old content to timestamped gzip files.
"""

import gzip
import shutil
from datetime import datetime
from pathlib import Path


def maybe_rotate_log(log_file: Path, max_lines: int = 10_000) -> bool:
    """
    Rotate log file if it exceeds max_lines.

    Archives current content to a timestamped .gz file in the same directory,
    then truncates the original.

    Args:
        log_file: Path to the log file
        max_lines: Maximum lines before rotation (default: 10,000)

    Returns:
        True if rotation occurred, False otherwise
    """
    if not log_file.exists():
        return False

    # Count lines
    line_count = 0
    with open(log_file, "r") as f:
        for _ in f:
            line_count += 1
            if line_count > max_lines:
                break

    if line_count <= max_lines:
        return False

    # Build archive filename
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{log_file.stem}-{timestamp}.jsonl.gz"
    archive_path = log_file.parent / archive_name

    # Compress current log to archive
    with open(log_file, "rb") as f_in:
        with gzip.open(archive_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    # Truncate original
    log_file.write_text("")

    return True
