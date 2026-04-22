#!/usr/bin/env python3
"""
Mode System for Hermes Agent.

Implements Roo-Code style modes with tool gating, role definitions,
and custom mode loading from YAML files.

Modes determine which tools the agent can use, what persona it adopts,
and any file/path constraints.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# Attempt YAML import
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ---------------------------------------------------------------------------
# Mode dataclass
# ---------------------------------------------------------------------------

@dataclass
class Mode:
    """Represents an agent mode with tool gating and role definition."""

    slug: str
    name: str
    role_definition: str
    when_to_use: str
    tool_groups: List[str] = field(default_factory=lambda: ["read", "edit", "command", "mcp"])
    source: str = "hermes"
    constraints: Dict[str, str] = field(default_factory=dict)
    custom_instructions: str = ""
    reasoning_effort: str = "standard"  # none|light|standard|heavy
    reasoning_directives: str = ""

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed in this mode based on tool groups."""
        from toolsets import ALWAYS_AVAILABLE_TOOLS
        if tool_name in ALWAYS_AVAILABLE_TOOLS:
            return True
        from toolsets import TOOL_GROUPS
        for group in self.tool_groups:
            if tool_name in TOOL_GROUPS.get(group, set()):
                return True
        # Also allow MCP tools when mcp group is present
        if "mcp" in self.tool_groups and tool_name.startswith("mcp_"):
            return True
        return False

    def get_allowed_tools(self) -> Set[str]:
        """Get the full set of allowed tool names for this mode."""
        from toolsets import ALWAYS_AVAILABLE_TOOLS, TOOL_GROUPS
        allowed = set(ALWAYS_AVAILABLE_TOOLS)
        for group in self.tool_groups:
            allowed.update(TOOL_GROUPS.get(group, set()))
        return allowed

    def has_file_constraint(self) -> bool:
        """Whether this mode has a file_regex constraint."""
        return bool(self.constraints.get("file_regex", ""))


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_ACTIVE_MODE: Optional[Mode] = None
_ALL_MODES: Dict[str, Mode] = {}


def get_active_mode() -> Optional[Mode]:
    """Get the currently active mode."""
    return _ACTIVE_MODE


def set_active_mode(slug: str) -> Mode:
    """Set the active mode by slug. Returns the mode."""
    global _ACTIVE_MODE
    if slug is None or slug.strip() == "":
        _ACTIVE_MODE = None
        return None
    mode = _ALL_MODES.get(slug)
    if mode is None:
        raise ValueError(f"Unknown mode: '{slug}'. Available: {list(_ALL_MODES.keys())}")
    _ACTIVE_MODE = mode
    return mode


def get_mode(slug: str) -> Optional[Mode]:
    """Get a mode by slug."""
    return _ALL_MODES.get(slug)


def list_modes() -> Dict[str, Mode]:
    """List all registered modes."""
    return dict(_ALL_MODES)


def get_all_modes() -> List[Mode]:
    """Get all modes as a list."""
    return list(_ALL_MODES.values())


def reload_modes() -> Dict[str, Mode]:
    """Reload all modes from built-in + YAML sources."""
    global _ALL_MODES
    _ALL_MODES.clear()
    _register_builtin_modes()
    if HAS_YAML:
        _load_bundled_modes()
        _load_user_modes()
    return _ALL_MODES


# ---------------------------------------------------------------------------
# Built-in modes
# ---------------------------------------------------------------------------

def _register_builtin_modes():
    """Register the 5 built-in modes."""
    modes = [
        Mode(
            slug="code",
            name="Code",
            role_definition=(
                "You are a coding assistant. Write, modify, and debug code. "
                "Follow best practices for the language and framework. "
                "Test your changes when possible."
            ),
            when_to_use="Writing, modifying, or debugging code",
            tool_groups=["read", "edit", "command", "mcp"],
            source="hermes",
            reasoning_effort="standard",
        ),
        Mode(
            slug="architect",
            name="Architect",
            role_definition=(
                "You are a software architect. Focus on design, planning, "
                "and system structure. Prefer diagrams and specifications "
                "over implementation. Only edit markdown and config files."
            ),
            when_to_use="Planning system design, creating specifications, reviewing architecture",
            tool_groups=["read", "edit", "mcp"],
            source="hermes",
            constraints={"file_regex": r"\.(md|yaml|yml|json|toml|txt)$"},
            reasoning_effort="heavy",
        ),
        Mode(
            slug="ask",
            name="Ask",
            role_definition=(
                "You are a knowledgeable assistant. Answer questions, explain "
                "concepts, and provide information. Do not modify any files "
                "or execute commands."
            ),
            when_to_use="Asking questions, getting explanations, learning about a topic",
            tool_groups=["read", "mcp"],
            source="hermes",
            reasoning_effort="none",
        ),
        Mode(
            slug="debug",
            name="Debug",
            role_definition=(
                "You are a debugging specialist. Diagnose issues, identify "
                "root causes, and fix bugs. Be methodical: reproduce, "
                "hypothesize, isolate, verify, prevent."
            ),
            when_to_use="Diagnosing and fixing bugs, investigating errors",
            tool_groups=["read", "edit", "command", "mcp"],
            source="hermes",
            reasoning_effort="heavy",
            reasoning_directives="REPRODUCE→HYPOTHESIZE→ISOLATE→VERIFY→PREVENT",
        ),
        Mode(
            slug="orchestrator",
            name="Orchestrator",
            role_definition=(
                "You are a task orchestrator. You coordinate work by delegating "
                "to specialist agents. You do NOT perform work directly — "
                "use delegate_task to spawn subagents for each subtask. "
                "Break complex tasks into independent parallel workstreams."
            ),
            when_to_use="Coordinating complex multi-step tasks that benefit from parallel specialist agents",
            tool_groups=[],  # Orchestrator has NO direct tool groups
            source="hermes",
            reasoning_effort="heavy",
            reasoning_directives="DECOMPOSE→IDENTIFY→PARALLELIZE→SYNTHESIZE→VERIFY",
        ),
    ]
    for mode in modes:
        _ALL_MODES[mode.slug] = mode


# ---------------------------------------------------------------------------
# YAML mode loading
# ---------------------------------------------------------------------------

def _load_yaml_mode(path: Path) -> Optional[Mode]:
    """Load a single mode from a YAML file."""
    if not HAS_YAML:
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data or not isinstance(data, dict):
            return None

        slug = data.get("slug", path.stem)
        groups = data.get("tool_groups", ["read", "edit", "command", "mcp"])
        if isinstance(groups, list):
            tool_groups = []
            for g in groups:
                if isinstance(g, str):
                    tool_groups.append(g)
                elif isinstance(g, dict):
                    tool_groups.append(g.get("name", ""))
                else:
                    tool_groups.append(str(g))
        else:
            tool_groups = ["read", "edit", "command", "mcp"]

        constraints = {}
        raw_constraints = data.get("constraints", {})
        if isinstance(raw_constraints, dict):
            constraints = raw_constraints

        return Mode(
            slug=slug,
            name=data.get("name", slug),
            role_definition=data.get("role_definition", data.get("roleDefinition", "")),
            when_to_use=data.get("when_to_use", data.get("whenToUse", "")),
            tool_groups=tool_groups,
            source=data.get("source", "hermes"),
            constraints=constraints,
            custom_instructions=data.get("custom_instructions", ""),
            reasoning_effort=data.get("reasoning_effort", "standard"),
            reasoning_directives=data.get("reasoning_directives", ""),
        )
    except Exception:
        return None


def _load_modes_from_dir(directory: Path) -> Dict[str, Mode]:
    """Load all *.yaml mode files from a directory."""
    modes = {}
    if not directory.is_dir():
        return modes
    for f in sorted(directory.glob("*.yaml")):
        mode = _load_yaml_mode(f)
        if mode is not None:
            modes[mode.slug] = mode
    # Also check .yml extension
    for f in sorted(directory.glob("*.yml")):
        if f.stem in modes:
            continue  # Already loaded from .yaml
        mode = _load_yaml_mode(f)
        if mode is not None:
            modes[mode.slug] = mode
    return modes


def _load_bundled_modes():
    """Load modes from agent/bundled_modes/ directory."""
    # Walk up from this file to find the agent directory
    bundled_dir = Path(__file__).parent / "bundled_modes"
    if not bundled_dir.is_dir():
        return
    modes = _load_modes_from_dir(bundled_dir)
    _ALL_MODES.update(modes)


def _load_user_modes():
    """Load user modes from ~/.hermes/modes/ (overrides bundled)."""
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    user_dir = Path(hermes_home) / "modes"
    modes = _load_modes_from_dir(user_dir)
    _ALL_MODES.update(modes)  # User modes override bundled


def load_roomodes(path: Path) -> Dict[str, Mode]:
    """Import modes from a .roomodes file (Roo-Code compatibility)."""
    if not HAS_YAML:
        return {}
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data or not isinstance(data, dict):
            return {}
        custom_modes = data.get("customModes", [])
        if not custom_modes or not isinstance(custom_modes, list):
            return {}
        modes = {}
        for m in custom_modes:
            if not isinstance(m, dict):
                continue
            groups = m.get("groups", ["read", "edit", "command", "mcp"])
            if isinstance(groups, list):
                tool_groups = []
                for g in groups:
                    if isinstance(g, str):
                        tool_groups.append(g)
                    elif isinstance(g, dict):
                        tool_groups.append(g.get("name", ""))
                        # Extract file_regex from group object
                        if "fileRegex" in g:
                            tool_groups[-1] = g["name"]
                # Handle file_regex from group objects
                constraints = {}
                for g in groups:
                    if isinstance(g, dict) and "fileRegex" in g:
                        constraints["file_regex"] = g["fileRegex"]
            else:
                tool_groups = ["read", "edit", "command", "mcp"]

            slug = m.get("slug", "")
            if not slug:
                continue

            modes[slug] = Mode(
                slug=slug,
                name=m.get("name", slug),
                role_definition=m.get("roleDefinition", ""),
                when_to_use=m.get("whenToUse", ""),
                tool_groups=tool_groups,
                source=m.get("source", "roo-code"),
                constraints=constraints,
                custom_instructions=m.get("customInstructions", ""),
            )
        return modes
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Initialize on import
# ---------------------------------------------------------------------------

_register_builtin_modes()
if HAS_YAML:
    _load_bundled_modes()
    _load_user_modes()
