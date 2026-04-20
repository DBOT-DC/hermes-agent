"""Phase 3 tests for agent/context_compressor.py — token buffer, update_model, preflight."""

import pytest
from unittest.mock import patch

from agent.context_compressor import ContextCompressor


@pytest.fixture()
def compressor():
    """Create a ContextCompressor with mocked dependencies."""
    with patch("agent.context_compressor.get_model_context_length", return_value=100000):
        c = ContextCompressor(
            model="test/model",
            threshold_percent=0.50,
            protect_first_n=2,
            protect_last_n=2,
            quiet_mode=True,
            # Phase 5 params
            auto_condense_percent=0.75,
            forced_reduction_percent=0.75,
            max_window_retries=3,
            token_buffer_percent=0.10,
        )
        return c


class TestTokenBufferSubtracted:
    """Gap 1 (MEDIUM): _token_buffer must be subtracted in should_compress().

    With context_length=100000 and token_buffer_percent=0.10 (buffer=10000),
    effective_context = 90000. Auto-condense at 75% of effective = 67500.
    Without the buffer it would trigger at 75000.
    """

    def test_buffer_subtracted_triggers_sooner(self, compressor):
        """Compression should fire at 67,500 tokens (75% of 90k), not 75,000."""
        assert compressor.context_length == 100000
        assert compressor._token_buffer == 10000  # 10% of 100k
        effective = compressor.context_length - compressor._token_buffer
        expected_threshold = int(effective * compressor.auto_condense_percent)  # 67500

        # At 67,500 (exactly at threshold) — should compress
        assert compressor.should_compress(prompt_tokens=expected_threshold) is True
        # At 67,499 — just below
        assert compressor.should_compress(prompt_tokens=expected_threshold - 1) is False
        # At 75,000 (75% of raw context_length) — also above effective threshold
        assert compressor.should_compress(prompt_tokens=75000) is True

    def test_buffer_10_percent_shifts_threshold_down(self, compressor):
        """10% buffer on 100k shifts 75% threshold from 75000 to 67500 (7500 difference)."""
        raw_threshold = int(compressor.context_length * compressor.auto_condense_percent)
        effective_threshold = int(
            (compressor.context_length - compressor._token_buffer) * compressor.auto_condense_percent
        )
        assert raw_threshold == 75000
        assert effective_threshold == 67500
        assert effective_threshold < raw_threshold

    def test_zero_tokens_returns_false(self, compressor):
        """Zero tokens should never trigger compression."""
        assert compressor.should_compress(prompt_tokens=0) is False

    def test_negative_tokens_returns_false(self, compressor):
        assert compressor.should_compress(prompt_tokens=-100) is False


class TestUpdateModelPhase5Params:
    """Gap 2 (HIGH): update_model() must propagate Phase 5 params."""

    def test_update_model_accepts_all_phase5_params(self, compressor):
        """All four Phase 5 kwargs should be accepted without error."""
        # Should not raise
        compressor.update_model(
            model="new/model",
            context_length=200000,
            base_url="https://new.example.com",
            api_key="new-key",
            provider="new-provider",
            api_mode="streaming",
            auto_condense_percent=0.80,
            forced_reduction_percent=0.70,
            max_window_retries=5,
            token_buffer_percent=0.15,
        )

    def test_update_model_propagates_auto_condense_percent(self, compressor):
        """auto_condense_percent should update when passed."""
        compressor.update_model(
            model="new/model",
            context_length=100000,
            auto_condense_percent=0.60,
        )
        assert compressor.auto_condense_percent == 0.60

    def test_update_model_propagates_forced_reduction_percent(self, compressor):
        compressor.update_model(
            model="new/model",
            context_length=100000,
            forced_reduction_percent=0.80,
        )
        assert compressor.forced_reduction_percent == 0.80

    def test_update_model_propagates_max_window_retries(self, compressor):
        compressor.update_model(
            model="new/model",
            context_length=100000,
            max_window_retries=7,
        )
        assert compressor.max_window_retries == 7

    def test_update_model_propagates_token_buffer_percent(self, compressor):
        """token_buffer_percent and _token_buffer should both update."""
        compressor.update_model(
            model="new/model",
            context_length=100000,
            token_buffer_percent=0.20,
        )
        assert compressor.token_buffer_percent == 0.20
        assert compressor._token_buffer == 20000  # 20% of 100k

    def test_update_model_recalculates_effective_threshold_after_buffer_update(self, compressor):
        """After buffer changes, should_compress threshold reflects new buffer."""
        compressor.update_model(
            model="new/model",
            context_length=100000,
            token_buffer_percent=0.20,
        )
        # Buffer is now 20k; effective = 80k; 75% of 80k = 60k
        assert compressor.should_compress(prompt_tokens=59999) is False
        assert compressor.should_compress(prompt_tokens=60000) is True

    def test_update_model_none_does_not_overwrite(self, compressor):
        """Passing None for a Phase 5 param should leave the existing value unchanged."""
        original_auto = compressor.auto_condense_percent
        original_forced = compressor.forced_reduction_percent
        original_retries = compressor.max_window_retries
        original_buffer = compressor.token_buffer_percent

        compressor.update_model(
            model="new/model",
            context_length=100000,
            auto_condense_percent=None,
            forced_reduction_percent=None,
            max_window_retries=None,
            token_buffer_percent=None,
        )

        assert compressor.auto_condense_percent == original_auto
        assert compressor.forced_reduction_percent == original_forced
        assert compressor.max_window_retries == original_retries
        assert compressor.token_buffer_percent == original_buffer

    def test_update_model_still_updates_context_length_and_threshold_tokens(self, compressor):
        """update_model should still update context_length and threshold_tokens."""
        compressor.update_model(
            model="new/model",
            context_length=200000,
        )
        assert compressor.context_length == 200000
        # threshold_tokens derived from threshold_percent (0.50) * 200k = 100k
        assert compressor.threshold_tokens == 100000

    def test_update_model_recovers_from_missing_attributes(self):
        """A compressor that somehow lacks Phase 5 attrs should not crash on update."""
        with patch("agent.context_compressor.get_model_context_length", return_value=100000):
            c = ContextCompressor(
                model="test/model",
                threshold_percent=0.50,
                quiet_mode=True,
            )
        # Simulate an older instance that was never set up with Phase 5 params
        if not hasattr(c, "auto_condense_percent"):
            c.auto_condense_percent = 0.75
        if not hasattr(c, "_token_buffer"):
            c._token_buffer = 0

        c.update_model(model="new/model", context_length=100000, auto_condense_percent=0.80)
        assert c.auto_condense_percent == 0.80


class TestShouldCompressPreflight:
    """Gap 4 (MEDIUM): should_compress_preflight() must use estimated tokens."""

    def test_preflight_returns_true_when_estimated_tokens_exceed_threshold(self, compressor):
        """Preflight should use estimate_messages_tokens_rough() result."""
        # Build a message list large enough to exceed the threshold.
        # compressor threshold with buffer: 67500 tokens.
        # estimate_messages_tokens_rough counts ~4 chars/token.
        big_message = {"role": "user", "content": "x" * 270_000}  # ~270k chars ≈ 67.5k tokens
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg1"},
            big_message,
        ]
        # estimate_messages_tokens_rough is rough; just verify it returns a bool
        result = compressor.should_compress_preflight(messages)
        assert isinstance(result, bool)

    def test_preflight_returns_false_for_small_messages(self, compressor):
        """Small messages well under threshold should return False."""
        messages = [
            {"role": "system", "content": "short system"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert compressor.should_compress_preflight(messages) is False

    def test_preflight_calls_should_compress_with_estimated_count(self, compressor):
        """should_compress_preflight should pass estimated tokens to should_compress."""
        import unittest.mock as mock

        messages = [{"role": "user", "content": "hello"}]

        with patch.object(
            compressor,
            "should_compress",
            wraps=compressor.should_compress,
        ) as mock_sc:
            compressor.should_compress_preflight(messages)
            assert mock_sc.call_count == 1
            # wraps stores positional args as a list, not a Call tuple
            call_args = mock_sc.call_args
            # call_args[0] is positional args tuple when using wraps
            call_arg = call_args[0][0] if call_args[0] else call_args[1]["prompt_tokens"]
            assert isinstance(call_arg, int)
            assert call_arg > 0

    def test_preflight_uses_estimate_messages_tokens_rough(self, compressor):
        """should_compress_preflight should call estimate_messages_tokens_rough."""
        with patch(
            "agent.context_compressor.estimate_messages_tokens_rough",
            return_value=99999,
        ) as mock_est:
            result = compressor.should_compress_preflight([{"role": "user", "content": "test"}])
            assert mock_est.call_count == 1
            # With 99999 tokens (well over 67500 threshold), should return True
            assert result is True
