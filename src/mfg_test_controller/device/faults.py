"""Fault injection for simulated devices.

The fault engine wraps register access and frame handling so a device can be
made to misbehave in controlled ways. This is the load-bearing piece for
testing the controller: every robustness path in the controller is exercised
by configuring a device fault rather than by needing real broken hardware.

Faults:

* ``drift``       add ``amount`` to a register on every read (slow walk-off)
* ``stuck``       freeze a register at its current value, ignoring writes
* ``delay``       sleep ``delay_seconds`` before responding
* ``crc_corrupt`` flip a bit in the outgoing CRC so the controller sees a
                  CRC error
* ``drop``        stop responding entirely after ``after_requests`` requests
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from mfg_test_controller.config import FaultConfig


@dataclass
class FaultEngine:
    """Applies a device's configured faults to register access and responses."""

    faults: list[FaultConfig]
    request_count: int = field(default=0, init=False)

    def fault(self, kind: str) -> FaultConfig | None:
        """Return the first configured fault of ``kind``, if any."""
        for fault in self.faults:
            if fault.kind == kind:
                return fault
        return None

    @property
    def has_faults(self) -> bool:
        """True if any fault is configured."""
        return bool(self.faults)

    def note_request(self) -> None:
        """Record that a request was received (drives count-gated faults)."""
        self.request_count += 1

    def should_drop(self) -> bool:
        """True if the connection-drop fault is active for this request."""
        fault = self.fault("drop")
        if fault is None:
            return False
        return self.request_count > fault.after_requests

    async def apply_delay(self) -> None:
        """Sleep if a delay fault is configured."""
        fault = self.fault("delay")
        if fault is not None and fault.delay_seconds > 0:
            await asyncio.sleep(fault.delay_seconds)

    def apply_read_drift(self, address: int, value: int) -> int:
        """Apply a drift fault to a register value being read out."""
        fault = self.fault("drift")
        if fault is None:
            return value
        if fault.register is not None and fault.register != address:
            return value
        return (value + fault.amount * self.request_count) & 0xFFFF

    def is_stuck(self, address: int) -> bool:
        """True if ``address`` is frozen by a stuck fault."""
        fault = self.fault("stuck")
        if fault is None:
            return False
        return fault.register is None or fault.register == address

    def corrupt_crc(self, frame: bytes) -> bytes:
        """Flip the low CRC bit if a crc_corrupt fault is configured."""
        if self.fault("crc_corrupt") is None or len(frame) < 1:
            return frame
        mutated = bytearray(frame)
        mutated[-1] ^= 0x01
        return bytes(mutated)
