#!/usr/bin/env python3
"""
Switch Mode Tool for Hermes Agent.

Allows the agent to switch between modes (code, architect, ask, debug, orchestrator).
Always available regardless of current mode.
"""

import json
from tools.registry import registry


def switch_mode_handler(args: dict) -> str:
    """Handle switch_mode tool calls."""
    mode_slug = args.get("mode", "")
    if not mode_slug:
        return json.dumps({"success": False, "error": "No mode specified"})

    try:
        from agent.modes import set_active_mode, list_modes
        mode = set_active_mode(mode_slug)
        if mode is None:
            return json.dumps({"success": True, "message": "Mode cleared"})

        all_modes = list_modes()
        tool_count = len(mode.get_allowed_tools())
        return json.dumps({
            "success": True,
            "mode": mode.name,
            "slug": mode.slug,
            "tool_groups": mode.tool_groups,
            "available_tools": tool_count,
            "all_modes": list(all_modes.keys()),
        })
    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)})
    except Exception as e:
        return json.dumps({"success": False, "error": f"Failed to switch mode: {e}"})


_SWITCH_MODE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "switch_mode",
        "description": (
            "Switch the agent's operating mode. Each mode has different tool access "
            "and persona. Available modes: code, architect, ask, debug, orchestrator. "
            "Use 'list' as the mode argument to see all available modes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "The mode slug to switch to (e.g., 'code', 'architect', 'ask', 'debug', 'orchestrator'). Use 'list' to see all available modes.",
                },
            },
            "required": ["mode"],
        },
    },
}

registry.register(
    name="switch_mode",
    toolset="agent",
    schema=_SWITCH_MODE_SCHEMA,
    handler=switch_mode_handler,
    description=(
        "Switch the agent's operating mode. Each mode has different tool access "
        "and persona. Available modes: code, architect, ask, debug, orchestrator."
    ),
    emoji="🔄",
)
