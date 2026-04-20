#!/usr/bin/env python3
"""
Mode System for Hermes Agent

A mode is a named configuration that gates which tool groups are available
and provides role-specific behavioral guidance. Modes are loaded from:
  - Built-in modes (code, architect, ask, debug, orchestrator)
  - ~/.hermes/modes/*.yaml  (user-defined, override built-ins)
  - ~/.hermes/.roomodes     (legacy compatibility import)

The orchestrator mode is special: it has NO direct tool groups and delegates
all work to subagents instead.

Usage:
    from agent.modes import get_active_mode, set_active_mode, list_modes
    mode = get_active_mode()   # returns Mode object or None
"""

from __future__ import annotations

import os
import re
import threading
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from hermes_constants import get_hermes_home

# -----------------------------------------------------------------------
# Tool Groups
# -----------------------------------------------------------------------
# Each group is a named set of tools.  MCP tools are resolved dynamically.
TOOL_GROUPS: Dict[str, List[str]] = {
    "read": [
        "read_file", "search_files",
        "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
        "browser_scroll", "browser_back", "browser_press", "browser_get_images",
        "browser_vision", "browser_console",
        "vision_analyze",
        "web_search", "web_extract",
        "session_search",
        "skill_view", "skills_list",
    ],
    "edit": [
        "write_file", "patch", "execute_code",
    ],
    "command": [
        "terminal", "process",
    ],
    "mcp": [],  # dynamically resolved at runtime from MCP tool registrations
}

# Tools that are ALWAYS available regardless of mode.
# Includes ha_* tools, session_search (read), skills_list/view/manage, etc.
ALWAYS_AVAILABLE_TOOLS: Set[str] = {
    # Planning & memory
    "todo", "memory", "clarify",
    # Delegation (core to orchestrator pattern)
    "delegate_task",
    # Scheduling
    "cronjob",
    # Cross-platform messaging
    "send_message",
    # Home Assistant (gated by HASS_TOKEN independently)
    "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
    # Skills (always visible for discoverability)
    "skills_list", "skill_view", "skill_manage",
    # Session history (always useful for context)
    "session_search",
    # Mode switching
    "switch_mode",
    # Orchestration (planning/breakdown for orchestrator mode)
    "orchestrate",
}

# Tools whose edit_group write operations are additionally gated by a
# file path regex (architect mode restriction).
# Maps tool_name -> regex pattern (compiled).
_EDIT_TOOL_FILE_REGEX: Dict[str, str] = {
    "write_file": r"\.md$",
    "patch":      r"\.md$",
}

# -----------------------------------------------------------------------
# Mode Dataclass
# -----------------------------------------------------------------------

@dataclass
class Mode:
    """Definition of a single operational mode."""

    slug: str                           # unique identifier: "code", "architect"
    name: str                           # display name: "Code Assistant"
    role_definition: str                # role guidance injected into system prompt
    when_to_use: str                    # human-readable guidance on when to use
    tool_groups: List[str] = field(default_factory=list)  # groups to allow: read, edit, command, mcp
    constraints: Optional[Dict[str, str]] = None  # e.g. {"file_regex": r"\.md$"}
    custom_instructions: str = ""       # extra system-prompt guidance for this mode

    @property
    def allowed_tools(self) -> Set[str]:
        """Compute the full set of allowed tool names from tool_groups."""
        tools: Set[str] = set()
        for group in self.tool_groups:
            if group in TOOL_GROUPS:
                tools.update(TOOL_GROUPS[group])
        # MCP group is special: resolved at call time (see get_mcp_tools())
        return tools

    def is_tool_allowed(self, tool_name: str, mcp_tools: Set[str]) -> bool:
        """Check if a tool is allowed in this mode."""
        if tool_name in ALWAYS_AVAILABLE_TOOLS:
            return True
        if tool_name in mcp_tools and "mcp" in self.tool_groups:
            return True
        return tool_name in self.allowed_tools

    def check_file_regex(self, tool_name: str, file_path: str) -> bool:
        """
        Check file path against constraint regex for edit-group tools.
        Returns True if allowed (no constraint, or constraint satisfied).
        """
        if self.constraints is None:
            return True
        pattern = self.constraints.get("file_regex")
        if not pattern:
            return True
        # Only apply to edit-group tools listed in _EDIT_TOOL_FILE_REGEX
        if tool_name not in _EDIT_TOOL_FILE_REGEX:
            return True
        try:
            return bool(re.search(pattern, file_path))
        except re.error:
            return True  # fail open on invalid regex


# -----------------------------------------------------------------------
# Built-in Modes
# -----------------------------------------------------------------------

_BUILTIN_MODES: Dict[str, Mode] = {
    "code": Mode(
        slug="code",
        name="Code Assistant",
        role_definition=(
            "You are a skilled software engineer. You read, write, and modify code "
            "across the entire project. You execute terminal commands, search and "
            "navigate files, and use browser automation when needed. "
            "You think in terms of implementations, trade-offs, and system design."
        ),
        when_to_use=(
            "Use this mode when you need to implement features, fix bugs, write tests, "
            "run builds, or perform any software development task."
        ),
        tool_groups=["read", "edit", "command", "mcp"],
        constraints=None,
        custom_instructions="",
    ),
    "architect": Mode(
        slug="architect",
        name="Solution Architect",
        role_definition=(
            "You are a solution architect. You think at the system level — analyzing "
            "requirements, designing data flows, evaluating trade-offs, and producing "
            "specifications and documentation. You may read code and browse the web "
            "freely, but you are disciplined about file edits: restrict write_file "
            "and patch operations to .md documentation files only."
        ),
        when_to_use=(
            "Use this mode when exploring a codebase, designing a system, producing "
            "specs, reviewing architectures, or drafting documentation."
        ),
        tool_groups=["read", "edit", "mcp"],
        constraints={"file_regex": r"\.md$"},
        custom_instructions=(
            "You may read any file but restrict edits to documentation (.md) files. "
            "For implementation work that requires modifying code, switch to 'code' mode."
        ),
    ),
    "ask": Mode(
        slug="ask",
        name="Knowledge Assistant",
        role_definition=(
            "You are a knowledgeable research assistant. You answer questions, "
            "explain concepts, search the web, and provide analysis. "
            "You do not write or execute code."
        ),
        when_to_use=(
            "Use this mode for questions, explanations, research, web searches, "
            "and any task that does not require modifying files or running commands."
        ),
        tool_groups=["read", "mcp"],
        constraints=None,
        custom_instructions="Do not use write_file, patch, execute_code, or terminal.",
    ),
    "debug": Mode(
        slug="debug",
        name="Debug Specialist",
        role_definition=(
            "You are a debugging specialist. You systematically diagnose issues, "
            "read logs, trace through code, run test commands, and identify root "
            "causes. You have full access to all tools."
        ),
        when_to_use=(
            "Use this mode when investigating crashes, errors, unexpected behavior, "
            "or performance problems."
        ),
        tool_groups=["read", "edit", "command", "mcp"],
        constraints=None,
        custom_instructions=(
            "Focus on reproducing the issue, gathering diagnostic information, "
            "and identifying the root cause. Provide a clear explanation of the problem "
            "and recommended fix."
        ),
    ),
    "orchestrator": Mode(
        slug="orchestrator",
        name="Orchestrator",
        role_definition=(
            "You are an orchestrator. You delegate all work to subagents and manage "
            "their progress. You do not perform direct file edits, terminal commands, "
            "or browser automation yourself — you coordinate specialist subagents "
            "and synthesize their results."
        ),
        when_to_use=(
            "Use this mode when you want to decompose a complex task across multiple "
            "specialist subagents rather than doing the work directly."
        ),
        tool_groups=[],  # No direct tools — only delegation
        constraints=None,
        custom_instructions=(
            "You have NO direct tool access. Use delegate_task to spawn specialist "
            "subagents. Monitor their progress and synthesize their results into "
            "a final deliverable."
        ),
    ),
}


# -----------------------------------------------------------------------
# Roomodes Compatibility
# -----------------------------------------------------------------------
# .roomodes format (one mode per line):
#   mode_name: tool_group1,tool_group2,... | role_definition text
# Example:
#   code: read,edit,command,mcp | You are a coding assistant...

def _parse_roomodes_line(line: str) -> Optional[Mode]:
    """Parse a single line from a .roomodes file into a Mode."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Format: name: groups | role
    parts = line.split("|")
    if len(parts) != 2:
        return None
    left = parts[0].strip()
    role = parts[1].strip()
    name_and_groups = left.split(":")
    if len(name_and_groups) != 2:
        return None
    slug = name_and_groups[0].strip()
    groups_str = name_and_groups[1].strip()
    groups = [g.strip() for g in groups_str.split(",") if g.strip()]
    return Mode(
        slug=slug,
        name=slug.capitalize(),
        role_definition=role,
        when_to_use=f"Loaded from .roomodes (mode: {slug})",
        tool_groups=groups,
        constraints=None,
        custom_instructions="",
    )


def _load_roomodes(path: Path) -> Dict[str, Mode]:
    """Load legacy .roomodes file, returning slug->Mode dict."""
    modes: Dict[str, Mode] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            mode = _parse_roomodes_line(line)
            if mode:
                modes[mode.slug] = mode
    except Exception:
        pass
    return modes


# -----------------------------------------------------------------------
# YAML Mode Loading
# -----------------------------------------------------------------------

def _load_yaml_mode(path: Path) -> Optional[Mode]:
    """Load a single YAML mode definition file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        slug = path.stem  # filename without .yaml
        return Mode(
            slug=slug,
            name=data.get("name", slug.capitalize()),
            role_definition=data.get("role_definition", ""),
            when_to_use=data.get("when_to_use", ""),
            tool_groups=data.get("tool_groups", []),
            constraints=data.get("constraints"),
            custom_instructions=data.get("custom_instructions", ""),
        )
    except Exception:
        return None


def _load_modes_from_dir(dir_path: Path) -> Dict[str, Mode]:
    """Load all YAML mode definitions from a directory."""
    modes: Dict[str, Mode] = {}
    if not dir_path.is_dir():
        return modes
    for path in dir_path.glob("*.yaml"):
        mode = _load_yaml_mode(path)
        if mode:
            modes[mode.slug] = mode
    return modes


def load_modes_from_yaml(project_dir: Optional[Path] = None) -> Dict[str, Mode]:
    """Load modes from bundled + user-defined YAML files.

    Search order (later overrides earlier):
      1. agent/bundled_modes/*.yaml           (shipped with the codebase)
      2. ~/.hermes/modes/*.yaml                (user customizations override bundled)
      3. <project_dir>/.hermes/modes/*.yaml     (per-project modes override all)

    Args:
        project_dir: The project working directory. When provided, mode definitions
                     from <project_dir>/.hermes/modes/ are loaded with highest priority.
                     Defaults to the current working directory.
    """
    modes: Dict[str, Mode] = {}
    # Bundled modes (shipped with agent)
    bundled_dir = Path(__file__).parent / "bundled_modes"
    modes.update(_load_modes_from_dir(bundled_dir))
    # User modes (override bundled)
    user_dir = get_hermes_home() / "modes"
    modes.update(_load_modes_from_dir(user_dir))
    # Project modes (highest priority)
    if project_dir is None:
        project_dir = Path.cwd()
    project_modes_dir = project_dir / ".hermes" / "modes"
    modes.update(_load_modes_from_dir(project_modes_dir))
    return modes


# -----------------------------------------------------------------------
# Global Mode State (thread-safe)
# -----------------------------------------------------------------------

_state_lock = threading.RLock()
_current_mode: Optional[Mode] = None
_loaded_modes: Dict[str, Mode] = {}  # slug -> Mode (built-in + YAML)
_project_mode_dir: Optional[Path] = None  # cached project directory for mode loading


def _ensure_modes_loaded(project_dir: Optional[Path] = None) -> None:
    """Lazily load all modes (built-in + YAML + .roomodes) into _loaded_modes.

    When *project_dir* is provided, project-level modes from
    <project_dir>/.hermes/modes/ are also loaded with highest priority.
    Subsequent calls with a different project_dir trigger a full reload.
    """
    global _loaded_modes, _project_mode_dir
    # Detect project_dir change — force reload when project switches
    if project_dir is None:
        project_dir = Path.cwd()
    if _loaded_modes and _project_mode_dir == project_dir:
        return  # already loaded for this project
    # Built-in first
    _loaded_modes = dict(_BUILTIN_MODES)
    # YAML overrides / supplements (includes project modes via updated load_modes_from_yaml)
    yaml_modes = load_modes_from_yaml(project_dir)
    _loaded_modes.update(yaml_modes)
    # .roomodes compatibility
    roomodes_path = get_hermes_home() / ".roomodes"
    if roomodes_path.is_file():
        rm_modes = _load_roomodes(roomodes_path)
        # .roomodes takes lowest priority so yaml/built-in win
        for slug, mode in rm_modes.items():
            if slug not in _loaded_modes:
                _loaded_modes[slug] = mode
    _project_mode_dir = project_dir


def get_active_mode() -> Optional[Mode]:
    """Return the currently active Mode, or None if no mode is set."""
    with _state_lock:
        return _current_mode


def set_active_mode(slug: str, project_dir: Optional[Path] = None) -> Mode:
    """
    Activate a mode by slug. Returns the activated Mode.

    When *project_dir* is provided, per-project modes from
    <project_dir>/.hermes/modes/ are discoverable.
    Raises ValueError if the slug is not found.
    """
    _ensure_modes_loaded(project_dir)
    with _state_lock:
        if slug not in _loaded_modes:
            raise ValueError(f"Unknown mode: {slug}. Available: {list_modes(project_dir)}")
        global _current_mode
        _current_mode = _loaded_modes[slug]
        return _current_mode


def list_modes(project_dir: Optional[Path] = None) -> List[str]:
    """Return sorted list of available mode slugs."""
    _ensure_modes_loaded(project_dir)
    return sorted(_loaded_modes.keys())


def get_mode(slug: str, project_dir: Optional[Path] = None) -> Optional[Mode]:
    """Return the Mode for a slug, or None."""
    _ensure_modes_loaded(project_dir)
    return _loaded_modes.get(slug)


def get_mode_tool_groups(slug: str, project_dir: Optional[Path] = None) -> List[str]:
    """Return the tool groups for a mode, or empty list."""
    mode = get_mode(slug, project_dir)
    return mode.tool_groups if mode else []


def get_mcp_tool_names() -> Set[str]:
    """
    Return the set of currently registered MCP tool names.
    MCP tools are discovered and registered by tools.mcp_tool.discover_mcp_tools().
    """
    try:
        from tools.mcp_tool import get_mcp_tool_names as _get_mcp
        return _get_mcp()
    except Exception:
        return set()


def is_tool_allowed_by_mode(
    tool_name: str,
    mode: Optional[Mode] = None,
    file_path: Optional[str] = None,
) -> bool:
    """
    Check if a tool is allowed given the active mode.

    If mode is None, the active mode is used.
    If file_path is provided and the tool is an edit-group tool with a constraint,
    the file path is checked against the constraint regex.
    """
    if mode is None:
        mode = get_active_mode()
    if mode is None:
        return True  # No mode active = no gating

    mcp_tools = get_mcp_tool_names()
    allowed = mode.is_tool_allowed(tool_name, mcp_tools)

    # Additional file_regex check for edit-group tools
    if allowed and file_path and tool_name in _EDIT_TOOL_FILE_REGEX:
        allowed = mode.check_file_regex(tool_name, file_path)

    return allowed


def reload_modes(project_dir: Optional[Path] = None) -> None:
    """Force reload of all modes (built-in + YAML + .roomodes).

    When *project_dir* is provided, per-project modes from
    <project_dir>/.hermes/modes/ are also reloaded.
    """
    global _loaded_modes, _current_mode, _project_mode_dir
    with _state_lock:
        _loaded_modes = {}
        _project_mode_dir = None
        _current_mode = None
    _ensure_modes_loaded(project_dir)


# -----------------------------------------------------------------------
# Initialise modes on module import
# -----------------------------------------------------------------------

_ensure_modes_loaded()
