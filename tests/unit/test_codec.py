"""Unit tests for the codec covering all four function codes."""

from __future__ import annotations

import pytest

from mfg_test_controller.modbus.codec import (
    ReadResponse,
    decode_read_response,
    decode_register_block,
    decode_request,
    decode_response,
    encode_read_holding,
    encode_read_input,
    encode_read_response,
    encode_register_block,
    encode_write_multiple,
    encode_write_single,
)
from mfg_test_controller.modbus.frame import Frame, FrameError, FunctionCode


def test_read_holding_request_round_trip() -> None:
    request = encode_read_holding(unit_id=1, start_addr=8, quantity=3)
    frame = decode_request(request)
    assert frame.function_code == FunctionCode.READ_HOLDING_REGISTERS
    assert frame.start_addr == 8
    assert frame.quantity_or_value == 3


def test_read_input_request_round_trip() -> None:
    request = encode_read_input(unit_id=2, start_addr=0, quantity=1)
    frame = decode_request(request)
    assert frame.function_code == FunctionCode.READ_INPUT_REGISTERS


def test_write_single_request_round_trip() -> None:
    request = encode_write_single(unit_id=3, addr=4, value=999)
    frame = decode_request(request)
    assert frame.function_code == FunctionCode.WRITE_SINGLE_REGISTER
    assert frame.quantity_or_value == 999


def test_write_multiple_request_round_trip() -> None:
    request = encode_write_multiple(unit_id=4, start_addr=10, quantity=2)
    frame = decode_request(request)
    assert frame.function_code == FunctionCode.WRITE_MULTIPLE_REGISTERS
    assert frame.quantity_or_value == 2


def test_read_response_round_trip() -> None:
    encoded = encode_read_response(1, FunctionCode.READ_HOLDING_REGISTERS, [10, 20, 30])
    decoded = decode_read_response(encoded)
    assert decoded == ReadResponse(1, FunctionCode.READ_HOLDING_REGISTERS, [10, 20, 30])


def test_read_response_empty() -> None:
    encoded = encode_read_response(1, FunctionCode.READ_INPUT_REGISTERS, [])
    assert decode_read_response(encoded).registers == []


def test_read_response_rejects_bad_crc() -> None:
    encoded = bytearray(encode_read_response(1, FunctionCode.READ_HOLDING_REGISTERS, [5]))
    encoded[-1] ^= 0xFF
    with pytest.raises(FrameError, match="CRC mismatch"):
        decode_read_response(bytes(encoded))


def test_read_response_rejects_length_mismatch() -> None:
    encoded = encode_read_response(1, FunctionCode.READ_HOLDING_REGISTERS, [5])
    with pytest.raises(FrameError, match="length mismatch"):
        decode_read_response(encoded + b"\x00")


def test_decode_response_dispatches_read() -> None:
    encoded = encode_read_response(1, FunctionCode.READ_INPUT_REGISTERS, [7])
    result = decode_response(encoded)
    assert isinstance(result, ReadResponse)


def test_decode_response_dispatches_write() -> None:
    echo = Frame(1, FunctionCode.WRITE_SINGLE_REGISTER, 0, 1).encode()
    result = decode_response(echo)
    assert isinstance(result, Frame)


def test_register_block_round_trip() -> None:
    block = encode_register_block([1, 65535, 0])
    assert decode_register_block(block) == [1, 65535, 0]


def test_register_block_rejects_odd_length() -> None:
    with pytest.raises(FrameError, match="even number"):
        decode_register_block(b"\x00\x01\x02")


def test_encode_read_response_rejects_out_of_range_register() -> None:
    with pytest.raises(FrameError, match="out of range"):
        encode_read_response(1, FunctionCode.READ_HOLDING_REGISTERS, [70000])
