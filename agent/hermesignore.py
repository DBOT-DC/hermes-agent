#!/usr/bin/env python3
"""
Hermes Ignore — gitignore-style file filtering for Hermes Agent.

Supports .hermesignore files that prevent the agent from reading,
writing, or modifying specific files/directories.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple


class HermesIgnore:
    """Gitignore-style file pattern matcher for Hermes Agent."""

    def __init__(self):
        self._patterns: List[re.Pattern] = []
        self._negation_patterns: List[re.Pattern] = []
        self._raw_patterns: List[str] = []

    def load_from_file(self, path: Path):
        """Load ignore patterns from a .hermesignore file."""
        if not path.is_file():
            return
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            parsed = self.parse_line(line)
            if parsed is None:
                continue
            is_negation, pattern_str = parsed
            self._raw_patterns.append(pattern_str)
            regex = self._glob_to_regex(pattern_str)
            try:
                compiled = re.compile(regex)
                if is_negation:
                    self._negation_patterns.append(compiled)
                else:
                    self._patterns.append(compiled)
            except re.error:
                pass  # Skip invalid patterns

    def is_ignored(self, file_path: Path) -> bool:
        """Check if a file path matches any ignore pattern.

        Negation patterns override earlier ignore patterns.
        """
        path_str = str(file_path)
        path_str_forward = path_str.replace(os.sep, "/")

        # Check negation patterns first (they un-ignore)
        for pat in self._negation_patterns:
            if pat.search(path_str_forward) or pat.search(path_str):
                return False

        # Check ignore patterns
        for pat in self._patterns:
            if pat.search(path_str_forward) or pat.search(path_str):
                return True

        return False

    @staticmethod
    def parse_line(line: str) -> Optional[Tuple[bool, str]]:
        """Parse a .hermesignore line.

        Returns (is_negation, pattern_string) or None for comments/blanks.
        """
        line = line.rstrip()
        if not line or line.startswith("#"):
            return None

        is_negation = False
        if line.startswith("!"):
            is_negation = True
            line = line[1:]

        # Remove leading/trailing whitespace
        line = line.strip()
        if not line:
            return None

        return (is_negation, line)

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        """Convert a gitignore-style glob pattern to a regex."""
        # Handle directory-only patterns (trailing /)
        is_dir_only = pattern.endswith("/")
        if is_dir_only:
            pattern = pattern.rstrip("/")

        # Escape regex special chars (except *, ?, **, /)
        regex = ""
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "*":
                if i + 1 < len(pattern) and pattern[i + 1] == "*":
                    # ** matches everything including /
                    if i + 2 < len(pattern) and pattern[i + 2] == "/":
                        regex += "(?:.+/)?"
                        i += 3
                        continue
                    else:
                        regex += ".*"
                        i += 2
                        continue
                else:
                    # * matches everything except /
                    regex += "[^/]*"
            elif ch == "?":
                regex += "[^/]"
            elif ch in r".+^${}()|[]\\":
                regex += "\\" + ch
            else:
                regex += ch
            i += 1

        # If pattern has no /, it matches anywhere in the path
        if "/" not in pattern and not pattern.startswith("**"):
            regex = "(?:^|.*/)" + regex
        else:
            regex = "^" + regex

        if is_dir_only:
            regex += "(?:/.*)?"

        # Match to end of string or path segment
        regex += "$"

        return regex


# =============================================================================
# Module-level convenience functions
# =============================================================================

def load_hermesignore(working_dir: Path) -> HermesIgnore:
    """Load .hermesignore from working directory, with fallback to home."""
    ignore = HermesIgnore()

    # Try project-level .hermesignore
    project_ignore = working_dir / ".hermesignore"
    if project_ignore.is_file():
        ignore.load_from_file(project_ignore)
        return ignore

    # Try .hermes/.hermesignore
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    home_ignore = Path(hermes_home) / ".hermesignore"
    if home_ignore.is_file():
        ignore.load_from_file(home_ignore)

    return ignore


def is_file_ignored(file_path: Path, working_dir: Path) -> bool:
    """Check if a file is ignored by .hermesignore rules."""
    ignore = load_hermesignore(working_dir)
    return ignore.is_ignored(file_path)
