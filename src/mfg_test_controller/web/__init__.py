"""Web UI for the manufacturing test controller.

A thin Flask layer that wraps the existing sequencer, store, and trends
modules. Web runs persist through the same :class:`RunStore` as CLI runs,
and live step results stream to the browser via Server-Sent Events. The
web layer is intentionally an adapter, not a re-implementation, so the
behaviour of a web-driven run is identical to ``mfg-ctl run``.
"""

from __future__ import annotations

from mfg_test_controller.web.app import WebConfig, create_app

__all__ = ["WebConfig", "create_app"]
