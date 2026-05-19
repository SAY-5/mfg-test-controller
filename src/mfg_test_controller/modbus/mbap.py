"""Real Modbus TCP MBAP framing.

The custom framing in :mod:`mfg_test_controller.modbus.frame` is a hand-rolled
8-byte form with a trailing CRC16. This module adds the *standard* Modbus TCP
framing so the controller can talk to actual PLCs.

A Modbus TCP message is an MBAP header followed by the PDU::

    [2B transaction_id][2B protocol_id = 0][2B length][1B unit_id] | PDU

* ``transaction_id`` is echoed by the server so a client can match replies.
* ``protocol_id`` is always 0 for Modbus.
* ``length`` counts the bytes that follow it: ``unit_id`` plus the PDU.
* The PDU is ``[1B function_code][...data...]``.

There is no CRC: TCP already guarantees integrity, and the MBAP ``length``
field is what frames the PDU on the stream.

The PDU shapes used here mirror the four supported function codes:

* request  0x03/0x04: ``[fc][2B start_addr][2B quantity]``
* request  0x06:      ``[fc][2B addr][2B value]``
* request  0x10:      ``[fc][2B start_addr][2B quantity][1B byte_count][regs]``
* response 0x03/0x04: ``[fc][1B byte_count][regs]``
* response 0x06/0x10: echo of the request's address fields
* exception:          ``[fc | 0x80][1B exception_code]``
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from mfg_test_controller.modbus.frame import FrameError

MBAP_HEADER_LEN = 7
"""transaction_id + protocol_id + length + unit_id."""

PROTOCOL_ID = 0
"""The Modbus protocol identifier; always zero."""


@dataclass(frozen=True)
class MbapMessage:
    """A decoded Modbus TCP message: the MBAP header fields plus the PDU."""

    transaction_id: int
    unit_id: int
    pdu: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.transaction_id <= 0xFFFF:
            raise FrameError(f"transaction_id out of range: {self.transaction_id}")
        if not 0 <= self.unit_id <= 0xFF:
            raise FrameError(f"unit_id out of range: {self.unit_id}")
        if not self.pdu:
            raise FrameError("Modbus TCP PDU must not be empty")

    def encode(self) -> bytes:
        """Serialise this message to the Modbus TCP wire format."""
        # length covers the unit_id byte plus the PDU.
        length = 1 + len(self.pdu)
        header = struct.pack(
            ">HHHB",
            self.transaction_id,
            PROTOCOL_ID,
            length,
            self.unit_id,
        )
        return header + self.pdu


def encode_mbap(transaction_id: int, unit_id: int, pdu: bytes) -> bytes:
    """Wrap ``pdu`` in an MBAP header and return the full Modbus TCP message."""
    return MbapMessage(transaction_id, unit_id, pdu).encode()


def decode_mbap(buffer: bytes) -> MbapMessage:
    """Decode one complete Modbus TCP message.

    Validates the header length, the zero protocol id, and that the declared
    ``length`` field matches the buffer. Raises :class:`FrameError` otherwise.
    """
    if len(buffer) < MBAP_HEADER_LEN:
        raise FrameError(f"MBAP message too short: {len(buffer)} bytes")
    transaction_id, protocol_id, length, unit_id = struct.unpack(">HHHB", buffer[:MBAP_HEADER_LEN])
    if protocol_id != PROTOCOL_ID:
        raise FrameError(f"non-Modbus protocol id: {protocol_id}")
    if length < 1:
        raise FrameError(f"MBAP length field too small: {length}")
    expected_total = MBAP_HEADER_LEN + length - 1
    if len(buffer) != expected_total:
        raise FrameError(
            f"MBAP length mismatch: header declares {expected_total} bytes, " f"got {len(buffer)}"
        )
    pdu = buffer[MBAP_HEADER_LEN:]
    return MbapMessage(transaction_id, unit_id, pdu)


def split_stream(buffer: bytes) -> tuple[bytes, bytes] | None:
    """Split one complete MBAP message off the front of ``buffer``.

    Returns ``(message, rest)`` when a full message is present, or ``None``
    when more bytes are still needed. Used by a streaming reader.
    """
    if len(buffer) < MBAP_HEADER_LEN:
        return None
    (length,) = struct.unpack(">H", buffer[4:6])
    total = MBAP_HEADER_LEN + length - 1
    if len(buffer) < total:
        return None
    return buffer[:total], buffer[total:]


__all__ = [
    "MBAP_HEADER_LEN",
    "PROTOCOL_ID",
    "MbapMessage",
    "encode_mbap",
    "decode_mbap",
    "split_stream",
]
