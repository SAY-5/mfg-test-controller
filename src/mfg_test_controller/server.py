"""Async TCP server hosting one simulated device.

The wire protocol is length-prefixed: every message is a 2-byte big-endian
length followed by that many bytes. A request is one such message; the device
reply is another. Write Multiple Registers requests carry the 8-byte frame
followed by the register block in the same message, so the server splits the
buffer at the fixed frame boundary.
"""

from __future__ import annotations

import asyncio
import struct

from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.frame import FIXED_FRAME_LEN

LENGTH_PREFIX = 2


async def read_message(reader: asyncio.StreamReader) -> bytes:
    """Read one length-prefixed message; returns empty bytes on EOF."""
    header = await reader.readexactly(LENGTH_PREFIX)
    (length,) = struct.unpack(">H", header)
    return await reader.readexactly(length)


def frame_message(payload: bytes) -> bytes:
    """Wrap ``payload`` in a 2-byte length prefix."""
    return struct.pack(">H", len(payload)) + payload


class DeviceServer:
    """Serves a single :class:`SimulatedDevice` over TCP."""

    def __init__(self, device: SimulatedDevice, host: str, port: int) -> None:
        self.device = device
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    message = await read_message(reader)
                except asyncio.IncompleteReadError:
                    break
                request = message[:FIXED_FRAME_LEN]
                payload = message[FIXED_FRAME_LEN:]

                await self.device.faults.apply_delay()
                response = self.device.handle_frame(request, payload)
                if response is None:
                    # Drop fault: close without replying.
                    break
                response = self.device.faults.corrupt_crc(response)
                writer.write(frame_message(response))
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
