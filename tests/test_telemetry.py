"""Tests for src/telemetry.py — EMF metrics and cold-start detection."""

from __future__ import annotations

import importlib
import json
import os

import pytest

os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:000000000000:secret:test")
os.environ.setdefault("MAX_OUTPUT_TOKENS", "280")
os.environ.setdefault("OPENAI_REQUEST_TIMEOUT", "10")

import src.telemetry as telemetry_module
from src.telemetry import EMF_NAMESPACE, consume_cold_start, emit_emf


@pytest.fixture(autouse=True)
def reset_cold_start():
    """Reset the cold-start flag before and after every test."""
    telemetry_module._IS_COLD_START = True
    yield
    telemetry_module._IS_COLD_START = True


# ---------------------------------------------------------------------------
# TestColdStart
# ---------------------------------------------------------------------------

class TestColdStart:
    def test_returns_true_on_first_call(self):
        assert consume_cold_start() is True

    def test_returns_false_on_second_call(self):
        consume_cold_start()
        assert consume_cold_start() is False

    def test_returns_false_on_subsequent_calls(self):
        consume_cold_start()
        consume_cold_start()
        assert consume_cold_start() is False

    def test_flag_resets_when_module_variable_reset(self):
        consume_cold_start()
        telemetry_module._IS_COLD_START = True
        assert consume_cold_start() is True


# ---------------------------------------------------------------------------
# TestEmitEmf
# ---------------------------------------------------------------------------

class TestEmitEmf:
    def _capture(self, capsys, **kwargs) -> dict:
        """Call emit_emf with given kwargs and return parsed JSON from stdout."""
        defaults = dict(
            intent="ChatIntent",
            is_cold=False,
            total_ms=500.0,
            openai_ms=400.0,
            ddb_load_ms=30.0,
            ddb_save_ms=20.0,
        )
        defaults.update(kwargs)
        emit_emf(**defaults)
        captured = capsys.readouterr()
        return json.loads(captured.out.strip())

    def test_output_is_valid_json(self, capsys):
        emit_emf("ChatIntent", False, 500.0, 400.0, 30.0, 20.0)
        out = capsys.readouterr().out.strip()
        json.loads(out)  # must not raise

    def test_contains_aws_key(self, capsys):
        data = self._capture(capsys)
        assert "_aws" in data

    def test_namespace_is_brainybob(self, capsys):
        data = self._capture(capsys)
        ns = data["_aws"]["CloudWatchMetrics"][0]["Namespace"]
        assert ns == EMF_NAMESPACE

    def test_dimensions_are_intent_and_cold_start(self, capsys):
        data = self._capture(capsys)
        dims = data["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert dims == [["intent", "cold_start"]]

    def test_total_ms_present_with_correct_value(self, capsys):
        data = self._capture(capsys, total_ms=123.456)
        assert "total_duration_ms" in data
        assert data["total_duration_ms"] == 123.46  # rounded to 2dp

    def test_openai_ms_present_when_provided(self, capsys):
        data = self._capture(capsys, openai_ms=300.0)
        assert "openai_duration_ms" in data

    def test_openai_ms_absent_when_none(self, capsys):
        data = self._capture(capsys, openai_ms=None)
        assert "openai_duration_ms" not in data

    def test_ddb_load_ms_absent_when_none(self, capsys):
        data = self._capture(capsys, ddb_load_ms=None)
        assert "ddb_load_ms" not in data

    def test_ddb_save_ms_absent_when_none(self, capsys):
        data = self._capture(capsys, ddb_save_ms=None)
        assert "ddb_save_ms" not in data

    def test_cold_start_true_is_string(self, capsys):
        data = self._capture(capsys, is_cold=True)
        assert data["cold_start"] == "true"
        assert isinstance(data["cold_start"], str)

    def test_cold_start_false_is_string(self, capsys):
        data = self._capture(capsys, is_cold=False)
        assert data["cold_start"] == "false"
        assert isinstance(data["cold_start"], str)

    def test_intent_dimension_value(self, capsys):
        data = self._capture(capsys, intent="AskAIIntent")
        assert data["intent"] == "AskAIIntent"

    def test_timestamp_is_epoch_ms(self, capsys):
        data = self._capture(capsys)
        ts = data["_aws"]["Timestamp"]
        assert isinstance(ts, int)
        assert ts > 1_000_000_000_000  # epoch ms, not seconds

    def test_metrics_array_omits_none_entries(self, capsys):
        data = self._capture(capsys, ddb_load_ms=None, ddb_save_ms=None)
        metric_names = [m["Name"] for m in data["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
        assert "ddb_load_ms" not in metric_names
        assert "ddb_save_ms" not in metric_names

    def test_all_metrics_present_when_all_provided(self, capsys):
        data = self._capture(capsys)
        metric_names = [m["Name"] for m in data["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
        assert "total_duration_ms" in metric_names
        assert "openai_duration_ms" in metric_names
        assert "ddb_load_ms" in metric_names
        assert "ddb_save_ms" in metric_names

    def test_none_only_total_ms_still_valid_emf(self, capsys):
        data = self._capture(capsys, openai_ms=None, ddb_load_ms=None, ddb_save_ms=None)
        assert "total_duration_ms" in data
        metric_names = [m["Name"] for m in data["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
        assert metric_names == ["total_duration_ms"]
