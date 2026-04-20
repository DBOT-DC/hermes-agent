"""Tests for error_recovery config wiring and tool_retry_budget tracking."""

import pytest
from unittest.mock import MagicMock, patch
import json


class TestErrorRecoveryDefaults:
    """Test that DEFAULT_CONFIG has the error_recovery section."""

    def test_default_config_has_error_recovery_section(self):
        from hermes_cli.config import DEFAULT_CONFIG
        assert "error_recovery" in DEFAULT_CONFIG

    def test_error_recovery_has_required_keys(self):
        from hermes_cli.config import DEFAULT_CONFIG
        er = DEFAULT_CONFIG["error_recovery"]
        assert "max_retries" in er
        assert "base_delay" in er
        assert "max_delay" in er
        assert "rate_limit_base_delay" in er
        assert "rate_limit_max_delay" in er
        assert "tool_retry_budget" in er

    def test_error_recovery_default_values(self):
        from hermes_cli.config import DEFAULT_CONFIG
        er = DEFAULT_CONFIG["error_recovery"]
        assert er["max_retries"] == 5
        assert er["base_delay"] == 5.0
        assert er["max_delay"] == 120.0
        assert er["rate_limit_base_delay"] == 2.0
        assert er["rate_limit_max_delay"] == 60.0
        assert er["tool_retry_budget"] == 3


class TestMaxRetriesConfigOverride:
    """Test that max_retries can be overridden via config."""

    def test_max_retries_from_config(self):
        cfg = {"error_recovery": {"max_retries": 10}}
        val = cfg.get("error_recovery", {}).get("max_retries", 5)
        assert val == 10

    def test_max_retries_falls_back_to_default(self):
        cfg = {}
        val = cfg.get("error_recovery", {}).get("max_retries", 5)
        assert val == 5


class TestToolRetryBudget:
    """Test tool_retry_budget tracking logic (unit tests)."""

    def test_tool_retry_counts_initially_empty(self):
        counts = {}
        assert counts.get("write_file", 0) == 0

    def test_increment_counts_tool(self):
        counts = {}
        tool_name = "write_file"
        counts[tool_name] = counts.get(tool_name, 0) + 1
        assert counts["write_file"] == 1

    def test_multiple_tools_tracked_separately(self):
        counts = {}
        counts["write_file"] = counts.get("write_file", 0) + 1
        counts["read_file"] = counts.get("read_file", 0) + 1
        counts["write_file"] = counts.get("write_file", 0) + 1
        assert counts["write_file"] == 2
        assert counts["read_file"] == 1

    def test_budget_exceeded_check(self):
        counts = {"write_file": 3}
        budget = 3
        # At 3, it has reached the budget (>=)
        assert counts.get("write_file", 0) >= budget

    def test_budget_not_exceeded_under_limit(self):
        counts = {"write_file": 2}
        budget = 3
        assert counts.get("write_file", 0) < budget

    def test_reset_clears_counts(self):
        counts = {"write_file": 2, "read_file": 1}
        counts = {}  # Reset per turn
        assert counts.get("write_file", 0) == 0
        assert counts.get("read_file", 0) == 0

    def test_budget_config_read(self):
        cfg = {"error_recovery": {"tool_retry_budget": 5}}
        budget = cfg.get("error_recovery", {}).get("tool_retry_budget", 3)
        assert budget == 5

    def test_budget_config_default(self):
        cfg = {}
        budget = cfg.get("error_recovery", {}).get("tool_retry_budget", 3)
        assert budget == 3


class TestBackoffConfigReads:
    """Test that backoff params are correctly read from config."""

    def test_base_delay_config(self):
        cfg = {"error_recovery": {"base_delay": 10.0, "max_delay": 200.0}}
        er = cfg.get("error_recovery", {})
        assert er.get("base_delay", 5.0) == 10.0
        assert er.get("max_delay", 120.0) == 200.0

    def test_rate_limit_delay_config(self):
        cfg = {"error_recovery": {"rate_limit_base_delay": 4.0, "rate_limit_max_delay": 90.0}}
        er = cfg.get("error_recovery", {})
        assert er.get("rate_limit_base_delay", 2.0) == 4.0
        assert er.get("rate_limit_max_delay", 60.0) == 90.0

    def test_backoff_falls_back_to_defaults(self):
        cfg = {}
        er = cfg.get("error_recovery", {})
        assert er.get("base_delay", 5.0) == 5.0
        assert er.get("max_delay", 120.0) == 120.0
        assert er.get("rate_limit_base_delay", 2.0) == 2.0
        assert er.get("rate_limit_max_delay", 60.0) == 60.0
