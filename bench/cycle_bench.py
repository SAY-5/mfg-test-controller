"""Test-cycle benchmark for the manufacturing test controller.

Runs the ``station_bringup`` plan repeatedly against the four simulated
devices over loopback TCP and measures:

* per-cycle wall-clock time (one full plan run)
* per-command round-trip latency, reported as P50/P95/P99
* controller throughput in commands per second

A second pass runs the same plan with drift and delay faults injected so the
fault-handling cost is visible next to the clean numbers.

Results are written as JSON to ``bench/results/<timestamp>.json``. The
``--check`` mode compares a fresh run against a stored baseline and fails if
the per-cycle wall-clock regresses by more than the allowed drift; this backs
the ``make bench-regress`` gate.

The benchmark is hermetic: every device is an in-process
:class:`SimulatedDevice` served on an ephemeral 127.0.0.1 port.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mfg_test_controller.config import DeviceProfile, FaultConfig, TestPlan, load_test_plan
from mfg_test_controller.controller.client import DeviceClient
from mfg_test_controller.controller.sequencer import Sequencer, StationReport
from mfg_test_controller.device.profiles import builtin_profile, builtin_profile_names
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.server import DeviceServer

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO_ROOT / "plans" / "station_bringup.yaml"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LOOPBACK = "127.0.0.1"

DEFAULT_ITERATIONS = 200
DEFAULT_DRIFT = 0.30
"""Allowed per-cycle wall-clock regression for the bench-regress gate."""


def _percentile(samples: Sequence[float], pct: float) -> float:
    """Return the ``pct`` percentile (0..100) of ``samples`` via nearest rank."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, round(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _fault_profiles() -> dict[str, DeviceProfile]:
    """Built-in profiles with a drift and a delay fault injected."""
    profiles: dict[str, DeviceProfile] = {}
    for name in builtin_profile_names():
        profile = builtin_profile(name)
        faults = [FaultConfig(kind="drift", amount=1)]
        if name == "dmm":
            faults.append(FaultConfig(kind="delay", delay_seconds=0.001))
        profiles[name] = profile.model_copy(update={"faults": faults})
    return profiles


def _clean_profiles() -> dict[str, DeviceProfile]:
    """Built-in profiles with no faults."""
    return {name: builtin_profile(name) for name in builtin_profile_names()}


async def _run_cycles(
    plan: TestPlan, profiles: dict[str, DeviceProfile], iterations: int
) -> dict[str, Any]:
    """Run ``plan`` ``iterations`` times and collect timing statistics."""
    servers: dict[str, DeviceServer] = {}
    for name, profile in profiles.items():
        server = DeviceServer(SimulatedDevice(profile), LOOPBACK, 0)
        await server.start()
        servers[name] = server

    cycle_times: list[float] = []
    command_latencies: list[float] = []
    command_count = 0

    try:
        async with AsyncExitStack() as stack:
            clients: dict[str, DeviceClient] = {}
            for name, server in servers.items():
                client = DeviceClient(LOOPBACK, server.sockets_port)
                await stack.enter_async_context(client)
                clients[name] = client

            sequencer = Sequencer(plan, profiles, clients)
            for _ in range(iterations):
                started = time.perf_counter()
                report: StationReport = await sequencer.run()
                cycle_times.append(time.perf_counter() - started)
                for outcome in report.outcomes:
                    command_latencies.append(outcome.duration_s)
                    command_count += 1
    finally:
        for server in servers.values():
            await server.stop()

    total_wall = sum(cycle_times)
    return {
        "iterations": iterations,
        "commands_per_cycle": command_count // iterations if iterations else 0,
        "cycle_wall_clock_s": {
            "mean": statistics.fmean(cycle_times),
            "p50": _percentile(cycle_times, 50),
            "p95": _percentile(cycle_times, 95),
            "p99": _percentile(cycle_times, 99),
            "min": min(cycle_times),
            "max": max(cycle_times),
        },
        "command_latency_ms": {
            "p50": _percentile(command_latencies, 50) * 1000.0,
            "p95": _percentile(command_latencies, 95) * 1000.0,
            "p99": _percentile(command_latencies, 99) * 1000.0,
        },
        "throughput_commands_per_s": (command_count / total_wall if total_wall > 0 else 0.0),
    }


async def run_bench(iterations: int) -> dict[str, Any]:
    """Run the clean and fault-injected benchmark passes."""
    plan = load_test_plan(PLAN_PATH)
    clean = await _run_cycles(plan, _clean_profiles(), iterations)
    faulted = await _run_cycles(plan, _fault_profiles(), iterations)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "plan": plan.name,
        "clean": clean,
        "fault_injected": faulted,
    }


def _write_result(result: dict[str, Any]) -> Path:
    """Write ``result`` as JSON under bench/results and return the path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    return path


def _print_summary(result: dict[str, Any]) -> None:
    """Print a compact human-readable summary of a bench result."""
    for label in ("clean", "fault_injected"):
        section = result[label]
        cycle = section["cycle_wall_clock_s"]
        latency = section["command_latency_ms"]
        print(
            f"[{label}] {section['iterations']} cycles, "
            f"{section['commands_per_cycle']} commands/cycle"
        )
        print(
            f"  per-cycle wall-clock: mean {cycle['mean'] * 1000:.3f} ms, "
            f"p95 {cycle['p95'] * 1000:.3f} ms, p99 {cycle['p99'] * 1000:.3f} ms"
        )
        print(
            f"  command latency:      p50 {latency['p50']:.3f} ms, "
            f"p95 {latency['p95']:.3f} ms, p99 {latency['p99']:.3f} ms"
        )
        print(f"  throughput:           " f"{section['throughput_commands_per_s']:.0f} commands/s")


def _latest_baseline() -> dict[str, Any] | None:
    """Return the most recent stored bench result, if any."""
    if not RESULTS_DIR.exists():
        return None
    results = sorted(RESULTS_DIR.glob("*.json"))
    if not results:
        return None
    return json.loads(results[-1].read_text())


def _check_regression(current: dict[str, Any], drift: float) -> int:
    """Compare ``current`` to the stored baseline; return a process exit code."""
    baseline = _latest_baseline()
    if baseline is None:
        print("bench-regress: no baseline stored yet; recording current run")
        _write_result(current)
        return 0
    base_mean = baseline["clean"]["cycle_wall_clock_s"]["mean"]
    cur_mean = current["clean"]["cycle_wall_clock_s"]["mean"]
    limit = base_mean * (1.0 + drift)
    pct = (cur_mean / base_mean - 1.0) * 100.0 if base_mean else 0.0
    print(
        f"bench-regress: baseline {base_mean * 1000:.3f} ms, "
        f"current {cur_mean * 1000:.3f} ms ({pct:+.1f}%), "
        f"limit {limit * 1000:.3f} ms (+{drift * 100:.0f}%)"
    )
    if cur_mean > limit:
        print("bench-regress: FAIL, per-cycle wall-clock regressed past the limit")
        return 1
    print("bench-regress: PASS")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the cycle benchmark CLI."""
    parser = argparse.ArgumentParser(description="Test-cycle benchmark.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help="Number of full plan cycles per pass.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the stored baseline and fail on regression.",
    )
    parser.add_argument(
        "--drift",
        type=float,
        default=DEFAULT_DRIFT,
        help="Allowed per-cycle wall-clock regression fraction.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not persist the result JSON.",
    )
    args = parser.parse_args(argv)

    result = asyncio.run(run_bench(args.iterations))
    _print_summary(result)

    if args.check:
        return _check_regression(result, args.drift)
    if not args.no_write:
        path = _write_result(result)
        print(f"results written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
