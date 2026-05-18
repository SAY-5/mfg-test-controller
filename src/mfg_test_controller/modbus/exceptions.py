"""Modbus-style exception frames.

When a device cannot service a request it replies with an exception frame.
The function code is OR-ed with 0x80 and a single exception code byte follows.
The exception frame here keeps the fixed-length form for testability:

    [1B unit_id][1B function_code|0x80][1B exception_code][3B padding][2B crc16]

The padding bytes are zero. Keeping the length fixed at 8 bytes means the
transport never has to frame variable-length buffers.
"""

from __future__ import annotations

import struct
from enum import IntEnum

from mfg_test_controller.modbus.frame import FIXED_FRAME_LEN, FunctionCode, crc16


class ExceptionCode(IntEnum):
    """Exception codes raised by simulated devices."""

    ILLEGAL_FUNCTION = 0x01
    ILLEGAL_DATA_ADDRESS = 0x02
    ILLEGAL_DATA_VALUE = 0x03
    DEVICE_FAILURE = 0x04
    CRC_ERROR = 0x05


class ModbusException(Exception):
    """Raised on the controller side when a device returns an exception frame."""

    def __init__(self, function_code: int, code: ExceptionCode) -> None:
        self.function_code = function_code
        self.code = code
        super().__init__(
            f"device returned exception {code.name} " f"for function {function_code:#04x}"
        )


def encode_exception(unit_id: int, function_code: int, code: ExceptionCode) -> bytes:
    """Build an exception frame for ``function_code`` carrying ``code``."""
    flagged = function_code | FunctionCode.EXCEPTION_MASK
    header = struct.pack(">BBB", unit_id, flagged, int(code)) + b"\x00\x00\x00"
    crc = crc16(header)
    return header + struct.pack("<H", crc)


def is_exception_frame(buffer: bytes) -> bool:
    """Return True if ``buffer`` looks like an exception frame (by the 0x80 bit)."""
    if len(buffer) != FIXED_FRAME_LEN:
        return False
    return bool(buffer[1] & FunctionCode.EXCEPTION_MASK)


def decode_exception(buffer: bytes) -> ModbusException:
    """Parse an exception frame into a :class:`ModbusException`.

    The CRC is validated; a bad CRC is itself surfaced as a CRC_ERROR.
    """
    header = buffer[:6]
    (received_crc,) = struct.unpack("<H", buffer[6:])
    if crc16(header) != received_crc:
        return ModbusException(buffer[1] & 0x7F, ExceptionCode.CRC_ERROR)
    original_fc = buffer[1] & 0x7F
    return ModbusException(original_fc, ExceptionCode(buffer[2]))
