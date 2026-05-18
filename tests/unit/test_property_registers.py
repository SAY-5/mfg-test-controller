"""Hypothesis stateful and property tests for the register map.

A random sequence of holding-register reads and writes is applied to both
the :class:`RegisterMap` and an independent Python dict reference; the two
must agree after every operation.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from mfg_test_controller.device.simulated import RegisterMap

ADDRS = st.integers(min_value=0, max_value=0xFFFF)
VALUES = st.integers(min_value=0, max_value=0xFFFF)


@given(
    ops=st.lists(
        st.tuples(ADDRS, VALUES),
        min_size=0,
        max_size=64,
    )
)
def test_holding_writes_are_consistent(ops: list[tuple[int, int]]) -> None:
    """After a random write sequence, every register matches a dict reference."""
    register_map = RegisterMap()
    reference: dict[int, int] = {}
    for addr, value in ops:
        register_map.write(addr, value)
        reference[addr] = value
    assert register_map.holding == reference
    for addr, expected in reference.items():
        assert register_map.read("holding", addr) == expected


@given(addr=ADDRS, value=st.integers(min_value=-1.0e6, max_value=-1))
def test_write_rejects_out_of_range_low(addr: int, value: int) -> None:
    """Negative values are rejected by the holding-register write."""
    register_map = RegisterMap()
    try:
        register_map.write(addr, value)
    except ValueError:
        return
    raise AssertionError("expected ValueError for out-of-range value")


@given(addr=ADDRS, value=st.integers(min_value=0x10000, max_value=0x100000))
def test_write_rejects_out_of_range_high(addr: int, value: int) -> None:
    """Values above 0xFFFF are rejected by the holding-register write."""
    register_map = RegisterMap()
    try:
        register_map.write(addr, value)
    except ValueError:
        return
    raise AssertionError("expected ValueError for out-of-range value")


class RegisterMapStateMachine(RuleBasedStateMachine):
    """Drives RegisterMap with random reads and writes against a dict model."""

    def __init__(self) -> None:
        super().__init__()
        self.register_map = RegisterMap()
        self.model: dict[int, int] = {}

    @rule(addr=ADDRS, value=VALUES)
    def write(self, addr: int, value: int) -> None:
        """Write a holding register and mirror it into the model."""
        self.register_map.write(addr, value)
        self.model[addr] = value

    @rule(addr=ADDRS)
    def read(self, addr: int) -> None:
        """Read a holding register; the result must match the model."""
        if addr in self.model:
            assert self.register_map.read("holding", addr) == self.model[addr]
        else:
            try:
                self.register_map.read("holding", addr)
            except KeyError:
                return
            raise AssertionError("expected KeyError for an unwritten address")

    @invariant()
    def banks_match_model(self) -> None:
        """The holding bank always equals the model dict."""
        assert self.register_map.holding == self.model


TestRegisterMapStateMachine = RegisterMapStateMachine.TestCase
