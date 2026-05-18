"""Unit tests for the sequencer, runner, client, and server stack.

These run hermetically over an ephemeral loopback socket: no real hardware
and no external services. Unlike the integration suite they are not gated by
``RUN_INTEGRATION`` because they finish in milliseconds and exercise the
controller logic directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mfg_test_controller.config import FaultConfig, load_device_profile, load_test_plan
from mfg_test_controller.controller.client import (
    DeviceClient,
    DeviceError,
    DeviceTimeout,
)
from mfg_test_controller.controller.sequencer import Sequencer, StationReport, StepOutcome
from mfg_test_controller.device.profiles import builtin_profile
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.exceptions import ModbusException
from mfg_test_controller.runner import run_plan_locally
from mfg_test_controller.server import DeviceServer

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _serve(profile_name: str, faults: list[FaultConfig] | None = None) -> DeviceServer:
    """Start a loopback device server, optionally with injected faults."""
    profile = builtin_profile(profile_name)
    if faults is not None:
        profile = profile.model_copy(update={"faults": faults})
    server = DeviceServer(SimulatedDevice(profile), "127.0.0.1", 0)
    await server.start()
    return server


def _load_plan_profiles() -> tuple[object, list[object]]:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = [
        load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        for name in {step.device for step in plan.steps}
    ]
    return plan, profiles


async def test_client_round_trips_all_function_codes() -> None:
    """The client drives 0x03/0x04/0x06/0x10 against simulated devices."""
    server = await _serve("power_supply")
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port) as client:
            await client.write_single_register(1, 0, 4321)
            assert await client.read_holding_registers(1, 0, 1) == [4321]
            await client.write_multiple_registers(1, 0, [10, 20, 30])
            assert await client.read_holding_registers(1, 0, 3) == [10, 20, 30]
            assert await client.read_input_registers(1, 0, 1) == [0]
    finally:
        await server.stop()


async def test_client_not_connected_raises() -> None:
    """Issuing a request before connect raises a DeviceError."""
    client = DeviceClient("127.0.0.1", 1)
    with pytest.raises(DeviceError, match="not connected"):
        await client.read_holding_registers(1, 0, 1)


async def test_station_bringup_plan_passes() -> None:
    """The canonical bring-up plan passes against the disk profiles."""
    plan, profiles = _load_plan_profiles()
    report = await run_plan_locally(plan, profiles)  # type: ignore[arg-type]
    assert isinstance(report, StationReport)
    assert report.total == 11
    assert report.all_passed, report.first_failure


async def test_only_failed_filter_runs_subset() -> None:
    """run_plan_locally honours the only_failed step filter."""
    plan, profiles = _load_plan_profiles()
    report = await run_plan_locally(
        plan, profiles, only_failed=["check_dmm_dc_voltage"]  # type: ignore[arg-type]
    )
    assert report.total == 1
    assert report.outcomes[0].name == "check_dmm_dc_voltage"


async def test_drift_fault_fails_a_threshold_step() -> None:
    """A drift fault on the thermocouple breaks a threshold step."""
    plan, _profiles = _load_plan_profiles()
    profiles = []
    for name in {step.device for step in plan.steps}:  # type: ignore[attr-defined]
        profile = load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        if name == "thermocouple":
            profile = profile.model_copy(
                update={"faults": [FaultConfig(kind="drift", register=0, amount=400)]}
            )
        profiles.append(profile)
    report = await run_plan_locally(plan, profiles)  # type: ignore[arg-type]
    assert not report.all_passed
    failure = report.first_failure
    assert failure is not None
    assert failure.device == "thermocouple"


async def test_crc_corrupt_fault_surfaces_as_device_error() -> None:
    """A corrupted CRC on a read response surfaces as a DeviceError."""
    server = await _serve("dmm", [FaultConfig(kind="crc_corrupt")])
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port) as client:
            with pytest.raises(DeviceError, match="CRC"):
                await client.read_input_registers(2, 0, 1)
    finally:
        await server.stop()


async def test_drop_fault_surfaces_as_timeout() -> None:
    """A drop fault leaves the client waiting until it times out."""
    server = await _serve("dmm", [FaultConfig(kind="drop", after_requests=0)])
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port, timeout=0.5) as client:
            with pytest.raises(DeviceTimeout):
                await client.read_input_registers(2, 0, 1)
    finally:
        await server.stop()


async def test_sequencer_reports_unknown_device() -> None:
    """A step naming an unconfigured device fails with a clear detail."""
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    sequencer = Sequencer(plan, {}, {})
    report = await sequencer.run()
    assert report.failed == report.total
    assert "no device configured" in report.outcomes[0].detail


async def test_sequencer_modbus_exception_is_caught() -> None:
    """A device exception frame is surfaced as a ModbusException, not a crash."""
    server = await _serve("dmm")
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port) as client:
            with pytest.raises(ModbusException):
                # Address 99 is not mapped on the dmm: illegal data address.
                await client.read_input_registers(2, 99, 1)
    finally:
        await server.stop()


def test_station_report_aggregates() -> None:
    """StationReport pass/fail accounting and first_failure are correct."""
    report = StationReport(plan_name="p")
    report.outcomes = [
        StepOutcome("a", "d", "read", "r", True, 1.0, "ok", 0.01),
        StepOutcome("b", "d", "read", "r", False, 2.0, "bad", 0.02),
    ]
    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    assert not report.all_passed
    assert report.first_failure is not None
    assert report.first_failure.name == "b"
