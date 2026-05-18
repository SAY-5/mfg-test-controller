"""SimulatedDevice: a register map that responds to Modbus-style frames."""

from __future__ import annotations

from mfg_test_controller.config import DeviceProfile
from mfg_test_controller.device.faults import FaultEngine
from mfg_test_controller.modbus.codec import (
    decode_register_block,
    encode_read_response,
)
from mfg_test_controller.modbus.exceptions import ExceptionCode, encode_exception
from mfg_test_controller.modbus.frame import Frame, FrameError, FunctionCode


class RegisterMap:
    """Holding and input register banks addressed by 16-bit address."""

    def __init__(self) -> None:
        self.holding: dict[int, int] = {}
        self.input: dict[int, int] = {}

    def bank(self, kind: str) -> dict[int, int]:
        """Return the register bank for ``kind`` (holding or input)."""
        if kind == "holding":
            return self.holding
        if kind == "input":
            return self.input
        raise ValueError(f"unknown register kind: {kind}")

    def read(self, kind: str, address: int) -> int:
        """Read one register; missing addresses raise KeyError."""
        return self.bank(kind)[address]

    def write(self, address: int, value: int) -> None:
        """Write one holding register (input registers are read-only)."""
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"register value out of range: {value}")
        self.holding[address] = value


class SimulatedDevice:
    """A simulated test-equipment device driven by a :class:`DeviceProfile`."""

    def __init__(self, profile: DeviceProfile) -> None:
        self.profile = profile
        self.unit_id = profile.unit_id
        self.registers = RegisterMap()
        self.faults = FaultEngine(profile.faults)
        for spec in profile.registers:
            self.registers.bank(spec.kind)[spec.address] = spec.value

    def handle_frame(self, request: bytes, payload: bytes = b"") -> bytes | None:
        """Process a request frame and return the response bytes.

        ``payload`` carries the register block for Write Multiple Registers.
        Returns ``None`` when a drop fault suppresses the response. CRC
        corruption and delay faults are applied by the transport, not here.
        """
        self.faults.note_request()
        if self.faults.should_drop():
            return None

        try:
            frame = Frame.decode(request)
        except FrameError:
            return encode_exception(
                self.unit_id,
                FunctionCode.READ_HOLDING_REGISTERS,
                ExceptionCode.CRC_ERROR,
            )

        if frame.unit_id != self.unit_id:
            return encode_exception(
                frame.unit_id, frame.function_code, ExceptionCode.DEVICE_FAILURE
            )

        fc = frame.function_code
        if fc == FunctionCode.READ_HOLDING_REGISTERS:
            return self._read(frame, "holding")
        if fc == FunctionCode.READ_INPUT_REGISTERS:
            return self._read(frame, "input")
        if fc == FunctionCode.WRITE_SINGLE_REGISTER:
            return self._write_single(frame)
        if fc == FunctionCode.WRITE_MULTIPLE_REGISTERS:
            return self._write_multiple(frame, payload)
        return encode_exception(self.unit_id, fc, ExceptionCode.ILLEGAL_FUNCTION)

    def _read(self, frame: Frame, kind: str) -> bytes:
        bank = self.registers.bank(kind)
        values: list[int] = []
        for offset in range(frame.quantity_or_value):
            address = frame.start_addr + offset
            if address not in bank:
                return encode_exception(
                    self.unit_id,
                    frame.function_code,
                    ExceptionCode.ILLEGAL_DATA_ADDRESS,
                )
            raw = bank[address]
            values.append(self.faults.apply_read_drift(address, raw))
        return encode_read_response(self.unit_id, frame.function_code, values)

    def _write_single(self, frame: Frame) -> bytes:
        address = frame.start_addr
        if address not in self.registers.holding:
            return encode_exception(
                self.unit_id,
                frame.function_code,
                ExceptionCode.ILLEGAL_DATA_ADDRESS,
            )
        if not self.faults.is_stuck(address):
            self.registers.write(address, frame.quantity_or_value)
        return frame.encode()

    def _write_multiple(self, frame: Frame, payload: bytes) -> bytes:
        try:
            values = decode_register_block(payload)
        except FrameError:
            return encode_exception(
                self.unit_id,
                frame.function_code,
                ExceptionCode.ILLEGAL_DATA_VALUE,
            )
        if len(values) != frame.quantity_or_value:
            return encode_exception(
                self.unit_id,
                frame.function_code,
                ExceptionCode.ILLEGAL_DATA_VALUE,
            )
        for offset in range(len(values)):
            address = frame.start_addr + offset
            if address not in self.registers.holding:
                return encode_exception(
                    self.unit_id,
                    frame.function_code,
                    ExceptionCode.ILLEGAL_DATA_ADDRESS,
                )
        for offset, value in enumerate(values):
            address = frame.start_addr + offset
            if not self.faults.is_stuck(address):
                self.registers.write(address, value)
        return frame.encode()
