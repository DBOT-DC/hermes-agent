#!/usr/bin/env python3
"""Tests for agent/hermesignore.py"""

import tempfile
import os
from pathlib import Path
import unittest

from agent.hermesignore import (
    load_hermesignore,
    is_path_ignored,
    _build_regex,
    _compile_patterns,
)


class TestLoadHermesignore(unittest.TestCase):
    """Tests for load_hermesignore()."""

    def test_no_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            patterns = load_hermesignore(Path(tmpdir))
            self.assertEqual(patterns, [])

    def test_loads_comments_and_blanks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hermesignore = Path(tmpdir) / ".hermesignore"
            hermesignore.write_text("# This is a comment\n\n\n*.log\n# another comment\n")
            patterns = load_hermesignore(Path(tmpdir))
            self.assertEqual(patterns, ["*.log"])

    def test_loads_negation_patterns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hermesignore = Path(tmpdir) / ".hermesignore"
            hermesignore.write_text("*.log\n!important.log\n")
            patterns = load_hermesignore(Path(tmpdir))
            self.assertEqual(patterns, ["*.log", "!important.log"])

    def test_strips_whitespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hermesignore = Path(tmpdir) / ".hermesignore"
            hermesignore.write_text("  *.py  \n  !test.py  \n")
            patterns = load_hermesignore(Path(tmpdir))
            self.assertEqual(patterns, ["*.py", "!test.py"])


class TestIsPathIgnored(unittest.TestCase):
    """Tests for is_path_ignored()."""

    def test_empty_patterns_returns_false(self):
        self.assertFalse(is_path_ignored("src/main.py", []))
        self.assertFalse(is_path_ignored("anything", []))

    def test_exact_match(self):
        self.assertTrue(is_path_ignored("secret.txt", ["secret.txt"]))
        self.assertFalse(is_path_ignored("secret.txt", ["public.txt"]))

    def test_wildcard_single_star(self):
        self.assertTrue(is_path_ignored("debug.log", ["*.log"]))
        self.assertTrue(is_path_ignored("error.log", ["*.log"]))
        self.assertFalse(is_path_ignored("error.txt", ["*.log"]))

    def test_wildcard_double_star(self):
        self.assertTrue(is_path_ignored("src/deep/file.py", ["src/**/*.py"]))
        self.assertTrue(is_path_ignored("src/file.py", ["src/**/*.py"]))
        self.assertFalse(is_path_ignored("lib/file.py", ["src/**/*.py"]))

    def test_directory_pattern(self):
        self.assertTrue(is_path_ignored("node_modules/package/index.js", ["node_modules/"]))
        self.assertTrue(is_path_ignored("node_modules/foo/bar/baz.txt", ["node_modules/"]))
        self.assertFalse(is_path_ignored("src/node_modules/file.js", ["node_modules/"]))

    def test_negation_restores(self):
        self.assertTrue(is_path_ignored("debug.log", ["*.log", "!important.log"]))
        self.assertFalse(is_path_ignored("important.log", ["*.log", "!important.log"]))
        self.assertTrue(is_path_ignored("trace.log", ["*.log", "!important.log"]))

    def test_comment_line_not_ignored(self):
        self.assertFalse(is_path_ignored("src/main.py", ["# this is a comment"]))

    def test_trailing_slash_directory_only(self):
        patterns = ["dir/"]
        self.assertTrue(is_path_ignored("dir/file.txt", patterns))
        self.assertTrue(is_path_ignored("dir/sub/file.txt", patterns))
        self.assertFalse(is_path_ignored("file.txt", patterns))

    def test_leading_slash_anchored(self):
        patterns = ["/root.txt"]
        self.assertTrue(is_path_ignored("root.txt", patterns))
        self.assertFalse(is_path_ignored("sub/root.txt", patterns))

    def test_backslash_normalised(self):
        self.assertTrue(is_path_ignored("src\\main.py", ["src/main.py"]))

    def test_question_mark_wildcard(self):
        self.assertTrue(is_path_ignored("file1.txt", ["file?.txt"]))
        self.assertFalse(is_path_ignored("file12.txt", ["file?.txt"]))


class TestIntegration(unittest.TestCase):
    """End-to-end integration tests using temp directories."""

    def test_full_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hermesignore = Path(tmpdir) / ".hermesignore"
            hermesignore.write_text("# Ignore all logs\n*.log\n\n# But not this one\n!critical.log\n\n# Ignore node_modules\nnode_modules/\n\n# Ignore build output\nbuild/\n")
            patterns = load_hermesignore(Path(tmpdir))
            # 4 non-comment, non-blank lines:
            #   *.log
            #   !important.log
            #   node_modules/
            #   build/
            self.assertEqual(len(patterns), 4)

            # Should be ignored
            self.assertTrue(is_path_ignored("debug.log", patterns))
            self.assertTrue(is_path_ignored("error.log", patterns))
            self.assertTrue(is_path_ignored("node_modules/lodash/index.js", patterns))
            self.assertTrue(is_path_ignored("build/app.js", patterns))

            # Should NOT be ignored (negation, or different type)
            self.assertFalse(is_path_ignored("critical.log", patterns))
            self.assertFalse(is_path_ignored("main.py", patterns))
            self.assertFalse(is_path_ignored("src/index.js", patterns))


if __name__ == "__main__":
    unittest.main()
