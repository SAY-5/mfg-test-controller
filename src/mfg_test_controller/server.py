"""Async TCP server hosting one simulated device.

Two wire formats are supported, selected by a :class:`Framer`:

* ``custom``: every message is a 2-byte big-endian length followed by that
  many bytes. A request is one such message; the device reply is another.
  Write Multiple Registers requests carry the 8-byte frame followed by the
  register block in the same message.
* ``modbus-tcp``: real Modbus TCP framing. The MBAP ``length`` field frames
  the message on the stream, so there is no separate 2-byte length prefix.

The :class:`SimulatedDevice` itself only ever sees the internal custom 8-byte
request frame; the framer translates to and from the wire format.
"""

from __future__ import annotations

import asyncio
import struct

from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.framing import Framer, FramingMode
from mfg_test_controller.modbus.mbap import MBAP_HEADER_LEN, split_stream

LENGTH_PREFIX = 2


async def read_message(reader: asyncio.StreamReader) -> bytes:
    """Read one length-prefixed message; raises IncompleteReadError on EOF."""
    header = await reader.readexactly(LENGTH_PREFIX)
    (length,) = struct.unpack(">H", header)
    return await reader.readexactly(length)


def frame_message(payload: bytes) -> bytes:
    """Wrap ``payload`` in a 2-byte length prefix."""
    return struct.pack(">H", len(payload)) + payload


async def read_mbap_message(reader: asyncio.StreamReader) -> bytes:
    """Read one complete Modbus TCP MBAP message off the stream."""
    header = await reader.readexactly(MBAP_HEADER_LEN)
    (length,) = struct.unpack(">H", header[4:6])
    body = await reader.readexactly(length - 1)
    return header + body


async def read_wire_message(reader: asyncio.StreamReader, framer: Framer) -> bytes:
    """Read one wire message using the transport framing for ``framer``."""
    if framer.is_modbus_tcp:
        return await read_mbap_message(reader)
    return await read_message(reader)


def frame_wire_message(payload: bytes, framer: Framer) -> bytes:
    """Wrap a wire message for transport.

    Modbus TCP messages are self-framing via the MBAP length field, so they
    are written as-is; custom messages get the 2-byte length prefix.
    """
    if framer.is_modbus_tcp:
        return payload
    return frame_message(payload)


class DeviceServer:
    """Serves a single :class:`SimulatedDevice` over TCP."""

    def __init__(
        self,
        device: SimulatedDevice,
        host: str,
        port: int,
        *,
        framer: Framer | None = None,
    ) -> None:
        self.device = device
        self.host = host
        self.port = port
        self.framer = framer if framer is not None else Framer(FramingMode.CUSTOM)
        self._server: asyncio.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    wire = await read_wire_message(reader, self.framer)
                except asyncio.IncompleteReadError:
                    break
                request, payload = self.framer.parse_request(wire)

                await self.device.faults.apply_delay()
                response = self.device.handle_frame(request, payload)
                if response is None:
                    # Drop fault: close without replying.
                    break
                response = self.device.faults.corrupt_crc(response)
                wire_response = self.framer.wrap_response(response, wire)
                writer.write(frame_wire_message(wire_response, self.framer))
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self) -> None:
        """Bind and start accepting connections."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)

    @property
    def sockets_port(self) -> int:
        """Return the actual bound port (useful when port 0 was requested)."""
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server not started")
        port: int = self._server.sockets[0].getsockname()[1]
        return port

    async def serve_forever(self) -> None:
        """Serve until cancelled."""
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the server and release the socket."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


__all__ = [
    "DeviceServer",
    "LENGTH_PREFIX",
    "read_message",
    "frame_message",
    "read_mbap_message",
    "read_wire_message",
    "frame_wire_message",
    "split_stream",
]
