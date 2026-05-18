"""Unit tests for the test-cycle benchmark helpers.

The bench lives in ``bench/cycle_bench.py`` (a top-level script, not part of
the installed package), so it is loaded here by file path. These tests cover
the percentile maths, the profile builders, a short end-to-end bench run, and
the regression-check decision.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_PATH = REPO_ROOT / "bench" / "cycle_bench.py"


def _load_bench() -> ModuleType:
    """Import the bench script as a module by file path."""
    spec = importlib.util.spec_from_file_location("cycle_bench", BENCH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_bench()


def test_percentile_nearest_rank() -> None:
    """The percentile helper uses nearest-rank ordering."""
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert bench._percentile(samples, 50) == 5.0
    assert bench._percentile(samples, 90) == 9.0
    assert bench._percentile(samples, 99) == 10.0
    assert bench._percentile(samples, 100) == 10.0


def test_percentile_empty_is_zero() -> None:
    """An empty sample set yields a zero percentile."""
    assert bench._percentile([], 95) == 0.0


def test_clean_and_fault_profiles_cover_four_devices() -> None:
    """Both profile builders return the four simulated devices."""
    clean = bench._clean_profiles()
    faulted = bench._fault_profiles()
    assert set(clean) == {"power_supply", "dmm", "actuator", "thermocouple"}
    assert set(faulted) == set(clean)
    assert all(not p.faults for p in clean.values())
    assert all(p.faults for p in faulted.values())


def test_run_bench_produces_timing_sections() -> None:
    """A short bench run yields clean and fault-injected timing sections."""
    result = asyncio.run(bench.run_bench(iterations=5))
    for label in ("clean", "fault_injected"):
        section = result[label]
        assert section["iterations"] == 5
        assert section["commands_per_cycle"] == 11
        assert section["throughput_commands_per_s"] > 0
        cycle = section["cycle_wall_clock_s"]
        assert cycle["p50"] <= cycle["p95"] <= cycle["p99"]
        latency = section["command_latency_ms"]
        assert latency["p50"] <= latency["p95"] <= latency["p99"]


def test_check_regression_passes_within_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run within the drift budget passes; one past it fails."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    monkeypatch.setattr(bench, "RESULTS_DIR", results_dir)
    baseline = {"clean": {"cycle_wall_clock_s": {"mean": 0.001}}}
    (results_dir / "20260101T000000Z.json").write_text(json.dumps(baseline))
    # 1.25 ms is within the +30% budget (limit 1.30 ms).
    current_ok = {"clean": {"cycle_wall_clock_s": {"mean": 0.00125}}}
    assert bench._check_regression(current_ok, drift=0.30) == 0
    # 1.45 ms is past the budget and must fail.
    current_bad = {"clean": {"cycle_wall_clock_s": {"mean": 0.00145}}}
    assert bench._check_regression(current_bad, drift=0.30) == 1


def test_check_regression_records_first_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no stored baseline the check records the current run and passes."""
    results_dir = tmp_path / "results"
    monkeypatch.setattr(bench, "RESULTS_DIR", results_dir)
    current = {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "clean": {"cycle_wall_clock_s": {"mean": 0.001}},
    }
    assert bench._check_regression(current, drift=0.30) == 0
    assert list(results_dir.glob("*.json"))
