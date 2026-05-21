"""End-to-end web tests, gated by RUN_INTEGRATION=1.

The Flask test client supports server-sent events via the ``iter_encoded``
iterator, so the full POST-then-stream flow can be exercised without a real
socket. The bound thread inside the broker still runs the real sequencer,
so this is a true end-to-end exercise of the web layer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mfg_test_controller.web import WebConfig, create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="integration tests gated by RUN_INTEGRATION=1",
)


def _parse_sse(raw: bytes) -> list[tuple[str, dict[str, object]]]:
    """Parse an SSE byte stream into ``(event, payload)`` pairs."""
    events: list[tuple[str, dict[str, object]]] = []
    text = raw.decode("utf-8")
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            continue
        payload = json.loads("\n".join(data_lines))
        events.append((event_name, payload))
    return events


def _drain_stream(response: object) -> bytes:
    """Read every chunk produced by the SSE generator until it ends."""
    buf = b""
    for chunk in response.iter_encoded():  # type: ignore[attr-defined]
        buf += chunk
        if b"event: done" in buf or b"event: error" in buf:
            break
    return buf


def test_full_web_run_emits_all_step_events_and_done_summary(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'web-int.db'}"
    config = WebConfig(
        db_url=db_url,
        plans_dir=REPO_ROOT / "plans",
        profiles_dir=REPO_ROOT / "profiles",
    )
    app = create_app(config)

    with app.test_client() as client:
        post = client.post("/plans/station_bringup/run")
        assert post.status_code == 200
        body = post.get_json()
        assert "run_id" in body and "stream_url" in body
        stream_url = body["stream_url"]

        response = client.get(stream_url)
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        raw = _drain_stream(response)

    events = _parse_sse(raw)
    kinds = [name for name, _ in events]
    assert kinds[0] == "open"
    assert kinds[-1] == "done"
    step_events = [payload for name, payload in events if name == "step"]
    assert len(step_events) == 11
    for ordinal, payload in enumerate(step_events):
        assert payload["ordinal"] == ordinal
        assert payload["passed"] is True
        assert "register" in payload and "device" in payload

    done = events[-1][1]
    assert done["passed"] == 11
    assert done["failed"] == 0
    assert done["total"] == 11
    assert done["all_passed"] is True
    assert isinstance(done["run_id"], int)


def test_stored_run_page_renders_after_web_run(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'web-int2.db'}"
    config = WebConfig(
        db_url=db_url,
        plans_dir=REPO_ROOT / "plans",
        profiles_dir=REPO_ROOT / "profiles",
    )
    app = create_app(config)

    with app.test_client() as client:
        post = client.post("/plans/station_bringup/run")
        stream_url = post.get_json()["stream_url"]
        raw = _drain_stream(client.get(stream_url))
        events = _parse_sse(raw)
        done = events[-1][1]
        run_id = done["run_id"]
        assert isinstance(run_id, int)

        page = client.get(f"/runs/{run_id}")
        assert page.status_code == 200
        assert b"station_bringup" in page.data
        assert b"PASS" in page.data

        runs_page = client.get("/runs")
        assert runs_page.status_code == 200
        assert f"#{run_id}".encode() in runs_page.data
