#!/usr/bin/env python3
"""
.hermesignore support — gitignore-style path filtering.

Files and directories matching .hermesignore patterns are excluded from
file-tool operations (read_file, write_file, search_files, etc.).

Syntax supported:
  - Comments: lines starting with #
  - Negation: lines starting with ! (un-ignores a pattern)
  - Wildcards: **, *, ? (fnmatch-style)
  - Directory patterns: dir/ matches the directory and all its contents
  - Trailing /: explicitly marks a directory
  - Leading /: anchors pattern to the working directory

Usage:
    patterns = load_hermesignore(Path("/path/to/project"))
    if is_path_ignored("src/main.py", patterns):
        raise PermissionError("Path is ignored by .hermesignore")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Pattern


# Characters that must be escaped in regex patterns
_SPECIAL_CHARS = frozenset(".+()[]{}|^$\\")


def load_hermesignore(working_dir: Path) -> List[str]:
    """
    Read .hermesignore from *working_dir* and return a list of patterns.

    Returns an empty list if no .hermesignore exists.
    Comments (#) and blank lines are stripped.
    Negation patterns (!) are preserved so the caller can apply them.
    """
    ignore_file = working_dir / ".hermesignore"
    if not ignore_file.is_file():
        return []

    try:
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    patterns: List[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip blanks and pure comments
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)

    return patterns


def _escape_char(c: str) -> str:
    """Escape a single character for use in a regex."""
    if c in _SPECIAL_CHARS:
        return "\\" + c
    return c


def _build_regex(pattern: str, directory_only: bool = False) -> Pattern[str]:
    """
    Convert a .gitignore-style pattern string to a compiled regex.

    Args:
        pattern: The pattern string (without leading ! or trailing /).
        directory_only: When True, the pattern matches the directory itself
                       AND all contents recursively (appends ``(/.*)?$``).

    Handles:
      - **  → match any number of directory segments
      - *   → match anything except /
      - ?   → match any single char except /
      - /   → path separator (anchors to segment boundaries)
      - Leading / anchors to the working-directory root
    """
    regex_parts: List[str] = []
    i = 0
    n = len(pattern)

    # Anchor at start (^)
    if pattern.startswith("/"):
        regex_parts.append("^")
        i = 1
    else:
        regex_parts.append("^")

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** → match any number of directory segments
                regex_parts.append("(?:.*/)?")
                i += 2
                # ** followed by / consumes the slash
                if i < n and pattern[i] == "/":
                    i += 1
                continue
            else:
                regex_parts.append("[^/]*")
                i += 1
        elif c == "?":
            regex_parts.append("[^/]")
            i += 1
        elif c == "/":
            regex_parts.append("/")
            i += 1
        else:
            regex_parts.append(_escape_char(c))
            i += 1

    if directory_only:
        # Matches the directory name itself OR anything inside it
        regex_parts.append("(/.*)?$")
    else:
        regex_parts.append("$")

    return re.compile("".join(regex_parts))


def _compile_patterns(patterns: List[str]) -> List[tuple[bool, Pattern[str]]]:
    """
    Compile a list of patterns into (is_negation, compiled_regex) tuples.

    Negation patterns (starting with !) have is_negation=True.
    The leading ! is stripped before compilation.
    """
    compiled: List[tuple[bool, Pattern[str]]] = []
    for p in patterns:
        if p.startswith("!"):
            is_neg = True
            p = p[1:]
        else:
            is_neg = False

        if not p:
            continue

        # trailing / marks a directory: matches the dir AND everything inside it
        if p.endswith("/"):
            compiled.append((is_neg, _build_regex(p[:-1], directory_only=True)))
        else:
            compiled.append((is_neg, _build_regex(p, directory_only=False)))

    return compiled


def is_path_ignored(file_path: str, patterns: List[str]) -> bool:
    """
    Return True if *file_path* matches any pattern in *.hermesignore* patterns.

    Paths are matched relative to the working directory (the directory
    containing .hermesignore).  The check is always performed on the
    normalised relative path using forward slashes.

    Patterns are evaluated in order; the *last* match wins.
    A negation pattern (!) un-ignores a previously ignored path.
    """
    if not patterns:
        return False

    compiled = _compile_patterns(patterns)

    # Normalise to forward slashes for cross-platform consistency
    normalized = file_path.replace("\\", "/")

    ignored: bool = False
    for is_neg, regex in compiled:
        if regex.search(normalized):
            ignored = not is_neg

    return ignored
