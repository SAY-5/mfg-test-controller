"""Hypothesis property tests for the Modbus-style codec and frame layer.

These complement the example-based tests in ``test_codec.py`` and
``test_frame.py`` by asserting structural invariants over wide random
inputs: encode/decode round-trips, CRC single-bit-flip detection, and the
variable-length read-response framing.
"""

from __future__ import annotations

import struct

from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.modbus.codec import (
    MAX_REGISTERS,
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
from mfg_test_controller.modbus.frame import Frame, FunctionCode

UNIT_IDS = st.integers(min_value=0, max_value=0xFF)
ADDRS = st.integers(min_value=0, max_value=0xFFFF)
VALUES = st.integers(min_value=0, max_value=0xFFFF)
REGISTERS = st.lists(VALUES, min_size=0, max_size=MAX_REGISTERS)


@given(unit_id=UNIT_IDS, addr=ADDRS, quantity=VALUES)
def test_read_holding_round_trip(unit_id: int, addr: int, quantity: int) -> None:
    """A Read Holding request encodes then decodes bit-identically."""
    frame = decode_request(encode_read_holding(unit_id, addr, quantity))
    assert frame.unit_id == unit_id
    assert frame.function_code == FunctionCode.READ_HOLDING_REGISTERS
    assert frame.start_addr == addr
    assert frame.quantity_or_value == quantity


@given(unit_id=UNIT_IDS, addr=ADDRS, quantity=VALUES)
def test_read_input_round_trip(unit_id: int, addr: int, quantity: int) -> None:
    """A Read Input request encodes then decodes bit-identically."""
    frame = decode_request(encode_read_input(unit_id, addr, quantity))
    assert frame.unit_id == unit_id
    assert frame.function_code == FunctionCode.READ_INPUT_REGISTERS
    assert frame.start_addr == addr
    assert frame.quantity_or_value == quantity


@given(unit_id=UNIT_IDS, addr=ADDRS, value=VALUES)
def test_write_single_round_trip(unit_id: int, addr: int, value: int) -> None:
    """A Write Single request encodes then decodes bit-identically."""
    frame = decode_request(encode_write_single(unit_id, addr, value))
    assert frame.unit_id == unit_id
    assert frame.function_code == FunctionCode.WRITE_SINGLE_REGISTER
    assert frame.start_addr == addr
    assert frame.quantity_or_value == value


@given(unit_id=UNIT_IDS, addr=ADDRS, quantity=VALUES)
def test_write_multiple_round_trip(unit_id: int, addr: int, quantity: int) -> None:
    """A Write Multiple request encodes then decodes bit-identically."""
    frame = decode_request(encode_write_multiple(unit_id, addr, quantity))
    assert frame.unit_id == unit_id
    assert frame.function_code == FunctionCode.WRITE_MULTIPLE_REGISTERS
    assert frame.start_addr == addr
    assert frame.quantity_or_value == quantity


@given(
    unit_id=UNIT_IDS,
    function_code=st.sampled_from(
        [FunctionCode.READ_HOLDING_REGISTERS, FunctionCode.READ_INPUT_REGISTERS]
    ),
    registers=REGISTERS,
)
def test_read_response_round_trip(unit_id: int, function_code: int, registers: list[int]) -> None:
    """A read response carrying random registers round-trips exactly."""
    decoded = decode_read_response(encode_read_response(unit_id, function_code, registers))
    assert decoded.unit_id == unit_id
    assert decoded.function_code == function_code
    assert decoded.registers == registers


@given(
    unit_id=UNIT_IDS,
    function_code=st.sampled_from(
        [FunctionCode.READ_HOLDING_REGISTERS, FunctionCode.READ_INPUT_REGISTERS]
    ),
    registers=REGISTERS,
)
def test_decode_response_dispatches_reads(
    unit_id: int, function_code: int, registers: list[int]
) -> None:
    """decode_response dispatches read function codes to ReadResponse."""
    decoded = decode_response(encode_read_response(unit_id, function_code, registers))
    assert hasattr(decoded, "registers")
    assert decoded.registers == registers  # type: ignore[union-attr]


@given(unit_id=UNIT_IDS, addr=ADDRS, value=VALUES)
def test_decode_response_dispatches_writes(unit_id: int, addr: int, value: int) -> None:
    """decode_response dispatches write function codes to a Frame."""
    decoded = decode_response(encode_write_single(unit_id, addr, value))
    assert isinstance(decoded, Frame)
    assert decoded.quantity_or_value == value


@given(registers=REGISTERS)
def test_register_block_round_trip(registers: list[int]) -> None:
    """A bare register block round-trips through encode and decode."""
    assert decode_register_block(encode_register_block(registers)) == registers


@given(registers=st.lists(VALUES, min_size=1, max_size=8))
def test_read_response_crc_single_bit_flip_detected(registers: list[int]) -> None:
    """Every single-bit flip in a read response is caught by the CRC check."""
    buffer = encode_read_response(1, FunctionCode.READ_HOLDING_REGISTERS, registers)
    for byte_index in range(len(buffer)):
        for bit in range(8):
            mutated = bytearray(buffer)
            mutated[byte_index] ^= 1 << bit
            try:
                decoded = decode_read_response(bytes(mutated))
            except Exception:
                continue
            # If it still parsed, the bytes must be unchanged from the original.
            assert bytes(mutated) == buffer
            assert decoded.registers == registers


@given(buffer=st.binary(min_size=0, max_size=64))
def test_decode_register_block_never_crashes(buffer: bytes) -> None:
    """decode_register_block either parses or raises a structured FrameError."""
    try:
        result = decode_register_block(buffer)
    except Exception as exc:  # noqa: BLE001
        from mfg_test_controller.modbus.frame import FrameError

        assert isinstance(exc, FrameError)
    else:
        assert len(result) == len(buffer) // 2
        assert struct.calcsize(">" + "H" * len(result)) == len(buffer)
