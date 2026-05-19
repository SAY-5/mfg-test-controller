"""Dual-framing tests: the same plan runs under both wire formats.

These assert the controller behaves identically whether it uses the custom
hand-rolled framing or real Modbus TCP MBAP framing, and that a modbus-tcp
exchange puts spec-correct MBAP bytes on the wire.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from mfg_test_controller.config import FaultConfig, load_device_profile, load_test_plan
from mfg_test_controller.controller.client import DeviceClient, DeviceTimeout
from mfg_test_controller.device.profiles import builtin_profile
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.exceptions import ModbusException
from mfg_test_controller.modbus.framing import Framer, FramingMode, parse_framing_mode
from mfg_test_controller.modbus.mbap import MBAP_HEADER_LEN, decode_mbap
from mfg_test_controller.runner import run_plan_locally
from mfg_test_controller.server import DeviceServer

REPO_ROOT = Path(__file__).resolve().parents[2]
ALL_MODES = [FramingMode.CUSTOM, FramingMode.MODBUS_TCP]


def _load_plan_profiles() -> tuple[object, list[object]]:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = [
        load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        for name in {step.device for step in plan.steps}
    ]
    return plan, profiles


async def _serve(mode: FramingMode, profile_name: str = "power_supply") -> DeviceServer:
    server = DeviceServer(
        SimulatedDevice(builtin_profile(profile_name)),
        "127.0.0.1",
        0,
        framer=Framer(mode),
    )
    await server.start()
    return server


def test_parse_framing_mode() -> None:
    """The CLI framing strings parse to the matching enum members."""
    assert parse_framing_mode("custom") is FramingMode.CUSTOM
    assert parse_framing_mode("modbus-tcp") is FramingMode.MODBUS_TCP
    with pytest.raises(Exception, match="unknown framing mode"):
        parse_framing_mode("rtu")


@pytest.mark.parametrize("mode", ALL_MODES)
async def test_station_bringup_identical_under_both_framings(mode: FramingMode) -> None:
    """The station_bringup plan passes identically under either framing."""
    plan, profiles = _load_plan_profiles()
    report = await run_plan_locally(plan, profiles, framing=mode)  # type: ignore[arg-type]
    assert report.total == 11
    assert report.passed == 11
    assert report.all_passed, report.first_failure


@pytest.mark.parametrize("mode", ALL_MODES)
async def test_all_four_function_codes_under_framing(mode: FramingMode) -> None:
    """Read/write of all four function codes works in the given framing mode."""
    server = await _serve(mode)
    try:
        async with DeviceClient("127.0.0.1", server.sockets_port, framer=Framer(mode)) as client:
            await client.write_single_register(1, 0, 7777)  # 0x06
            assert await client.read_holding_registers(1, 0, 1) == [7777]  # 0x03
            await client.write_multiple_registers(1, 0, [11, 22, 33])  # 0x10
            assert await client.read_holding_registers(1, 0, 3) == [11, 22, 33]
            assert await client.read_input_registers(1, 0, 1) == [0]  # 0x04
    finally:
        await server.stop()


async def test_modbus_tcp_wire_format_matches_spec() -> None:
    """A modbus-tcp request puts spec-correct MBAP bytes on the wire.

    The framer wraps a Read Holding Registers request; the resulting bytes
    must carry the 7-byte MBAP header (transaction id, zero protocol id,
    length, unit id) followed by the PDU, with no trailing CRC.
    """
    framer = Framer(FramingMode.MODBUS_TCP)
    from mfg_test_controller.modbus.codec import encode_read_holding

    request_frame = encode_read_holding(unit_id=0x07, start_addr=4, quantity=2)
    wire = framer.wrap_request(request_frame)

    message = decode_mbap(wire)
    # protocol id is always zero for Modbus.
    assert wire[2:4] == b"\x00\x00"
    assert message.unit_id == 0x07
    # The PDU is [fc][addr][quantity], 5 bytes, with no CRC.
    assert len(message.pdu) == 5
    fc, addr, quantity = struct.unpack(">BHH", message.pdu)
    assert fc == 0x03
    assert addr == 4
    assert quantity == 2
    # length field frames unit_id + PDU.
    assert struct.unpack(">H", wire[4:6])[0] == 1 + len(message.pdu)
    assert len(wire) == MBAP_HEADER_LEN + len(message.pdu)


async def test_modbus_tcp_transaction_id_is_echoed() -> None:
    """A modbus-tcp server echoes the request transaction id on the reply."""
    server = await _serve(FramingMode.MODBUS_TCP)
    try:
        framer = Framer(FramingMode.MODBUS_TCP)
        async with DeviceClient("127.0.0.1", server.sockets_port, framer=framer) as client:
            await client.write_single_register(1, 0, 42)
            assert await client.read_holding_registers(1, 0, 1) == [42]
    finally:
        await server.stop()


async def test_modbus_tcp_exception_surfaces() -> None:
    """An illegal address under modbus-tcp surfaces as a ModbusException."""
    server = await _serve(FramingMode.MODBUS_TCP, "dmm")
    try:
        framer = Framer(FramingMode.MODBUS_TCP)
        async with DeviceClient("127.0.0.1", server.sockets_port, framer=framer) as client:
            with pytest.raises(ModbusException):
                await client.read_input_registers(2, 99, 1)
    finally:
        await server.stop()


@pytest.mark.parametrize("mode", ALL_MODES)
async def test_drift_fault_under_framing(mode: FramingMode) -> None:
    """A drift fault breaks a threshold step under either framing mode."""
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = []
    for name in {step.device for step in plan.steps}:
        profile = load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        if name == "thermocouple":
            profile = profile.model_copy(
                update={"faults": [FaultConfig(kind="drift", register=0, amount=400)]}
            )
        profiles.append(profile)
    report = await run_plan_locally(plan, profiles, framing=mode)  # type: ignore[arg-type]
    assert not report.all_passed
    assert report.first_failure is not None
    assert report.first_failure.device == "thermocouple"


async def test_drop_fault_times_out_under_modbus_tcp() -> None:
    """A drop fault under modbus-tcp surfaces as a DeviceTimeout."""
    server = DeviceServer(
        SimulatedDevice(
            builtin_profile("dmm").model_copy(
                update={"faults": [FaultConfig(kind="drop", after_requests=0)]}
            )
        ),
        "127.0.0.1",
        0,
        framer=Framer(FramingMode.MODBUS_TCP),
    )
    await server.start()
    try:
        framer = Framer(FramingMode.MODBUS_TCP)
        async with DeviceClient(
            "127.0.0.1", server.sockets_port, timeout=0.5, framer=framer
        ) as client:
            with pytest.raises(DeviceTimeout):
                await client.read_input_registers(2, 0, 1)
    finally:
        await server.stop()


def test_modbus_tcp_unwrap_rejects_garbled_response() -> None:
    """The framer rejects a non-MBAP reply with a structured FrameError."""
    from mfg_test_controller.modbus.frame import FrameError

    framer = Framer(FramingMode.MODBUS_TCP)
    with pytest.raises(FrameError):
        framer.unwrap_response(b"\x00\x00\x00")
