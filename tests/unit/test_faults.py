"""Unit tests for fault injection: drift, stuck, delay, crc-corrupt, drop."""

from __future__ import annotations

import asyncio
import time

from mfg_test_controller.config import DeviceProfile, FaultConfig, RegisterSpec
from mfg_test_controller.device.faults import FaultEngine
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.codec import (
    decode_read_response,
    encode_read_input,
    encode_write_single,
)
from mfg_test_controller.modbus.exceptions import is_exception_frame
from mfg_test_controller.modbus.frame import Frame


def _profile(faults: list[FaultConfig]) -> DeviceProfile:
    return DeviceProfile(
        name="dmm",
        unit_id=2,
        kind="dmm",
        registers=[
            RegisterSpec(name="meas", address=0, kind="input", value=1000),
            RegisterSpec(name="setpoint", address=0, kind="holding", value=10),
        ],
        faults=faults,
    )


def test_drift_walks_register_off_over_reads() -> None:
    device = SimulatedDevice(_profile([FaultConfig(kind="drift", register=0, amount=5)]))
    first = decode_read_response(
        device.handle_frame(encode_read_input(2, 0, 1))  # type: ignore[arg-type]
    ).registers[0]
    second = decode_read_response(
        device.handle_frame(encode_read_input(2, 0, 1))  # type: ignore[arg-type]
    ).registers[0]
    assert second > first
    assert second - first == 5


def test_stuck_register_ignores_writes() -> None:
    device = SimulatedDevice(_profile([FaultConfig(kind="stuck", register=0)]))
    device.handle_frame(encode_write_single(2, 0, 555))
    assert device.registers.holding[0] == 10


def test_delay_sleeps_before_response() -> None:
    engine = FaultEngine([FaultConfig(kind="delay", delay_seconds=0.05)])
    started = time.perf_counter()
    asyncio.run(engine.apply_delay())
    assert time.perf_counter() - started >= 0.04


def test_crc_corrupt_mutates_outgoing_frame() -> None:
    engine = FaultEngine([FaultConfig(kind="crc_corrupt")])
    frame = Frame(1, 3, 0, 1).encode()
    corrupted = engine.corrupt_crc(frame)
    assert corrupted != frame
    assert corrupted[:-1] == frame[:-1]


def test_drop_suppresses_response_after_threshold() -> None:
    device = SimulatedDevice(_profile([FaultConfig(kind="drop", after_requests=1)]))
    first = device.handle_frame(encode_read_input(2, 0, 1))
    assert first is not None
    second = device.handle_frame(encode_read_input(2, 0, 1))
    assert second is None


def test_no_faults_is_inert() -> None:
    device = SimulatedDevice(_profile([]))
    assert not device.faults.has_faults
    response = device.handle_frame(encode_read_input(2, 0, 1))
    assert response is not None and not is_exception_frame(response)


def test_drift_only_targets_named_register() -> None:
    engine = FaultEngine([FaultConfig(kind="drift", register=0, amount=5)])
    engine.note_request()
    assert engine.apply_read_drift(1, 100) == 100
    assert engine.apply_read_drift(0, 100) == 105
