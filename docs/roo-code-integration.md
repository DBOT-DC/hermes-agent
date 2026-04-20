# Roo-Code Integration — Usage Guide

## Overview

This port brings Roo-Code's multi-mode agentic architecture into Hermes Agent. The agent can now operate in specialized **modes** that restrict which tools it can use, shape its personality, and gate file access — just like Roo-Code's architecture in VS Code.

## Quick Start

### Switching Modes

```
/mode code              # Full coding mode (read, write, terminal, MCP)
/mode architect         # Planning & design (read, edit .md only, MCP)
/mode ask               # Q&A (read, MCP — no writes)
/mode debug             # Diagnose & fix (read, write, terminal, MCP)
/mode orchestrator      # Coordinate subtasks only (delegates to other agents)
/mode                   # Show current mode and available modes
```

### Using Checkpoints

```
/checkpoint save "before refactor"    # Save a shadow git checkpoint
/checkpoint list                      # List all checkpoints for current task
/checkpoint diff <id>                 # Show diff from checkpoint to current state
/checkpoint restore <id>              # Restore files to checkpoint state
/checkpoint clear                     # Delete all checkpoints for current task
```

Aliases: `/checkpoint` also responds to `/cp` and `/rollback`.

### Using the Orchestrator

```
# Switch to orchestrator mode first
/mode orchestrator

# The LLM will use the orchestrate tool to:
# 1. Break your request into subtasks
# 2. Spawn specialist agents for each subtask
# 3. Aggregate results and synthesize a final response
```

## Available Modes

### Built-in Modes

| Mode | Tool Groups | Purpose |
|------|-------------|---------|
| **code** | read, edit, command, mcp | Write and modify code (default) |
| **architect** | read, edit, mcp | Planning & design — can only edit `.md` files |
| **ask** | read, mcp | Questions & explanations — no writes or commands |
| **debug** | read, edit, command, mcp | Diagnose and fix issues |
| **orchestrator** | *(delegates only)* | Coordinate subtasks via `delegate_task` |

### Bundled Custom Modes

| Mode | Tool Groups | File Constraint | Purpose |
|------|-------------|-----------------|---------|
| **merge-resolver** | read, edit, command, mcp | — | Resolve git merge conflicts |
| **docs-extractor** | read, edit, command, mcp | `.roo/extraction/` | Extract documentation into structured files |
| **documentation-writer** | read, edit, command, mcp | — | Write project documentation |
| **user-story-creator** | read, edit, command, mcp | — | Create user stories and acceptance criteria |
| **project-research** | read, command, mcp | — | Research projects and technologies |
| **security-reviewer** | read, edit, command, mcp | — | Security audit and vulnerability review |
| **devops** | read, edit, command, mcp | — | DevOps and infrastructure tasks |
| **jest-test-engineer** | read, edit, command, mcp | — | Write Jest/JavaScript tests |
| **skills-writer** | read, edit, command, mcp | — | Create and manage Hermes skills |
| **mode-writer** | read, edit, command, mcp | — | Create new custom modes |

## How Tool Gating Works

When a mode is active, the agent only sees tools matching that mode's tool groups:

| Tool Group | Tools |
|------------|-------|
| **read** | `read_file`, `search_files`, `browser_navigate`, `browser_snapshot` |
| **edit** | `write_file`, `patch`, `execute_code` |
| **command** | `terminal`, `process` |
| **mcp** | All MCP tools |

**Always available** (bypass mode gating): `clarify`, `todo`, `memory`, `delegate_task`, `switch_mode`, `cronjob`, `send_message`, `skill_*`, `checkpoint`, `orchestrate`

### Examples

- **`ask` mode**: Agent can read files and search, but cannot write, run commands, or edit — perfect for "explain this code to me"
- **`architect` mode**: Agent can edit markdown files but not `.py`/`.ts`/etc — perfect for planning docs
- **`orchestrator` mode**: Agent has NO direct tools — can only `delegate_task` to spawn specialist subagents

## Context Management

The Roo-Code port adds a dual-strategy context management system:

### Auto-Condense
When conversation reaches 75% of context window, the compressor automatically summarizes older messages while preserving recent context.

### Sliding Window Fallback
If compression fails or is ineffective (anti-thrashing protection kicks in after 2 consecutive failed compressions), the system falls back to sliding window truncation — keeping the most recent messages and dropping older ones.

### Configuration

```yaml
# ~/.hermes/config.yaml
context:
  engine: compressor
  auto_condense_percent: 0.75      # Trigger at 75% of context
  forced_reduction_percent: 0.75   # Reduce to 25% on overflow
  max_window_retries: 3            # Max sliding window attempts
  token_buffer_percent: 0.10       # Reserve 10% for response headroom
```

## Checkpoint System

Checkpoints create shadow git snapshots before file-modifying operations. If something goes wrong, you can restore to any previous checkpoint.

### Auto-Save
When enabled, checkpoints are automatically created before `write_file` and `patch` operations.

```yaml
# ~/.hermes/config.yaml
checkpoints:
  enabled: true
  auto_save: true        # Auto-checkpoint before edits
  max_snapshots: 50      # Max checkpoints per task
```

### Manual Usage
```
/checkpoint save "refactoring auth module"
# ... make changes ...
/checkpoint diff 1       # See what changed since checkpoint 1
/checkpoint restore 1    # Undo everything back to checkpoint 1
```

## Batch Editing

The `patch` tool now supports batch mode for multi-file edits:

```json
{
  "mode": "batch",
  "changes": [
    {"path": "src/auth.ts", "old_string": "old code 1", "new_string": "new code 1"},
    {"path": "src/api.ts", "old_string": "old code 2", "new_string": "new code 2", "replace_all": true}
  ]
}
```

**Features:**
- Pre-flight validation: checks ALL `old_string` patterns exist before writing anything
- Atomic: if any change fails validation, NO files are modified
- Returns `applied[]`, `failed[]`, and combined `diff`
- Supports `replace_all` per-change

## Custom Modes

### Creating a Custom Mode

Create a YAML file in `~/.hermes/modes/`:

```yaml
# ~/.hermes/modes/my-reviewer.yaml
slug: my-reviewer
name: My Code Reviewer
role_definition: >
  You are a strict code reviewer. Focus on security, performance,
  and maintainability. Always provide specific line-level feedback.
when_to_use: >
  Use when reviewing pull requests or conducting code reviews.
tool_groups:
  - read
  - mcp
custom_instructions: >
  Always check for:
  1. Security vulnerabilities
  2. Performance bottlenecks
  3. Code style consistency
constraints:
  file_regex: "\\.(ts|tsx|js|jsx|py|rs|go)$"
```

### Importing Roo-Code .roomodes

Drop a `.roomodes` file in your project root. Hermes will auto-import custom modes from it:

```yaml
# .roomodes (Roo-Code format — compatible)
customModes:
  - slug: my-mode
    name: My Mode
    roleDefinition: "You are a specialist in..."
    whenToUse: "Use when..."
    groups: [read, edit, command, mcp]
```

### Per-Project Modes

Create modes in your project's `.hermes/modes/` directory. Project modes override user modes, which override bundled modes:

```
Priority: bundled → user (~/.hermes/modes/) → project (.hermes/modes/)
```

## Orchestrator Mode

The orchestrator cannot use tools directly. It coordinates work by:

1. **Planning**: Breaking your request into subtasks using LLM reasoning
2. **Delegating**: Spawning specialist subagents for each subtask (via `delegate_task`)
3. **Monitoring**: Tracking subtask progress and status
4. **Aggregating**: Combining results from all subtasks into a coherent response

### Example Flow

```
User: "Refactor the auth system to use JWT and update all tests"

Orchestrator:
  1. Plans: [analyze auth, design JWT, implement, write tests, update docs]
  2. Delegates each subtask to a code-mode agent
  3. Each agent runs independently with its own context
  4. Orchestrator synthesizes results into final response
```

## Error Recovery

Configurable retry with exponential backoff for tool failures:

```yaml
# ~/.hermes/config.yaml
error_recovery:
  max_retries: 5
  base_delay: 5.0           # Start at 5s
  max_delay: 120.0          # Cap at 2min
  rate_limit_base_delay: 2.0
  rate_limit_max_delay: 60.0
  tool_retry_budget: 3      # Max retries per tool per turn
```

## .hermesignore

Works like `.gitignore` — prevents the agent from reading/writing matching files:

```
# ~/.hermesignore
*.env
*.log
__pycache__/
node_modules/
secrets/
!important.env    # Negation — allow this specific file
```

## Configuration Reference

All Roo-Code port settings in `~/.hermes/config.yaml`:

```yaml
modes:
  default: "code"           # Starting mode (code, architect, ask, debug, orchestrator)
  auto_switch: false         # Let the LLM auto-switch modes

context:
  engine: "compressor"
  auto_condense_percent: 0.75
  forced_reduction_percent: 0.75
  max_window_retries: 3
  token_buffer_percent: 0.10

checkpoints:
  enabled: false             # Master switch
  auto_save: true            # Auto-checkpoint before edits
  max_snapshots: 50

error_recovery:
  max_retries: 5
  base_delay: 5.0
  max_delay: 120.0
  rate_limit_base_delay: 2.0
  rate_limit_max_delay: 60.0
  tool_retry_budget: 3
```

## Architecture

```
agent/modes.py              — Mode system (Mode dataclass, loader, switching)
agent/checkpoint_service.py — Shadow Git checkpoints
agent/task_hierarchy.py     — Task tree for orchestrator
agent/orchestrator.py       — LLM-based task breakdown + delegation
agent/hermesignore.py       — .hermesignore pattern matching
tools/mode_tool.py          — switch_mode tool handler
tools/checkpoint_tool.py    — checkpoint tool handler
tools/orchestrator_tool.py  — orchestrate tool handler
agent/bundled_modes/        — 10 shipped mode YAML definitions
```

## System Prompt Builder (11-Section Modular Assembly)

The port includes Roo Code's full modular system prompt architecture. The system
prompt is assembled from 11 independent sections in canonical order:

| # | Section | Function | Status |
|---|---------|----------|--------|
| 1 | Agent Identity | Role, name, personality | ✅ Existing (SOUL.md) |
| 2 | Markdown Rules | Clickable file refs, formatting | ✅ `build_markdown_rules_section()` |
| 3 | Tool Use Intro | Shared tool execution header | ✅ `build_tool_use_section()` |
| 4 | Tool Guidelines | 3 numbered execution rules | ✅ `build_tool_use_guidelines_section()` |
| 5 | Capabilities | CLI, file ops, search, MCP | ✅ `build_capabilities_section()` |
| 6 | Available Modes | List all modes + whenToUse | ✅ `build_modes_section()` |
| 7 | Mode Prompt | Role definition + 3-tier instructions | ✅ `build_mode_prompt()` |
| 8 | Rules | File handling, git, path conventions | ✅ `build_rules_section()` |
| 9 | System Info | OS, shell, home dir, workspace | ✅ `build_system_info_section()` |
| 10 | Objective | Iterative task accomplishment | ✅ `build_objective_section()` |
| 11 | Custom Instructions | Global → mode → project rules | ✅ `build_mode_prompt()` + `_load_project_instructions()` |

### 3-Tier Instruction Hierarchy (Section 11)

Instructions are layered from broadest to most specific:

1. **Global rules** — `~/.hermes/instructions.md` (applies to all modes)
2. **Mode rules** — `.hermes/modes/<mode>.yaml` `instructions:` field
3. **Project rules** — `<workspace>/.hermes/instructions.md` (project-specific)

Each tier can override or extend the previous one. The mode prompt includes the
mode's role definition and any mode-specific skills.

### Mode-Filtered Skills

When a mode is active, the skills section is filtered to only show skills
relevant to that mode's toolset. For example, `ask` mode won't show coding
skills since it lacks write/terminal access.

## Testing

```bash
cd /path/to/hermes-agent
source venv/bin/activate

# Run all Roo Code port tests
python -m pytest tests/agent/test_modes.py \
  tests/agent/test_checkpoint_service.py \
  tests/agent/test_task_hierarchy.py \
  tests/agent/test_orchestrator.py \
  tests/tools/test_mode_tool.py \
  tests/tools/test_checkpoint_tool.py \
  tests/tools/test_orchestrator_tool.py \
  tests/agent/test_context_compressor.py \
  tests/agent/test_bundled_modes.py \
  tests/tools/test_mode_approval.py \
  tests/agent/test_context_phase3.py \
  tests/tools/test_batch_edit.py \
  tests/agent/test_error_recovery_config.py \
  tests/agent/test_hermesignore.py \
  tests/agent/test_project_config.py \
  tests/hermes_cli/test_mode_ui.py \
  tests/agent/test_prompt_builder_sections.py \
  tests/test_roo_code_port.py \
  -v -o "addopts="
```

354 tests, 0 failures.
