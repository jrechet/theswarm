"""Hash-anchored file editing for autonomous agents.

Tags file lines with content hashes so agents can reference lines by hash
instead of line numbers, preventing stale-line errors when files change.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# --- Data classes --------------------------------------------------------- #


@dataclass(frozen=True)
class HashlineEdit:
    """A single line edit instruction parsed from LLM output."""

    filepath: str
    line_number: int
    expected_hash: str
    new_content: str


@dataclass
class ApplyResult:
    """Outcome of applying a batch of hashline edits."""

    applied: int = 0
    mismatches: int = 0
    files_modified: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --- Core helpers --------------------------------------------------------- #

_HASH_LEN = 2


def _line_hash(content: str) -> str:
    """Return the first 2 hex chars of SHA-256 of *stripped* content."""
    digest = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
    return digest[:_HASH_LEN]


def validate_hash(line_content: str, expected_hash: str) -> bool:
    """Check whether a line's computed hash matches *expected_hash*."""
    return _line_hash(line_content) == expected_hash


def _safe_path(filepath: str, workspace: str) -> str | None:
    """Resolve *filepath* under *workspace*, rejecting traversal attacks.

    Returns the resolved absolute path or ``None`` if the path escapes
    the workspace.
    """
    if os.path.isabs(filepath):
        log.warning("Rejected absolute path: %s", filepath)
        return None
    if ".." in filepath.split(os.sep):
        log.warning("Rejected path with '..': %s", filepath)
        return None
    resolved = os.path.normpath(os.path.join(workspace, filepath))
    if not resolved.startswith(os.path.normpath(workspace) + os.sep):
        log.warning("Path escapes workspace: %s", filepath)
        return None
    return resolved


# --- Public API ----------------------------------------------------------- #


def hash_tagged_read(filepath: str) -> str:
    """Read *filepath* and return lines tagged with ``LINE#HASH| content``.

    Example output::

        1#a7| def hello():
        2#3f|     return "world"
        3#e3|
    """
    log.debug("hash_tagged_read: %s", filepath)
    with open(filepath, encoding="utf-8") as fh:
        lines = fh.readlines()

    tagged: list[str] = []
    for idx, line in enumerate(lines, start=1):
        h = _line_hash(line)
        content = line.rstrip("\n")
        tagged.append(f"{idx}#{h}| {content}")

    return "\n".join(tagged)


# Regex for an edit instruction line inside an EDIT block:
#   12#a7| replacement content here
_EDIT_LINE_RE = re.compile(r"^(\d+)#([0-9a-f]{2})\|\s?(.*)$")

# Block delimiters
_BLOCK_START_RE = re.compile(r"^---\s*EDIT:\s*(.+?)\s*---$")
_BLOCK_END_RE = re.compile(r"^---\s*END EDIT\s*---$")


def parse_hashline_edits(text: str) -> list[HashlineEdit]:
    """Parse ``--- EDIT ... --- END EDIT ---`` blocks from LLM output.

    Expected format::

        --- EDIT: path/to/file.py ---
        1#a7| def hello_world():
        --- END EDIT ---
    """
    edits: list[HashlineEdit] = []
    current_file: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        start_match = _BLOCK_START_RE.match(line)
        if start_match:
            current_file = start_match.group(1)
            continue

        if _BLOCK_END_RE.match(line):
            current_file = None
            continue

        if current_file is None:
            continue

        edit_match = _EDIT_LINE_RE.match(line)
        if edit_match:
            line_number = int(edit_match.group(1))
            expected_hash = edit_match.group(2)
            new_content = edit_match.group(3)
            edits.append(
                HashlineEdit(
                    filepath=current_file,
                    line_number=line_number,
                    expected_hash=expected_hash,
                    new_content=new_content,
                )
            )

    log.debug("Parsed %d hashline edits", len(edits))
    return edits


def apply_hashline_edits(
    edits: list[HashlineEdit],
    workspace: str,
) -> ApplyResult:
    """Apply *edits* to files under *workspace*, verifying hashes first.

    Each edit's ``expected_hash`` is checked against the current line
    content.  Mismatches are recorded but do not abort the batch.
    """
    result = ApplyResult()

    # Group edits by file so we read/write each file once
    edits_by_file: dict[str, list[HashlineEdit]] = {}
    for edit in edits:
        edits_by_file.setdefault(edit.filepath, []).append(edit)

    for filepath, file_edits in edits_by_file.items():
        safe = _safe_path(filepath, workspace)
        if safe is None:
            msg = f"Rejected unsafe path: {filepath}"
            log.error(msg)
            result.errors.append(msg)
            continue

        if not os.path.isfile(safe):
            msg = f"File not found: {filepath}"
            log.error(msg)
            result.errors.append(msg)
            continue

        with open(safe, encoding="utf-8") as fh:
            lines = fh.readlines()

        modified = False
        file_applied = 0
        for edit in file_edits:
            idx = edit.line_number - 1  # 0-based
            if idx < 0 or idx >= len(lines):
                msg = (
                    f"{filepath}:{edit.line_number} — "
                    f"line number out of range (file has {len(lines)} lines)"
                )
                log.warning(msg)
                result.errors.append(msg)
                result.mismatches += 1
                continue

            current_line = lines[idx]
            if not validate_hash(current_line, edit.expected_hash):
                actual = _line_hash(current_line)
                msg = (
                    f"{filepath}:{edit.line_number} — "
                    f"hash mismatch (expected {edit.expected_hash}, "
                    f"got {actual})"
                )
                log.warning(msg)
                result.errors.append(msg)
                result.mismatches += 1
                continue

            # Preserve original trailing newline
            trailing = "\n" if current_line.endswith("\n") else ""
            lines[idx] = edit.new_content + trailing
            result.applied += 1
            file_applied += 1
            modified = True
            log.debug(
                "Applied edit %s:%d (%s)",
                filepath,
                edit.line_number,
                edit.expected_hash,
            )

        if modified:
            with open(safe, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            result.files_modified.append(filepath)
            log.info("Wrote %s (%d edits applied)", filepath, file_applied)

    return result
