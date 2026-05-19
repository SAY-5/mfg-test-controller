"""Tests for the Modbus TCP MBAP framing layer.

These assert the wire format matches the Modbus TCP specification: the 7-byte
MBAP header, the zero protocol id, and the length field that frames the PDU.
"""

from __future__ import annotations

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.modbus.frame import FrameError
from mfg_test_controller.modbus.mbap import (
    MBAP_HEADER_LEN,
    PROTOCOL_ID,
    MbapMessage,
    decode_mbap,
    encode_mbap,
    split_stream,
)


def test_mbap_header_is_seven_bytes() -> None:
    """The MBAP header is exactly transaction + protocol + length + unit."""
    assert MBAP_HEADER_LEN == 7


def test_encode_mbap_wire_format_matches_spec() -> None:
    """A known PDU encodes to the exact Modbus TCP byte layout."""
    # PDU for Read Holding Registers, addr 8, quantity 2.
    pdu = struct.pack(">BHH", 0x03, 8, 2)
    wire = encode_mbap(transaction_id=0x1234, unit_id=0x11, pdu=pdu)
    # [2B txid][2B protocol=0][2B length][1B unit][PDU]
    assert wire[0:2] == b"\x12\x34"  # transaction id
    assert wire[2:4] == b"\x00\x00"  # protocol id, always zero
    # length covers unit_id (1) + PDU (5) = 6.
    assert struct.unpack(">H", wire[4:6])[0] == 1 + len(pdu)
    assert wire[6] == 0x11  # unit id
    assert wire[MBAP_HEADER_LEN:] == pdu
    assert len(wire) == MBAP_HEADER_LEN + len(pdu)


def test_protocol_id_constant_is_zero() -> None:
    """The Modbus protocol identifier is always zero."""
    assert PROTOCOL_ID == 0


def test_decode_rejects_non_modbus_protocol_id() -> None:
    """A non-zero protocol id is rejected as not Modbus."""
    pdu = b"\x03\x00\x00\x00\x01"
    wire = bytearray(encode_mbap(1, 1, pdu))
    wire[2:4] = b"\x00\x07"  # corrupt protocol id
    with pytest.raises(FrameError, match="non-Modbus protocol"):
        decode_mbap(bytes(wire))


def test_decode_rejects_length_mismatch() -> None:
    """A length field that does not match the buffer is rejected."""
    pdu = b"\x03\x00\x00\x00\x01"
    wire = bytearray(encode_mbap(1, 1, pdu))
    wire[4:6] = struct.pack(">H", 99)  # claim more bytes than present
    with pytest.raises(FrameError, match="length mismatch"):
        decode_mbap(bytes(wire))


def test_decode_rejects_short_buffer() -> None:
    """A buffer shorter than the MBAP header is rejected."""
    with pytest.raises(FrameError, match="too short"):
        decode_mbap(b"\x00\x00\x00")


def test_split_stream_extracts_one_message() -> None:
    """split_stream peels exactly one MBAP message off a concatenated stream."""
    pdu = struct.pack(">BHH", 0x06, 1, 100)
    a = encode_mbap(1, 1, pdu)
    b = encode_mbap(2, 2, pdu)
    result = split_stream(a + b)
    assert result is not None
    first, rest = result
    assert first == a
    assert rest == b


def test_split_stream_waits_for_more_bytes() -> None:
    """split_stream returns None until a full message is buffered."""
    pdu = struct.pack(">BHH", 0x06, 1, 100)
    wire = encode_mbap(1, 1, pdu)
    assert split_stream(wire[:-1]) is None
    assert split_stream(b"\x00\x00") is None


@given(
    txid=st.integers(min_value=0, max_value=0xFFFF),
    unit_id=st.integers(min_value=0, max_value=0xFF),
    pdu=st.binary(min_size=1, max_size=64),
)
def test_mbap_round_trip(txid: int, unit_id: int, pdu: bytes) -> None:
    """Any MBAP message round-trips through encode and decode."""
    message = decode_mbap(encode_mbap(txid, unit_id, pdu))
    assert message.transaction_id == txid
    assert message.unit_id == unit_id
    assert message.pdu == pdu


def test_empty_pdu_is_rejected() -> None:
    """An MBAP message must carry a non-empty PDU."""
    with pytest.raises(FrameError, match="must not be empty"):
        MbapMessage(transaction_id=1, unit_id=1, pdu=b"")
