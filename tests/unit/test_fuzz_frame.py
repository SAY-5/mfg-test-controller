"""Fuzz tests for the frame parser and the device frame handler.

Random byte streams are fed into :meth:`Frame.decode`, the codec decoders,
and :meth:`SimulatedDevice.handle_frame`. None of them may crash with an
unexpected exception type: a malformed buffer must surface either a
structured :class:`FrameError` or, for the device, an exception frame.
"""

from __future__ import annotations

import contextlib

from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.device.profiles import builtin_profile
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.codec import (
    decode_read_response,
    decode_register_block,
    decode_response,
)
from mfg_test_controller.modbus.exceptions import is_exception_frame
from mfg_test_controller.modbus.frame import FIXED_FRAME_LEN, Frame, FrameError

ARBITRARY = st.binary(min_size=0, max_size=128)
FIXED_LEN = st.binary(min_size=FIXED_FRAME_LEN, max_size=FIXED_FRAME_LEN)


@given(buffer=ARBITRARY)
def test_frame_decode_never_crashes(buffer: bytes) -> None:
    """Frame.decode either parses or raises FrameError, never anything else."""
    with contextlib.suppress(FrameError):
        Frame.decode(buffer)


@given(buffer=ARBITRARY)
def test_decode_read_response_never_crashes(buffer: bytes) -> None:
    """decode_read_response only ever raises a structured FrameError."""
    with contextlib.suppress(FrameError):
        decode_read_response(buffer)


@given(buffer=ARBITRARY)
def test_decode_response_never_crashes(buffer: bytes) -> None:
    """decode_response only ever raises a structured FrameError."""
    with contextlib.suppress(FrameError):
        decode_response(buffer)


@given(buffer=ARBITRARY)
def test_decode_register_block_never_crashes(buffer: bytes) -> None:
    """decode_register_block only ever raises a structured FrameError."""
    with contextlib.suppress(FrameError):
        decode_register_block(buffer)


@given(request=ARBITRARY, payload=ARBITRARY)
def test_device_handle_frame_never_crashes(request: bytes, payload: bytes) -> None:
    """Random bytes into a device produce a structured reply or a clean drop."""
    device = SimulatedDevice(builtin_profile("dmm"))
    response = device.handle_frame(request, payload)
    if response is None:
        return
    assert isinstance(response, bytes)
    # Any reply to a malformed request is either a valid frame or an
    # exception frame; it must round-trip through one of those decoders.
    if is_exception_frame(response):
        assert len(response) == FIXED_FRAME_LEN
        return
    try:
        Frame.decode(response)
    except FrameError:
        decode_read_response(response)


@given(request=FIXED_LEN)
def test_device_handle_fixed_length_garbage(request: bytes) -> None:
    """A fixed-length garbage frame yields a structured reply, never a crash."""
    device = SimulatedDevice(builtin_profile("power_supply"))
    response = device.handle_frame(request, b"")
    assert response is None or isinstance(response, bytes)
