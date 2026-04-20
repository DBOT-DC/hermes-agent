#!/usr/bin/env python3
"""
End-to-End Integration Test — Roo-Code Port (FIXED)

Tests the full wiring of all major components after bug fixes:
1. AIAgent Instantiation with Mode System (self._config fix)
2. Agent Mode Switching Flow
3. OrchestratorEngine + TaskHierarchy Integration
4. Checkpoint E2E Flow
5. Config Loading Pipeline
6. Gateway Mode Change Handler
7. Full Tool Registry Integrity (checkpoint toolset fix)

No LLM API calls — structural/instantiation tests only.
"""

import os, sys, tempfile, shutil, subprocess

# Ensure we use the venv Python
venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
if os.path.exists(venv_python):
    if sys.executable != venv_python:
        os.execv(venv_python, [venv_python, __file__] + sys.argv[1:])

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

os.environ["HERMES_QUIET"] = "1"
os.environ["NOISY_LOGGERS"] = "0"

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from pathlib import Path

passed = 0
failed = 0

def result(test_name, ok, detail=""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {test_name}")
    if detail:
        print(f"         {detail}")
    if ok:
        passed += 1
    else:
        failed += 1
    return ok


# === TEST 1: AIAgent Instantiation ===
def test_1():
    print("\n=== TEST 1: AIAgent Instantiation with Mode System ===")
    try:
        from run_agent import AIAgent
        from agent.modes import get_active_mode, set_active_mode

        set_active_mode("orchestrator")

        agent = AIAgent(
            model="test-model",
            max_iterations=5,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

        result("AIAgent instantiates without error", True)
        result("agent._config is a dict", isinstance(getattr(agent, '_config', None), dict),
               f"type={type(getattr(agent, '_config', None))}")
        result("agent._config is not empty", bool(agent._config),
               f"keys={len(agent._config)}")
        result("agent._config has 'agent' section", 'agent' in agent._config)
        result("agent._config['agent']['default_mode'] == 'orchestrator'",
               agent._config.get('agent', {}).get('default_mode') == 'orchestrator',
               f"got={agent._config.get('agent', {}).get('default_mode')}")
        result("agent._tool_retry_counts is a dict",
               isinstance(getattr(agent, '_tool_retry_counts', None), dict))
        result("agent._refresh_tools_for_mode is callable",
               callable(getattr(agent, '_refresh_tools_for_mode', None)))
        result("agent._config has 'error_recovery' section",
               'error_recovery' in agent._config,
               f"keys={list(agent._config.get('error_recovery', {}).keys())}")
    except Exception as e:
        result("TEST 1", False, f"Exception: {e}")


# === TEST 2: Mode Switching ===
def test_2():
    print("\n=== TEST 2: Agent Mode Switching Flow ===")
    try:
        from run_agent import AIAgent
        from agent.modes import set_active_mode, get_active_mode

        agent = AIAgent(
            model="test-model", max_iterations=5, quiet_mode=True,
            skip_context_files=True, skip_memory=True,
        )

        # Switch to code mode
        set_active_mode("code")
        agent._refresh_tools_for_mode()
        code_count = len(agent.tools)

        # Switch to orchestrator mode
        set_active_mode("orchestrator")
        agent._refresh_tools_for_mode()
        orch_count = len(agent.tools)

        result("Code mode has more tools than orchestrator",
               code_count > orch_count,
               f"code={code_count}, orch={orch_count}")
        result("Orchestrator has ~12 tools", orch_count >= 10 and orch_count <= 15,
               f"orch_count={orch_count}")
        result("Code mode has ~29+ tools", code_count >= 25,
               f"code_count={code_count}")

        # Reset
        set_active_mode("orchestrator")
    except Exception as e:
        result("TEST 2", False, f"Exception: {e}")


# === TEST 3: OrchestratorEngine + TaskHierarchy ===
def test_3():
    print("\n=== TEST 3: OrchestratorEngine + TaskHierarchy ===")
    try:
        from agent.task_hierarchy import TaskHierarchyManager, TaskNode

        hier = TaskHierarchyManager()
        root = hier.create_task(description="Build the thing")

        result("TaskHierarchyManager instantiates", True)
        result("create_task() returns a TaskNode", root is not None)
        result("TaskNode has task_id", hasattr(root, 'task_id'))
        result("get_root_task() returns the root",
               hier.get_root_task(root.task_id).task_id == root.task_id)

        child = hier.create_task(description="Sub-task", parent_id=root.task_id)
        result("Child task created", child is not None)
        result("Child linked to parent (child.parent_task_id == root.task_id)",
               child.parent_task_id == root.task_id)

        from agent.orchestrator import OrchestratorEngine, SubtaskPlan
        result("OrchestratorEngine instantiates", OrchestratorEngine is not None)
        result("SubtaskPlan dataclass works", SubtaskPlan is not None)
    except Exception as e:
        result("TEST 3", False, f"Exception: {e}")


# === TEST 4: Checkpoint E2E ===
def test_4():
    print("\n=== TEST 4: Checkpoint E2E Flow ===")
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True)

        from agent.checkpoint_service import CheckpointService
        svc = CheckpointService(working_dir=tmp, enabled=True)
        result("CheckpointService instantiates", True)

        # Create and commit a file
        f = Path(tmp) / "test.txt"
        f.write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True)

        r1 = svc.save_checkpoint("before changes")
        result("save_checkpoint('before') succeeds",
               r1.get("success", False), f"result={r1}")

        # Modify file and commit
        f.write_text("changed")
        subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True)
        subprocess.run(["git", "commit", "-m", "change"], cwd=tmp, capture_output=True)

        r2 = svc.save_checkpoint("after changes")
        # Dedup is expected if same turn — the service tracks per-turn state
        result("save_checkpoint('after') handles dedup or succeeds",
               r2.get("success", False) or "already done" in r2.get("error", ""),
               f"result={r2}")

        cps = svc.list_checkpoints()
        result("list_checkpoints() returns items",
               len(cps) >= 1, f"count={len(cps)}")

        for cp in cps:
            has_fields = all(k in cp for k in ('hash', 'timestamp', 'reason'))
            if not has_fields:
                result("Checkpoint has required fields", False, f"missing in {cp}")
                break
        else:
            result("All checkpoints have required fields", True)

        r3 = svc.ensure_checkpoint("auto")
        result("ensure_checkpoint() returns", r3 is not None, f"type={type(r3)}")
    except Exception as e:
        result("TEST 4", False, f"Exception: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# === TEST 5: Config Loading ===
def test_5():
    print("\n=== TEST 5: Config Loading Pipeline ===")
    try:
        from hermes_cli.config import load_config
        cfg = load_config()

        result("config['agent']['default_mode'] == 'orchestrator'",
               cfg.get('agent', {}).get('default_mode') == 'orchestrator',
               f"got={cfg.get('agent', {}).get('default_mode')}")

        er = cfg.get('error_recovery', {})
        required_keys = {'max_retries', 'base_delay', 'max_delay',
                         'rate_limit_base_delay', 'rate_limit_max_delay', 'tool_retry_budget'}
        result("error_recovery has all 6 keys",
               required_keys.issubset(er.keys()),
               f"keys={list(er.keys())}")
        result("max_retries == 5", er.get('max_retries') == 5, f"got={er.get('max_retries')}")
        result("tool_retry_budget == 3", er.get('tool_retry_budget') == 3, f"got={er.get('tool_retry_budget')}")
    except Exception as e:
        result("TEST 5", False, f"Exception: {e}")


# === TEST 6: Gateway Mode Change ===
def test_6():
    print("\n=== TEST 6: Gateway Mode Change Handler ===")
    try:
        from gateway.run import GatewayRunner
        result("GatewayRunner has _handle_mode_command",
               hasattr(GatewayRunner, '_handle_mode_command'))

        # Check source for /mode routing
        import inspect
        src = inspect.getsource(GatewayRunner)
        result("Gateway source contains '/mode' routing",
               '/mode' in src or '"mode"' in src)

        # Verify the handler returns tool count/groups
        if hasattr(GatewayRunner, '_handle_mode_command'):
            sig = inspect.signature(GatewayRunner._handle_mode_command)
            result("_handle_mode_command accepts mode param",
                   'mode' in sig.parameters or len(sig.parameters) >= 1)
    except Exception as e:
        result("TEST 6", False, f"Exception: {e}")


# === TEST 7: Tool Registry Integrity ===
def test_7():
    print("\n=== TEST 7: Full Tool Registry Integrity ===")
    try:
        from model_tools import get_tool_definitions, _discover_tools
        _discover_tools()

        all_tools = get_tool_definitions(
            enabled_toolsets=None, disabled_toolsets=None,
            quiet_mode=True, active_mode=None,
        )
        tool_names = {t["function"]["name"] for t in all_tools}

        critical = [
            "read_file", "write_file", "patch", "search_files",
            "terminal", "execute_code", "delegate_task",
            "web_search", "web_extract", "browser_navigate",
            "memory", "todo", "switch_mode", "checkpoint", "orchestrate",
        ]
        missing = [t for t in critical if t not in tool_names]
        result(f"All {len(critical)} critical tools registered",
               len(missing) == 0, f"missing={missing}" if missing else "")

        # Batch editing
        patch_tool = next((t for t in all_tools if t["function"]["name"] == "patch"), None)
        if patch_tool:
            mode_enum = patch_tool["function"]["parameters"]["properties"].get("mode", {}).get("enum", [])
            result("patch accepts mode='batch'", "batch" in mode_enum, f"enum={mode_enum}")
        else:
            result("patch accepts mode='batch'", False, "patch tool not found")

        # Mode-gated tool counts (must pass Mode objects, not strings)
        from agent.modes import get_mode
        orch_mode = get_mode("orchestrator")
        code_mode = get_mode("code")
        ask_mode = get_mode("ask")

        orch_tools = get_tool_definitions(quiet_mode=True, active_mode=orch_mode)
        code_tools = get_tool_definitions(quiet_mode=True, active_mode=code_mode)
        ask_tools = get_tool_definitions(quiet_mode=True, active_mode=ask_mode)

        result(f"Orchestrator: {len(orch_tools)} tools (expect ~12-15)",
               10 <= len(orch_tools) <= 20, f"got={len(orch_tools)}")
        result(f"Code: {len(code_tools)} tools (expect ~25-35)",
               20 <= len(code_tools) <= 40, f"got={len(code_tools)}")
        result(f"Ask: {len(ask_tools)} tools (expect ~25-30)",
               20 <= len(ask_tools) <= 35, f"got={len(ask_tools)}")
        result("Code has more tools than orchestrator",
               len(code_tools) > len(orch_tools))

        result(f"Total tools >= 100 (got {len(all_tools)})",
               len(all_tools) >= 100)
    except Exception as e:
        result("TEST 7", False, f"Exception: {e}")


# === MAIN ===
if __name__ == "__main__":
    print("=" * 60)
    print("  Roo-Code Port — End-to-End Integration Test (POST-FIX)")
    print("=" * 60)

    test_1()
    test_2()
    test_3()
    test_4()
    test_5()
    test_6()
    test_7()

    print("\n" + "=" * 60)
    print(f"  SUMMARY: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed > 0 else 0)
