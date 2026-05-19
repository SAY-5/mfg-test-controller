"""Async TCP client that talks to simulated devices.

The client encodes Modbus-style requests, sends them over the configured wire
format, and decodes the response. Exception frames are surfaced as
:class:`ModbusException`; a missing or malformed reply (drop fault, delay
timeout) is surfaced as :class:`DeviceTimeout` or :class:`DeviceError`.

The wire format is chosen by the :class:`Framer` passed at construction:
``custom`` for the hand-rolled 8-byte framing or ``modbus-tcp`` for real
Modbus TCP MBAP framing. The request-building and response-decoding logic is
identical in both modes; only the transport edge differs.
"""

from __future__ import annotations

import asyncio
import contextlib

from mfg_test_controller.modbus.codec import (
    decode_read_response,
    encode_read_holding,
    encode_read_input,
    encode_register_block,
    encode_write_multiple,
    encode_write_single,
)
from mfg_test_controller.modbus.exceptions import (
    ModbusException,
    decode_exception,
    is_exception_frame,
)
from mfg_test_controller.modbus.frame import Frame, FrameError
from mfg_test_controller.modbus.framing import Framer, FramingMode
from mfg_test_controller.server import frame_wire_message, read_wire_message


class DeviceError(Exception):
    """Raised when a device reply cannot be parsed or is otherwise invalid."""


class DeviceTimeout(DeviceError):
    """Raised when a device does not reply within the configured timeout."""


class DeviceClient:
    """A connection to one simulated device."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 2.0,
        framer: Framer | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.framer = framer if framer is not None else Framer(FramingMode.CUSTOM)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        """Open the TCP connection."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=self.timeout
        )

    async def close(self) -> None:
        """Close the TCP connection."""
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await self._writer.wait_closed()
            self._reader = None
            self._writer = None

    async def __aenter__(self) -> DeviceClient:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def _exchange(self, request: bytes, payload: bytes = b"") -> bytes:
        if self._reader is None or self._writer is None:
            raise DeviceError("client is not connected")
        wire_request = self.framer.wrap_request(request, payload)
        self._writer.write(frame_wire_message(wire_request, self.framer))
        await self._writer.drain()
        try:
            wire_response = await asyncio.wait_for(
                read_wire_message(self._reader, self.framer), timeout=self.timeout
            )
        except asyncio.IncompleteReadError as exc:
            raise DeviceTimeout("device closed connection without replying") from exc
        except TimeoutError as exc:
            raise DeviceTimeout(f"device did not reply within {self.timeout}s") from exc
        try:
            return self.framer.unwrap_response(wire_response)
        except FrameError as exc:
            raise DeviceError(f"malformed wire response: {exc}") from exc

    @staticmethod
    def _raise_if_exception(response: bytes) -> None:
        if is_exception_frame(response):
            raise decode_exception(response)

    async def read_holding_registers(
        self, unit_id: int, start_addr: int, quantity: int
    ) -> list[int]:
        """Issue a Read Holding Registers (0x03) request."""
        response = await self._exchange(encode_read_holding(unit_id, start_addr, quantity))
        self._raise_if_exception(response)
        try:
            return decode_read_response(response).registers
        except FrameError as exc:
            raise DeviceError(str(exc)) from exc

    async def read_input_registers(self, unit_id: int, start_addr: int, quantity: int) -> list[int]:
        """Issue a Read Input Registers (0x04) request."""
        response = await self._exchange(encode_read_input(unit_id, start_addr, quantity))
        self._raise_if_exception(response)
        try:
            return decode_read_response(response).registers
        except FrameError as exc:
            raise DeviceError(str(exc)) from exc

    async def write_single_register(self, unit_id: int, addr: int, value: int) -> None:
        """Issue a Write Single Register (0x06) request."""
        response = await self._exchange(encode_write_single(unit_id, addr, value))
        self._raise_if_exception(response)
        try:
            Frame.decode(response)
        except FrameError as exc:
            raise DeviceError(str(exc)) from exc

    async def write_multiple_registers(
        self, unit_id: int, start_addr: int, values: list[int]
    ) -> None:
        """Issue a Write Multiple Registers (0x10) request."""
        request = encode_write_multiple(unit_id, start_addr, len(values))
        payload = encode_register_block(values)
        response = await self._exchange(request, payload)
        self._raise_if_exception(response)
        try:
            Frame.decode(response)
        except FrameError as exc:
            raise DeviceError(str(exc)) from exc


__all__ = ["DeviceClient", "DeviceError", "DeviceTimeout", "ModbusException"]
