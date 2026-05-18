"""Loopback TCP integration tests, gated by RUN_INTEGRATION=1.

These tests start real :class:`DeviceServer` instances on ephemeral loopback
ports and drive them with the async :class:`DeviceClient` and the sequencer.
No real hardware is involved; everything runs over 127.0.0.1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mfg_test_controller.config import (
    FaultConfig,
    load_device_profile,
    load_test_plan,
)
from mfg_test_controller.controller.client import (
    DeviceClient,
    DeviceError,
    DeviceTimeout,
)
from mfg_test_controller.device.profiles import builtin_profile
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.runner import run_plan_locally
from mfg_test_controller.server import DeviceServer

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="integration tests gated by RUN_INTEGRATION=1",
)


async def _serve(profile_name: str, faults: list[FaultConfig] | None = None) -> DeviceServer:
    profile = builtin_profile(profile_name)
    if faults is not None:
        profile = profile.model_copy(update={"faults": faults})
    server = DeviceServer(SimulatedDevice(profile), "127.0.0.1", 0)
    await server.start()
    return server


async def test_read_write_across_all_four_devices() -> None:
    servers = {
        name: await _serve(name) for name in ("power_supply", "dmm", "actuator", "thermocouple")
    }
    try:
        ps = servers["power_supply"]
        async with DeviceClient("127.0.0.1", ps.sockets_port) as client:
            await client.write_single_register(1, 0, 1234)
            assert await client.read_holding_registers(1, 0, 1) == [1234]

        dmm = servers["dmm"]
        async with DeviceClient("127.0.0.1", dmm.sockets_port) as client:
            assert await client.read_input_registers(2, 0, 1) == [4980]

        act = servers["actuator"]
        async with DeviceClient("127.0.0.1", act.sockets_port) as client:
            await client.write_multiple_registers(3, 0, [800, 1])
            assert await client.read_holding_registers(3, 0, 2) == [800, 1]

        tc = servers["thermocouple"]
        async with DeviceClient("127.0.0.1", tc.sockets_port) as client:
            assert len(await client.read_input_registers(4, 0, 3)) == 3
    finally:
        for server in servers.values():
            await server.stop()


async def test_station_bringup_plan_all_pass() -> None:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = [
        load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        for name in {step.device for step in plan.steps}
    ]
    report = await run_plan_locally(plan, profiles)
    assert report.total == 11
    assert report.all_passed, report.first_failure


async def test_crc_corrupt_fault_surfaces_as_error() -> None:
    # A corrupted read response fails CRC validation on the controller side
    # and is surfaced as a DeviceError rather than a clean exception frame.
    server = await _serve("dmm", [FaultConfig(kind="crc_corrupt")])
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port) as client:
            with pytest.raises(DeviceError, match="CRC"):
                await client.read_input_registers(2, 0, 1)
    finally:
        await server.stop()


async def test_drop_fault_surfaces_as_timeout() -> None:
    server = await _serve("dmm", [FaultConfig(kind="drop", after_requests=0)])
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port, timeout=0.5) as client:
            with pytest.raises(DeviceTimeout):
                await client.read_input_registers(2, 0, 1)
    finally:
        await server.stop()


async def test_drift_fault_fails_a_threshold_step() -> None:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = []
    for name in {step.device for step in plan.steps}:
        profile = load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        if name == "thermocouple":
            profile = profile.model_copy(
                update={"faults": [FaultConfig(kind="drift", register=0, amount=400)]}
            )
        profiles.append(profile)
    report = await run_plan_locally(plan, profiles)
    assert not report.all_passed
    failure = report.first_failure
    assert failure is not None
    assert failure.device == "thermocouple"
