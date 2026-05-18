"""Encode and decode the four supported function codes.

Requests are always the fixed 8-byte :class:`Frame`. Responses come in two
shapes:

* Read responses (0x03, 0x04) carry register data, so they use a variable
  length form: ``[1B unit_id][1B fc][1B byte_count][N*2B registers][2B crc16]``.
* Write responses (0x06, 0x10) echo the request and use the fixed 8-byte form.

This split keeps write traffic trivially framed while still letting reads
return arbitrary register counts.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from mfg_test_controller.modbus.frame import (
    FRAME_HEADER_LEN,
    Frame,
    FrameError,
    FunctionCode,
    crc16,
)

MAX_REGISTERS = 125
"""Upper bound on registers per read, matching the classic Modbus limit."""


def encode_read_holding(unit_id: int, start_addr: int, quantity: int) -> bytes:
    """Encode a Read Holding Registers (0x03) request."""
    return Frame(unit_id, FunctionCode.READ_HOLDING_REGISTERS, start_addr, quantity).encode()


def encode_read_input(unit_id: int, start_addr: int, quantity: int) -> bytes:
    """Encode a Read Input Registers (0x04) request."""
    return Frame(unit_id, FunctionCode.READ_INPUT_REGISTERS, start_addr, quantity).encode()


def encode_write_single(unit_id: int, addr: int, value: int) -> bytes:
    """Encode a Write Single Register (0x06) request."""
    return Frame(unit_id, FunctionCode.WRITE_SINGLE_REGISTER, addr, value).encode()


def encode_write_multiple(unit_id: int, start_addr: int, quantity: int) -> bytes:
    """Encode a Write Multiple Registers (0x10) request.

    The register payload is carried separately by :func:`encode_register_block`
    in the device transport; the request frame itself only declares the count.
    """
    return Frame(unit_id, FunctionCode.WRITE_MULTIPLE_REGISTERS, start_addr, quantity).encode()


def decode_request(buffer: bytes) -> Frame:
    """Decode an 8-byte request buffer into a :class:`Frame`."""
    return Frame.decode(buffer)


@dataclass(frozen=True)
class ReadResponse:
    """A decoded variable-length read response."""

    unit_id: int
    function_code: int
    registers: list[int]


def encode_read_response(unit_id: int, function_code: int, registers: list[int]) -> bytes:
    """Encode a read response carrying ``registers``."""
    if len(registers) > MAX_REGISTERS:
        raise FrameError(f"too many registers: {len(registers)}")
    for value in registers:
        if not 0 <= value <= 0xFFFF:
            raise FrameError(f"register value out of range: {value}")
    byte_count = len(registers) * 2
    body = struct.pack(">BBB", unit_id, function_code, byte_count)
    body += b"".join(struct.pack(">H", value) for value in registers)
    crc = crc16(body)
    return body + struct.pack("<H", crc)


def decode_read_response(buffer: bytes) -> ReadResponse:
    """Decode a variable-length read response, validating its CRC."""
    if len(buffer) < 5:
        raise FrameError(f"read response too short: {len(buffer)} bytes")
    unit_id, function_code, byte_count = struct.unpack(">BBB", buffer[:3])
    expected_len = 3 + byte_count + 2
    if len(buffer) != expected_len:
        raise FrameError(
            f"read response length mismatch: declared {expected_len}, " f"got {len(buffer)}"
        )
    body = buffer[:-2]
    (received_crc,) = struct.unpack("<H", buffer[-2:])
    if crc16(body) != received_crc:
        raise FrameError("CRC mismatch in read response")
    registers = [struct.unpack(">H", buffer[3 + i : 5 + i])[0] for i in range(0, byte_count, 2)]
    return ReadResponse(unit_id, function_code, registers)


def decode_response(buffer: bytes) -> Frame | ReadResponse:
    """Decode a response buffer, dispatching on function code.

    Read responses (0x03, 0x04) are returned as :class:`ReadResponse`; write
    responses are returned as :class:`Frame`.
    """
    if len(buffer) < 2:
        raise FrameError("response buffer too short")
    function_code = buffer[1]
    if function_code in (
        FunctionCode.READ_HOLDING_REGISTERS,
        FunctionCode.READ_INPUT_REGISTERS,
    ):
        return decode_read_response(buffer)
    return Frame.decode(buffer)


def encode_register_block(registers: list[int]) -> bytes:
    """Encode a bare register payload for Write Multiple Registers traffic."""
    return b"".join(struct.pack(">H", value & 0xFFFF) for value in registers)


def decode_register_block(buffer: bytes) -> list[int]:
    """Decode a bare register payload back into integers."""
    if len(buffer) % 2 != 0:
        raise FrameError("register block must be an even number of bytes")
    return [struct.unpack(">H", buffer[i : i + 2])[0] for i in range(0, len(buffer), 2)]


__all__ = [
    "MAX_REGISTERS",
    "FRAME_HEADER_LEN",
    "ReadResponse",
    "encode_read_holding",
    "encode_read_input",
    "encode_write_single",
    "encode_write_multiple",
    "decode_request",
    "encode_read_response",
    "decode_read_response",
    "decode_response",
    "encode_register_block",
    "decode_register_block",
]
