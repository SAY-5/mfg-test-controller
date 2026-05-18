"""Hand-rolled Modbus-style framing and codec layer."""

from mfg_test_controller.modbus.codec import (
    decode_request,
    decode_response,
    encode_read_holding,
    encode_read_input,
    encode_write_multiple,
    encode_write_single,
)
from mfg_test_controller.modbus.exceptions import (
    ExceptionCode,
    ModbusException,
    decode_exception,
    encode_exception,
)
from mfg_test_controller.modbus.frame import (
    Frame,
    FrameError,
    FunctionCode,
    crc16,
)

__all__ = [
    "Frame",
    "FrameError",
    "FunctionCode",
    "crc16",
    "decode_request",
    "decode_response",
    "encode_read_holding",
    "encode_read_input",
    "encode_write_multiple",
    "encode_write_single",
    "ExceptionCode",
    "ModbusException",
    "decode_exception",
    "encode_exception",
]
