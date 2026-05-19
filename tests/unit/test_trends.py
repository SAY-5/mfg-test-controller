"""Unit tests for measurement trend analysis and drift detection."""

from __future__ import annotations

from mfg_test_controller.controller.sequencer import StationReport, StepOutcome
from mfg_test_controller.store import RunStore
from mfg_test_controller.trends import (
    ControlState,
    analyse_register,
    classify,
    estimate_runs_to_failure,
    linear_slope,
    render_trends_markdown,
)


def _seed_run(store: RunStore, plan: str, register: str, measured: float) -> None:
    """Persist a one-step run that recorded a single register read."""
    report = StationReport(plan_name=plan)
    report.outcomes = [
        StepOutcome("read_reg", "dmm", "read", register, True, measured, "ok", 0.001),
    ]
    report.duration_s = 0.01
    store.save_report(report, {"dmm": "dmm"})


def test_linear_slope_matches_known_ramp() -> None:
    # y = 2x + 100
    values = [100.0 + 2.0 * i for i in range(10)]
    assert linear_slope(values) == 2.0


def test_classify_stable_series_is_in_control() -> None:
    values = [500.0, 501.0, 499.0, 500.0, 501.0, 499.0, 500.0]
    slope = linear_slope(values)
    from statistics import pstdev

    assert classify(values, slope, pstdev(values)) is ControlState.IN_CONTROL


def test_drift_detected_with_seeded_history() -> None:
    """Seed a deliberately drifting register and assert drift detection.

    The ramp is start=4000, step=+25/run over 12 runs. The threshold limit
    is 5000. Hand-computed values:

    * seeded slope: 25.0 per run
    * last value: 4000 + 25 * 11 = 4275
    * runs-to-failure: (5000 - 4275) / 25 = 29.0
    """
    store = RunStore("sqlite:///:memory:")
    start, step, runs = 4000.0, 25.0, 12
    for i in range(runs):
        _seed_run(store, "stationA", "dc_voltage", start + step * i)

    history = store.register_history("dc_voltage", station="stationA")
    values = [measured for _device, measured in history]
    assert len(values) == runs

    trend = analyse_register("dc_voltage", "dmm", values, limit=5000.0)

    assert trend.state is ControlState.TRENDING
    # Detected slope must match the seeded +25/run ramp within tolerance.
    assert abs(trend.slope - step) < 1e-6
    # Runs-to-failure: hand-computed 29.0.
    assert trend.runs_to_failure is not None
    assert abs(trend.runs_to_failure - 29.0) < 1e-6


def test_in_control_register_has_no_runs_to_failure() -> None:
    """A stable register classifies in-control with no runs-to-failure."""
    store = RunStore("sqlite:///:memory:")
    stable = [500.0, 501.0, 499.0, 500.0, 502.0, 498.0, 500.0, 501.0]
    for value in stable:
        _seed_run(store, "stationB", "dc_current", value)

    history = store.register_history("dc_current", station="stationB")
    values = [measured for _device, measured in history]

    trend = analyse_register("dc_current", "dmm", values, limit=5000.0)

    assert trend.state is ControlState.IN_CONTROL
    assert trend.runs_to_failure is None


def test_out_of_control_point_breaches_control_limit() -> None:
    # A tight baseline plus one spike: the spike sits well beyond the
    # 3-sigma control limits of the established series.
    baseline = [500.0, 501.0, 499.0, 500.0, 501.0, 499.0, 500.0, 501.0, 499.0]
    values = [*baseline, 560.0, *baseline]
    slope = linear_slope(values)
    from statistics import pstdev

    assert classify(values, slope, pstdev(values)) is ControlState.OUT_OF_CONTROL


def test_runs_to_failure_none_when_drifting_away() -> None:
    values = [4000.0 - 25.0 * i for i in range(6)]
    slope = linear_slope(values)
    assert estimate_runs_to_failure(values, slope, limit=5000.0) is None


def test_measured_registers_lists_distinct_pairs() -> None:
    store = RunStore("sqlite:///:memory:")
    _seed_run(store, "stationC", "dc_voltage", 100.0)
    _seed_run(store, "stationC", "dc_current", 200.0)
    _seed_run(store, "stationC", "dc_voltage", 110.0)

    pairs = store.measured_registers("stationC")
    assert ("dmm", "dc_voltage") in pairs
    assert ("dmm", "dc_current") in pairs
    assert len(pairs) == 2


def test_markdown_report_has_table_and_trending_section() -> None:
    drifting = analyse_register(
        "dc_voltage", "dmm", [4000.0 + 25.0 * i for i in range(12)], limit=5000.0
    )
    stable = analyse_register(
        "dc_current", "dmm", [500.0, 501.0, 499.0, 500.0, 501.0], limit=5000.0
    )
    report = render_trends_markdown([drifting, stable])

    assert "# Measurement trend analysis" in report
    assert "| Register | Device | Samples |" in report
    assert "| dc_voltage | dmm |" in report
    assert "## Trending toward a limit" in report
