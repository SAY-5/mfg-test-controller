"""Unit tests for Modbus-style exception frames."""

from __future__ import annotations

from mfg_test_controller.modbus.exceptions import (
    ExceptionCode,
    decode_exception,
    encode_exception,
    is_exception_frame,
)
from mfg_test_controller.modbus.frame import Frame, FunctionCode


def test_exception_frame_round_trip() -> None:
    encoded = encode_exception(
        1, FunctionCode.READ_HOLDING_REGISTERS, ExceptionCode.ILLEGAL_DATA_ADDRESS
    )
    exc = decode_exception(encoded)
    assert exc.code == ExceptionCode.ILLEGAL_DATA_ADDRESS
    assert exc.function_code == FunctionCode.READ_HOLDING_REGISTERS


def test_exception_frame_sets_high_bit() -> None:
    encoded = encode_exception(1, 0x03, ExceptionCode.DEVICE_FAILURE)
    assert encoded[1] == 0x83
    assert is_exception_frame(encoded)


def test_normal_frame_is_not_exception() -> None:
    normal = Frame(1, FunctionCode.WRITE_SINGLE_REGISTER, 0, 1).encode()
    assert not is_exception_frame(normal)


def test_corrupt_exception_frame_reports_crc_error() -> None:
    encoded = bytearray(encode_exception(1, 0x03, ExceptionCode.ILLEGAL_FUNCTION))
    encoded[-1] ^= 0xFF
    exc = decode_exception(bytes(encoded))
    assert exc.code == ExceptionCode.CRC_ERROR
