"""Unit tests for station report rendering and persistence."""

from __future__ import annotations

import json

from mfg_test_controller.controller.sequencer import StationReport, StepOutcome
from mfg_test_controller.report import (
    render_console,
    render_json,
    render_markdown,
)
from mfg_test_controller.store import RunStore


def _report() -> StationReport:
    report = StationReport(plan_name="demo")
    report.outcomes = [
        StepOutcome("step_a", "dmm", "read", "dc_voltage", True, 5000.0, "ok", 0.001),
        StepOutcome("step_b", "dmm", "read", "dc_current", False, 900.0, "out of range", 0.002),
    ]
    report.duration_s = 0.05
    return report


def test_report_aggregates_pass_fail() -> None:
    report = _report()
    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    assert not report.all_passed
    assert report.first_failure is not None
    assert report.first_failure.name == "step_b"


def test_render_json_is_valid_json() -> None:
    parsed = json.loads(render_json(_report()))
    assert parsed["summary"]["failed"] == 1
    assert parsed["summary"]["first_failure"] == "step_b"
    assert len(parsed["steps"]) == 2


def test_render_markdown_has_table_and_verdict() -> None:
    text = render_markdown(_report())
    assert "Result: FAIL" in text
    assert "| step_a |" in text
    assert "First failing step: step_b" in text


def test_render_console_is_compact() -> None:
    text = render_console(_report())
    assert "[FAIL]" in text
    assert "1/2 passed" in text


def test_store_round_trip(tmp_path: object) -> None:
    db_path = f"{tmp_path}/runs.db"  # type: ignore[str-bytes-safe]
    store = RunStore(f"sqlite:///{db_path}")
    run_id = store.save_report(_report(), {"dmm": "dmm"})
    loaded = store.get_run(run_id)
    assert loaded is not None
    assert loaded.plan_name == "demo"
    assert loaded.passed_steps == 1
    assert loaded.failed_steps == 1
    assert len(loaded.steps) == 2


def test_store_lists_runs_newest_first(tmp_path: object) -> None:
    db_path = f"{tmp_path}/runs.db"  # type: ignore[str-bytes-safe]
    store = RunStore(f"sqlite:///{db_path}")
    first = store.save_report(_report(), {"dmm": "dmm"})
    second = store.save_report(_report(), {"dmm": "dmm"})
    runs = store.list_runs()
    assert [r.id for r in runs[:2]] == [second, first]
