#!/usr/bin/env python3
"""
Mode Switch Tool

Allows the agent or user to switch between operational modes.
Registered via the standard tools.registry pattern.
"""

import json
from typing import Any, Dict, Optional

from tools.registry import registry, tool_error


SWITCH_MODE_SCHEMA = {
    "name": "switch_mode",
    "description": (
        "Switch Hermes Agent to a different operational mode. "
        "Each mode has different tool group access and behavioral guidance. "
        "Use this when the nature of the task changes significantly. "
        "Returns the new mode's name and description on success."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": (
                    "The mode slug to switch to. "
                    "Available modes: code, architect, ask, debug, orchestrator. "
                    "Use /mode list to see all available modes."
                ),
            }
        },
        "required": ["mode"]
    }
}


def check_switch_mode_requirements() -> bool:
    """Always available — modes are a core feature."""
    return True


def switch_mode_tool(args: Dict[str, Any], **kwargs) -> str:
    """
    Handler for the switch_mode tool.
    Sets the active mode and returns confirmation.
    """
    mode_slug = args.get("mode", "").strip().lower()
    if not mode_slug:
        return json.dumps({"error": "mode argument is required"}, ensure_ascii=False)

    try:
        from agent.modes import set_active_mode, get_mode, list_modes

        # Validate mode exists
        available = list_modes()
        if mode_slug not in available:
            return json.dumps({
                "error": f"Unknown mode: '{mode_slug}'. Available modes: {', '.join(sorted(available))}"
            }, ensure_ascii=False)

        mode = set_active_mode(mode_slug)

        return json.dumps({
            "success": True,
            "mode": mode.name,
            "slug": mode.slug,
            "role": mode.role_definition[:200] + "..." if len(mode.role_definition) > 200 else mode.role_definition,
            "tool_groups": mode.tool_groups,
            "when_to_use": mode.when_to_use,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"Failed to switch mode: {str(e)}"}, ensure_ascii=False)


# --- Registry ---

registry.register(
    name="switch_mode",
    toolset="modes",
    schema=SWITCH_MODE_SCHEMA,
    handler=lambda args, **kw: switch_mode_tool(args, **kw),
    check_fn=check_switch_mode_requirements,
    emoji="🔀",
)
