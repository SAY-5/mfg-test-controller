"""Glue that wires a test plan to in-process simulated devices over loopback.

The CLI ``run`` command does not need real network hosts: it starts a
:class:`DeviceServer` per profile on an ephemeral loopback port, connects a
:class:`DeviceClient` to each, runs the plan, and tears everything down. This
keeps the whole pipeline hermetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AsyncExitStack

from mfg_test_controller.config import DeviceProfile, TestPlan
from mfg_test_controller.controller.client import DeviceClient
from mfg_test_controller.controller.sequencer import Sequencer, StationReport
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.server import DeviceServer

LOOPBACK = "127.0.0.1"


async def run_plan_locally(
    plan: TestPlan,
    profiles: Sequence[DeviceProfile],
    only_failed: list[str] | None = None,
) -> StationReport:
    """Run ``plan`` against in-process simulated devices and return the report."""
    profile_by_name = {p.name: p for p in profiles}
    servers: dict[str, DeviceServer] = {}

    for name, profile in profile_by_name.items():
        device = SimulatedDevice(profile)
        server = DeviceServer(device, LOOPBACK, 0)
        await server.start()
        servers[name] = server

    async with AsyncExitStack() as stack:
        clients: dict[str, DeviceClient] = {}
        for name, server in servers.items():
            client = DeviceClient(LOOPBACK, server.sockets_port)
            await stack.enter_async_context(client)
            clients[name] = client

        sequencer = Sequencer(plan, profile_by_name, clients)
        report = await sequencer.run(only_failed=only_failed)

    for server in servers.values():
        await server.stop()
    return report
