"""Unit tests for the Modbus-style frame and CRC16."""

from __future__ import annotations

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.modbus.frame import (
    FIXED_FRAME_LEN,
    Frame,
    FrameError,
    FunctionCode,
    crc16,
)


def test_crc16_known_vector() -> None:
    # CRC16/Modbus of b"123456789" is 0x4B37.
    assert crc16(b"123456789") == 0x4B37


def test_crc16_empty_is_seed() -> None:
    assert crc16(b"") == 0xFFFF


def test_frame_round_trip() -> None:
    frame = Frame(1, FunctionCode.READ_HOLDING_REGISTERS, 0x0010, 4)
    decoded = Frame.decode(frame.encode())
    assert decoded == frame


def test_frame_encode_length_is_fixed() -> None:
    frame = Frame(1, FunctionCode.WRITE_SINGLE_REGISTER, 0, 1)
    assert len(frame.encode()) == FIXED_FRAME_LEN


def test_decode_rejects_wrong_length() -> None:
    with pytest.raises(FrameError, match="expected 8 bytes"):
        Frame.decode(b"\x00\x01\x02")


def test_decode_rejects_bad_crc() -> None:
    frame = Frame(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)
    corrupt = bytearray(frame.encode())
    corrupt[-1] ^= 0xFF
    with pytest.raises(FrameError, match="CRC mismatch"):
        Frame.decode(bytes(corrupt))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"unit_id": 256, "function_code": 3, "start_addr": 0, "quantity_or_value": 0},
        {"unit_id": 1, "function_code": -1, "start_addr": 0, "quantity_or_value": 0},
        {"unit_id": 1, "function_code": 3, "start_addr": 0x10000, "quantity_or_value": 0},
        {"unit_id": 1, "function_code": 3, "start_addr": 0, "quantity_or_value": 0x10000},
    ],
)
def test_frame_rejects_out_of_range_fields(kwargs: dict[str, int]) -> None:
    with pytest.raises(FrameError):
        Frame(**kwargs)


@given(
    unit_id=st.integers(0, 0xFF),
    function_code=st.integers(0, 0xFF),
    start_addr=st.integers(0, 0xFFFF),
    quantity=st.integers(0, 0xFFFF),
)
def test_property_round_trip(
    unit_id: int, function_code: int, start_addr: int, quantity: int
) -> None:
    frame = Frame(unit_id, function_code, start_addr, quantity)
    assert Frame.decode(frame.encode()) == frame


@given(
    unit_id=st.integers(0, 0xFF),
    function_code=st.integers(0, 0xFF),
    start_addr=st.integers(0, 0xFFFF),
    quantity=st.integers(0, 0xFFFF),
    bit=st.integers(0, FIXED_FRAME_LEN * 8 - 1),
)
def test_property_single_bit_flip_caught(
    unit_id: int,
    function_code: int,
    start_addr: int,
    quantity: int,
    bit: int,
) -> None:
    encoded = bytearray(Frame(unit_id, function_code, start_addr, quantity).encode())
    encoded[bit // 8] ^= 1 << (bit % 8)
    # A single-bit flip anywhere either fails the CRC or, if it lands such
    # that CRC still matches a different header, decodes to a different frame.
    try:
        decoded = Frame.decode(bytes(encoded))
    except FrameError:
        return
    assert decoded != Frame(unit_id, function_code, start_addr, quantity)


def test_header_bytes_layout() -> None:
    frame = Frame(0x11, 0x03, 0x1234, 0x0006)
    assert frame.header_bytes() == struct.pack(">BBHH", 0x11, 0x03, 0x1234, 6)
