"""Latency instrumentation — EMF metrics and cold-start detection for Brainy Bob."""

from __future__ import annotations

import json
import time

# Module-level cold-start flag. True on the first invocation of the Lambda container,
# False on all subsequent warm invocations. Flipped by consume_cold_start().
_IS_COLD_START: bool = True

EMF_NAMESPACE = "BrainyBob"

_METRIC_DEFS = [
    ("total_duration_ms",  "total_ms"),
    ("openai_duration_ms", "openai_ms"),
    ("ddb_load_ms",        "ddb_load_ms"),
    ("ddb_save_ms",        "ddb_save_ms"),
]


def consume_cold_start() -> bool:
    """
    Returns True on the first call (cold start), False on all subsequent calls
    within the same Lambda container lifetime.
    """
    global _IS_COLD_START
    was_cold = _IS_COLD_START
    _IS_COLD_START = False
    return was_cold


def emit_emf(
    intent: str,
    is_cold: bool,
    total_ms: float,
    openai_ms: float | None,
    ddb_load_ms: float | None,
    ddb_save_ms: float | None,
) -> None:
    """
    Print an EMF-structured JSON object to stdout. CloudWatch Logs ingests this
    line and extracts metrics into the BrainyBob custom namespace automatically.
    None values are omitted from the payload — absent differs from zero in CloudWatch.
    """
    values: dict[str, float] = {"total_ms": total_ms}
    if openai_ms is not None:
        values["openai_ms"] = openai_ms
    if ddb_load_ms is not None:
        values["ddb_load_ms"] = ddb_load_ms
    if ddb_save_ms is not None:
        values["ddb_save_ms"] = ddb_save_ms

    metrics = [
        {"Name": emf_name, "Unit": "Milliseconds"}
        for emf_name, key in _METRIC_DEFS
        if key in values
    ]

    payload: dict = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": EMF_NAMESPACE,
                    "Dimensions": [["intent", "cold_start"]],
                    "Metrics": metrics,
                }
            ],
        },
        "intent": intent,
        "cold_start": "true" if is_cold else "false",
    }

    for emf_name, key in _METRIC_DEFS:
        if key in values:
            payload[emf_name] = round(values[key], 2)

    print(json.dumps(payload))
