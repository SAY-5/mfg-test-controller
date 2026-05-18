"""Modbus-style frame primitives: framing and CRC16.

Wire layout (fixed 10 bytes for the request/short-response forms used here):

    [1B unit_id][1B function_code][2B start_addr][2B quantity_or_value][2B crc16]

The CRC16 uses the Modbus polynomial 0xA001 and is computed over every byte
preceding it. The CRC is transmitted low byte first, matching Modbus RTU.

This is a hand-rolled framing layer, not a real Modbus implementation. The
fixed 10-byte form keeps the wire format trivially testable; variable-length
register payloads are layered on top by the codec module.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

FRAME_HEADER_LEN = 6
"""unit_id + function_code + start_addr + quantity_or_value, before the CRC."""

CRC_LEN = 2

FIXED_FRAME_LEN = FRAME_HEADER_LEN + CRC_LEN


class FunctionCode(IntEnum):
    """Supported Modbus-style function codes."""

    READ_HOLDING_REGISTERS = 0x03
    READ_INPUT_REGISTERS = 0x04
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_REGISTERS = 0x10

    EXCEPTION_MASK = 0x80


class FrameError(ValueError):
    """Raised when a buffer cannot be parsed as a valid frame."""


def crc16(data: bytes) -> int:
    """Compute the Modbus CRC16 (polynomial 0xA001) over ``data``.

    Returns a 16-bit integer. The seed is 0xFFFF.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass(frozen=True)
class Frame:
    """A fixed-length 8-byte command/short-response frame.

    ``payload`` carries the two-byte ``start_addr`` and ``quantity_or_value``
    fields. The CRC is computed on demand and validated on decode.
    """

    unit_id: int
    function_code: int
    start_addr: int
    quantity_or_value: int

    def __post_init__(self) -> None:
        if not 0 <= self.unit_id <= 0xFF:
            raise FrameError(f"unit_id out of range: {self.unit_id}")
        if not 0 <= self.function_code <= 0xFF:
            raise FrameError(f"function_code out of range: {self.function_code}")
        if not 0 <= self.start_addr <= 0xFFFF:
            raise FrameError(f"start_addr out of range: {self.start_addr}")
        if not 0 <= self.quantity_or_value <= 0xFFFF:
            raise FrameError(f"quantity_or_value out of range: {self.quantity_or_value}")

    def header_bytes(self) -> bytes:
        """Return the 6-byte header preceding the CRC."""
        return struct.pack(
            ">BBHH",
            self.unit_id,
            self.function_code,
            self.start_addr,
            self.quantity_or_value,
        )

    def encode(self) -> bytes:
        """Serialise the frame including its trailing CRC16 (low byte first)."""
        header = self.header_bytes()
        crc = crc16(header)
        return header + struct.pack("<H", crc)

    @classmethod
    def decode(cls, buffer: bytes) -> Frame:
        """Parse ``buffer`` into a :class:`Frame`, validating length and CRC."""
        if len(buffer) != FIXED_FRAME_LEN:
            raise FrameError(f"expected {FIXED_FRAME_LEN} bytes, got {len(buffer)}")
        header = buffer[:FRAME_HEADER_LEN]
        (received_crc,) = struct.unpack("<H", buffer[FRAME_HEADER_LEN:])
        expected_crc = crc16(header)
        if received_crc != expected_crc:
            raise FrameError(
                f"CRC mismatch: frame carries {received_crc:#06x}, " f"computed {expected_crc:#06x}"
            )
        unit_id, function_code, start_addr, quantity = struct.unpack(">BBHH", header)
        return cls(
            unit_id=unit_id,
            function_code=function_code,
            start_addr=start_addr,
            quantity_or_value=quantity,
        )
