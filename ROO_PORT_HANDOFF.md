# Roo-Code Port — COMPLETED ✅

## Status: 100% — All 7 items done, 115 new integration tests passing

## Created Modules (all compile clean)
- agent/modes.py — 5 built-in modes, YAML loader, .roomodes importer
- agent/checkpoint_service.py — Shadow Git checkpoint service
- agent/task_hierarchy.py — TaskNode + TaskHierarchyManager
- agent/orchestrator.py — OrchestratorEngine
- tools/mode_tool.py — switch_mode tool
- tools/checkpoint_tool.py — checkpoint tool
- tools/orchestrator_tool.py — orchestrate tool

## Modified Files
- model_tools.py — 3 new tool modules + active_mode gating
- toolsets.py — TOOL_GROUPS, ALWAYS_AVAILABLE_TOOLS, orchestrate
- hermes_cli/commands.py — /mode and /checkpoint CommandDefs
- cli.py — /mode and /checkpoint dispatch handlers
- agent/prompt_builder.py — build_mode_prompt()
- hermes_cli/config.py — modes.*, context.*, checkpoints.auto_save
- agent/context_compressor.py — sliding window, forced reduction, auto-condense, handle_context_overflow()
- run_agent.py — checkpoint service injection, auto-save hooks, sliding window fallback at all 3 overflow exhaustion sites

## Integration Tests (115 tests)
- tests/agent/test_modes.py — 22 tests (Mode switching, tool gating, file regex)
- tests/agent/test_task_hierarchy.py — 23 tests (CRUD, tree traversal, aggregation)
- tests/agent/test_checkpoint_service.py — 22 tests (disabled ops, dedup, enabled ops)
- tests/agent/test_orchestrator.py — 10 tests (planning, execution, monitoring)
- tests/tools/test_mode_tool.py — 5 tests (switch_mode handler)
- tests/tools/test_checkpoint_tool.py — 14 tests (all checkpoint actions)
- tests/tools/test_orchestrator_tool.py — 16 tests (all orchestrate actions)
- tests/agent/test_context_compressor.py — 7 new tests (sliding window + handle_context_overflow)

## Full Plan
See skill: roo-code-port-plan

---

## Usage Guide

### Activating Modes

**Command:** `/mode <name>` or `/mode`

- No argument: Lists all 15 available modes with descriptions
- With argument: Switches to that mode immediately
- Aliases: `/m code`, `/m orchestrator`

**Available Modes:**

| Mode | When to Use |
|------|-------------|
| `orchestrator` | DEFAULT for project work. Plans, delegates to specialist agents, synthesizes results. Only sees delegation tools (delegate_task, todo, memory, switch_mode, orchestrate). |
| `code` | Hands-on coding. Full tool access: read/write files, terminal, browser, patch, search. |
| `architect` | System design. Can read files and search but cannot write or execute. Good for planning before coding. |
| `ask` | Q&A only. Can search and read but cannot modify anything. |
| `debug` | Bug hunting. Full access plus focused system prompt for systematic debugging. |
| `merge-resolver` | Resolves git merge conflicts. File read/write access only. |
| `docs-extractor` | Extracts documentation from codebases. Read-only with focused prompts. |
| `documentation-writer` | Writes project documentation. File read/write access. |
| `user-story-creator` | Creates user stories from requirements. |
| `project-research` | Research tasks for projects. Web search + file read. |
| `security-reviewer` | Security audit mode. Read-only with security-focused prompts. |
| `devops` | Deployment and infrastructure. Terminal + file access. |
| `jest-test-engineer` | Writes Jest tests. File read/write + terminal. |
| `skills-writer` | Creates Hermes skills. File read/write access. |
| `mode-writer` | Creates custom mode YAML files. File read/write access. |

### How Orchestrator Mode Works

1. Start a task (e.g. "Build a REST API with auth")
2. Orchestrator calls `delegate_task` to spawn subagents in specialist modes:
   - One agent plans the architecture (mode=architect)
   - Another implements the code (mode=code)
   - A third writes tests (mode=jest-test-engineer)
3. Each subagent runs with its own tool set and mode prompt
4. Orchestrator reviews results and synthesizes the final answer

You can also use the `orchestrate` tool directly:
- `plan` — Break down a goal into subtasks
- `execute` — Run the plan with specialist agents
- `status` — Check progress
- `results` — View completed work
- `cancel` — Stop execution

### Switching Modes Mid-Session

Just say the mode name or use `/mode <name>`:
- "Switch to code mode" or `/mode code`
- "Let me debug this" or `/mode debug`
- "Go back to orchestrator" or `/mode orchestrator`

When you switch modes, the tool list automatically refreshes — you immediately get the right tools for that mode.

### Creating Custom Modes

Create a YAML file in `~/.hermes/modes/`:

```yaml
name: my-custom-mode
slug: my-custom-mode
role_definition: You are a specialist in...
when_to_use: Use when the user needs...
tool_groups:
  - file-read
  - web
  - search
always_available_tools:
  - todo
  - memory
  - switch_mode
```

Tool groups: `file-read`, `file-write`, `terminal`, `browser`, `web`, `search`, `mcp`, `execute-code`

Custom modes override bundled modes with the same slug.

### Checkpoints

- `/checkpoint save [message]` — Save a snapshot of current state
- `/checkpoint list` — View all checkpoints
- `/checkpoint restore <id>` — Restore to a checkpoint
- `/checkpoint diff <id>` — See what changed since checkpoint
- `/checkpoint clear` — Delete all checkpoints
- Aliases: `/checkpoint` = `/rollback` = `/cp`

Checkpoints use shadow Git — no repo needed. Auto-saves before file edits.

### Config

Set default mode in `~/.hermes/config.yaml`:
```yaml
agent:
  default_mode: orchestrator
```

To disable mode system entirely, set `default_mode: ""` or leave it unset.
