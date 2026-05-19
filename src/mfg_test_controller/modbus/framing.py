"""Framing-mode abstraction over the wire transport.

The controller supports two wire formats for the same four function codes:

* ``custom``     the hand-rolled 8-byte frame with a trailing CRC16, carried
                 over a 2-byte length prefix. See :mod:`.frame`.
* ``modbus-tcp`` the real Modbus TCP MBAP framing. See :mod:`.mbap`.

Device profiles, test plans, the sequencer, and the simulated devices are all
framing-agnostic: a :class:`SimulatedDevice` only ever sees the custom 8-byte
request frame and produces custom responses. This module translates between
that internal representation and whichever wire format is selected, so the
device and controller logic is written once.

The translation for ``modbus-tcp`` maps each MBAP message to the equivalent
custom frame and back. A transaction id is carried per request and echoed on
the matching response, exactly as the Modbus TCP spec requires.
"""

from __future__ import annotations

import struct
from enum import Enum

from mfg_test_controller.modbus.codec import (
    decode_register_block,
    encode_register_block,
)
from mfg_test_controller.modbus.exceptions import is_exception_frame
from mfg_test_controller.modbus.frame import (
    FIXED_FRAME_LEN,
    Frame,
    FrameError,
    FunctionCode,
)
from mfg_test_controller.modbus.mbap import (
    MBAP_HEADER_LEN,
    decode_mbap,
    encode_mbap,
)

_READ_CODES = (
    FunctionCode.READ_HOLDING_REGISTERS,
    FunctionCode.READ_INPUT_REGISTERS,
)


class FramingMode(str, Enum):
    """Selects the wire format used by the client and server."""

    CUSTOM = "custom"
    MODBUS_TCP = "modbus-tcp"


def parse_framing_mode(value: str) -> FramingMode:
    """Parse a CLI string into a :class:`FramingMode`."""
    try:
        return FramingMode(value)
    except ValueError as exc:
        raise FrameError(f"unknown framing mode: {value!r}") from exc


# --- modbus-tcp PDU helpers -------------------------------------------------


def _custom_request_to_pdu(request: bytes, payload: bytes) -> bytes:
    """Translate a custom 8-byte request frame into a Modbus TCP PDU."""
    frame = Frame.decode(request)
    fc = frame.function_code
    if fc == FunctionCode.WRITE_MULTIPLE_REGISTERS:
        registers = decode_register_block(payload)
        byte_count = len(registers) * 2
        return struct.pack(
            ">BHHB", fc, frame.start_addr, frame.quantity_or_value, byte_count
        ) + encode_register_block(registers)
    return struct.pack(">BHH", fc, frame.start_addr, frame.quantity_or_value)


def _pdu_to_custom_request(unit_id: int, pdu: bytes) -> tuple[bytes, bytes]:
    """Translate a Modbus TCP request PDU into a custom frame plus payload."""
    if len(pdu) < 5:
        raise FrameError(f"Modbus TCP request PDU too short: {len(pdu)} bytes")
    fc, addr, value = struct.unpack(">BHH", pdu[:5])
    frame = Frame(unit_id, fc, addr, value)
    if fc == FunctionCode.WRITE_MULTIPLE_REGISTERS:
        if len(pdu) < 6:
            raise FrameError("Modbus TCP write-multiple PDU missing byte count")
        byte_count = pdu[5]
        block = pdu[6:]
        if len(block) != byte_count:
            raise FrameError(
                f"Modbus TCP write-multiple byte count mismatch: "
                f"declared {byte_count}, got {len(block)}"
            )
        return frame.encode(), block
    return frame.encode(), b""


def _custom_response_to_pdu(response: bytes) -> bytes:
    """Translate a custom response frame into a Modbus TCP response PDU."""
    if is_exception_frame(response):
        # Exception frame: function_code|0x80 then exception code.
        return bytes([response[1], response[2]])
    fc = response[1]
    if fc in _READ_CODES:
        # Custom read response: [unit][fc][byte_count][regs][crc].
        byte_count = response[2]
        registers = response[3 : 3 + byte_count]
        return bytes([fc, byte_count]) + registers
    # Write response: echo the address and value fields.
    frame = Frame.decode(response)
    return struct.pack(">BHH", fc, frame.start_addr, frame.quantity_or_value)


# --- Framer -----------------------------------------------------------------


class Framer:
    """Translates between the internal custom frames and a selected wire mode.

    ``custom`` mode is a pass-through: the wire bytes already are the internal
    representation. ``modbus-tcp`` mode translates each message through the
    MBAP layer.
    """

    def __init__(self, mode: FramingMode = FramingMode.CUSTOM) -> None:
        self.mode = mode
        self._next_txid = 0

    @property
    def is_modbus_tcp(self) -> bool:
        """True when this framer uses real Modbus TCP framing."""
        return self.mode is FramingMode.MODBUS_TCP

    def _allocate_txid(self) -> int:
        txid = self._next_txid
        self._next_txid = (self._next_txid + 1) & 0xFFFF
        return txid

    # -- client side --------------------------------------------------------

    def wrap_request(self, request: bytes, payload: bytes = b"") -> bytes:
        """Wrap an internal request (frame + payload) for the wire."""
        if self.mode is FramingMode.CUSTOM:
            return request + payload
        unit_id = request[0]
        pdu = _custom_request_to_pdu(request, payload)
        return encode_mbap(self._allocate_txid(), unit_id, pdu)

    def unwrap_response(self, wire: bytes) -> bytes:
        """Translate a wire response back into the internal custom form.

        For ``custom`` mode this is identity. For ``modbus-tcp`` mode the
        MBAP message is decoded and its PDU re-expressed as a custom frame or
        read response so the existing controller decoders apply unchanged.
        """
        if self.mode is FramingMode.CUSTOM:
            return wire
        message = decode_mbap(wire)
        return _pdu_to_internal_response(message.unit_id, message.pdu)

    # -- server side --------------------------------------------------------

    def parse_request(self, wire: bytes) -> tuple[bytes, bytes]:
        """Split a wire request into the internal ``(frame, payload)`` pair."""
        if self.mode is FramingMode.CUSTOM:
            return wire[:FIXED_FRAME_LEN], wire[FIXED_FRAME_LEN:]
        message = decode_mbap(wire)
        return _pdu_to_custom_request(message.unit_id, message.pdu)

    def wrap_response(self, response: bytes, request_wire: bytes) -> bytes:
        """Wrap an internal device response for the wire.

        ``request_wire`` is the original request so a ``modbus-tcp`` reply can
        echo the transaction id and unit id.
        """
        if self.mode is FramingMode.CUSTOM:
            return response
        message = decode_mbap(request_wire)
        pdu = _custom_response_to_pdu(response)
        return encode_mbap(message.transaction_id, message.unit_id, pdu)


def _pdu_to_internal_response(unit_id: int, pdu: bytes) -> bytes:
    """Re-express a Modbus TCP response PDU as the internal custom form."""
    from mfg_test_controller.modbus.codec import encode_read_response
    from mfg_test_controller.modbus.exceptions import ExceptionCode, encode_exception

    if not pdu:
        raise FrameError("empty Modbus TCP response PDU")
    fc = pdu[0]
    if fc & FunctionCode.EXCEPTION_MASK:
        if len(pdu) < 2:
            raise FrameError("Modbus TCP exception PDU missing exception code")
        return encode_exception(unit_id, fc & 0x7F, ExceptionCode(pdu[1]))
    if fc in _READ_CODES:
        if len(pdu) < 2:
            raise FrameError("Modbus TCP read response PDU too short")
        byte_count = pdu[1]
        block = pdu[2 : 2 + byte_count]
        if len(block) != byte_count:
            raise FrameError("Modbus TCP read response byte count mismatch")
        registers = list(decode_register_block(block))
        return encode_read_response(unit_id, fc, registers)
    if len(pdu) < 5:
        raise FrameError("Modbus TCP write response PDU too short")
    _fc, addr, value = struct.unpack(">BHH", pdu[:5])
    return Frame(unit_id, fc, addr, value).encode()


__all__ = [
    "FramingMode",
    "Framer",
    "parse_framing_mode",
    "MBAP_HEADER_LEN",
]
