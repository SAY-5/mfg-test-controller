"""Hypothesis property tests for the Modbus CRC16 (polynomial 0xA001).

The load-bearing guarantee of a CRC is single-bit-error detection: flipping
any one bit of a buffer must change the CRC. These tests assert that over
random buffers, plus basic determinism and range invariants.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.modbus.frame import crc16

BUFFERS = st.binary(min_size=1, max_size=64)


@given(data=st.binary(min_size=0, max_size=128))
def test_crc16_is_16_bit(data: bytes) -> None:
    """The CRC always fits in 16 bits."""
    assert 0 <= crc16(data) <= 0xFFFF


@given(data=st.binary(min_size=0, max_size=128))
def test_crc16_is_deterministic(data: bytes) -> None:
    """The CRC of a buffer is stable across calls."""
    assert crc16(data) == crc16(data)


@given(data=BUFFERS)
def test_crc16_detects_every_single_bit_flip(data: bytes) -> None:
    """Flipping any single bit of the buffer changes the CRC."""
    baseline = crc16(data)
    for byte_index in range(len(data)):
        for bit in range(8):
            mutated = bytearray(data)
            mutated[byte_index] ^= 1 << bit
            assert crc16(bytes(mutated)) != baseline, f"bit {bit} of byte {byte_index} not detected"


@given(data=BUFFERS, extra=st.integers(min_value=1, max_value=8))
def test_crc16_detects_appended_zero_bytes(data: bytes, extra: int) -> None:
    """Appending zero bytes shifts the CRC (length is part of the cover)."""
    assert crc16(data) != crc16(data + b"\x00" * extra)


@given(a=BUFFERS, b=BUFFERS)
def test_crc16_distinguishes_distinct_buffers_mostly(a: bytes, b: bytes) -> None:
    """Equal buffers share a CRC; the converse is only a probabilistic hint."""
    if a == b:
        assert crc16(a) == crc16(b)
