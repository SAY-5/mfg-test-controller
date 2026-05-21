"""Flask app factory and routes for the manufacturing test controller web UI.

The web layer is a thin adapter over the existing modules:

* ``GET /`` lists plans on disk and recent runs from the store.
* ``POST /plans/<name>/run`` allocates a run id and kicks off the plan in a
  background thread. The handler returns immediately with ``{"run_id": ...}``.
* ``GET /runs/<run_id>/stream`` is a Server-Sent Events stream emitting one
  ``step`` event per outcome plus a final ``done`` summary. The same broker
  feeds the browser EventSource and the integration test consumer.
* ``GET /runs/<run_id>`` renders a completed run report.
* ``GET /runs`` lists all stored runs.
* ``GET /trends`` reuses ``mfg_test_controller.trends`` directly.
* ``GET /healthz`` returns ``"ok"``.

A web-driven run writes through :class:`RunStore` exactly like a CLI run, so
the SQLite history is shared.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from flask import Flask, Response, abort, jsonify, render_template, stream_with_context, url_for

from mfg_test_controller.config import DeviceProfile, load_device_profile, load_test_plan
from mfg_test_controller.controller.sequencer import StationReport, StepOutcome
from mfg_test_controller.device.profiles import builtin_profile, builtin_profile_names
from mfg_test_controller.modbus.framing import FramingMode
from mfg_test_controller.runner import run_plan_locally
from mfg_test_controller.store import RunStore
from mfg_test_controller.trends import analyse_register, render_trends_markdown

DEFAULT_PROFILE_DIR = Path("profiles")


@dataclass
class WebConfig:
    """Server-side configuration for the web UI."""

    db_url: str = "sqlite:///test-runs.db"
    plans_dir: Path = field(default_factory=lambda: Path("plans"))
    profiles_dir: Path = field(default_factory=lambda: Path("profiles"))
    framing: FramingMode = FramingMode.CUSTOM


@dataclass
class _RunChannel:
    """Per-run event channel and final report."""

    plan_name: str
    queue: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    report: StationReport | None = None
    error: str | None = None
    run_id: int | None = None
    started_at: float = field(default_factory=time.time)
    finished: threading.Event = field(default_factory=threading.Event)


class RunBroker:
    """Tracks in-flight web runs and their event queues.

    The broker is intentionally process-local: a single ``mfg-ctl serve-web``
    process owns its run state. Restarting the server loses live runs but
    completed runs are still recoverable from the SQLite store.
    """

    def __init__(self) -> None:
        self._channels: dict[str, _RunChannel] = {}
        self._lock = threading.Lock()

    def open(self, plan_name: str) -> str:
        """Allocate a new run id and return it."""
        run_uuid = uuid.uuid4().hex
        with self._lock:
            self._channels[run_uuid] = _RunChannel(plan_name=plan_name)
        return run_uuid

    def get(self, run_uuid: str) -> _RunChannel | None:
        """Return the channel for ``run_uuid`` if it exists."""
        with self._lock:
            return self._channels.get(run_uuid)

    def publish_step(self, run_uuid: str, outcome: StepOutcome, ordinal: int) -> None:
        """Push one step outcome onto the run's queue."""
        channel = self.get(run_uuid)
        if channel is None:
            return
        channel.queue.put(
            {
                "kind": "step",
                "ordinal": ordinal,
                "name": outcome.name,
                "device": outcome.device,
                "action": outcome.action,
                "register": outcome.register,
                "passed": outcome.passed,
                "measured": outcome.measured,
                "detail": outcome.detail,
                "duration_s": round(outcome.duration_s, 4),
            }
        )

    def publish_done(self, run_uuid: str, report: StationReport, run_id: int | None) -> None:
        """Push the final ``done`` summary for a completed run."""
        channel = self.get(run_uuid)
        if channel is None:
            return
        channel.report = report
        channel.run_id = run_id
        channel.queue.put(
            {
                "kind": "done",
                "plan": report.plan_name,
                "run_id": run_id,
                "total": report.total,
                "passed": report.passed,
                "failed": report.failed,
                "all_passed": report.all_passed,
                "duration_s": round(report.duration_s, 4),
            }
        )
        channel.finished.set()

    def publish_error(self, run_uuid: str, message: str) -> None:
        """Push a terminal ``error`` event."""
        channel = self.get(run_uuid)
        if channel is None:
            return
        channel.error = message
        channel.queue.put({"kind": "error", "message": message})
        channel.finished.set()


def _format_sse(event: str, payload: dict[str, Any]) -> str:
    """Format one SSE event in the standard ``event:``/``data:`` form."""
    return f"event: {event}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"


def _list_plans(plans_dir: Path) -> list[dict[str, Any]]:
    """Enumerate plan YAML files alongside their step count."""
    if not plans_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(plans_dir.glob("*.yaml")):
        try:
            plan = load_test_plan(path)
        except Exception:  # noqa: BLE001
            continue
        entries.append(
            {
                "name": plan.name,
                "path": str(path),
                "steps_count": len(plan.steps),
                "description": plan.description.strip(),
            }
        )
    return entries


def _resolve_plan_path(plans_dir: Path, plan_name: str) -> Path | None:
    """Find the YAML file whose ``name:`` field matches ``plan_name``."""
    if not plans_dir.exists():
        return None
    for path in sorted(plans_dir.glob("*.yaml")):
        try:
            plan = load_test_plan(path)
        except Exception:  # noqa: BLE001
            continue
        if plan.name == plan_name:
            return path
    return None


def _load_plan_profiles(profiles_dir: Path, plan_profile_names: set[str]) -> list[DeviceProfile]:
    """Resolve profiles for a plan, preferring on-disk YAML over built-ins."""
    profiles: list[DeviceProfile] = []
    for name in sorted(plan_profile_names):
        disk_path = profiles_dir / f"{name}.yaml"
        if disk_path.exists():
            profiles.append(load_device_profile(disk_path))
        elif name in builtin_profile_names():
            profiles.append(builtin_profile(name))
        else:
            raise click.ClickException(f"no profile found for device {name!r}")
    return profiles


def _execute_run(
    run_uuid: str,
    plan_path: Path,
    config: WebConfig,
    broker: RunBroker,
) -> None:
    """Background-thread entry point that runs a plan and pushes SSE events."""
    try:
        plan = load_test_plan(plan_path)
        profiles = _load_plan_profiles(config.profiles_dir, {step.device for step in plan.steps})
        store = RunStore(config.db_url)
        report = StationReport(plan_name=plan.name)
        loop = asyncio.new_event_loop()
        try:
            full_report = loop.run_until_complete(
                run_plan_locally(plan, profiles, framing=config.framing)
            )
        finally:
            loop.close()
        report = full_report
        for ordinal, outcome in enumerate(report.outcomes):
            broker.publish_step(run_uuid, outcome, ordinal)
        device_kinds = {p.name: p.kind for p in profiles}
        run_id = store.save_report(report, device_kinds)
        broker.publish_done(run_uuid, report, run_id)
    except Exception as exc:  # noqa: BLE001
        broker.publish_error(run_uuid, f"{type(exc).__name__}: {exc}")


def _stored_run_payload(store: RunStore, run_id: int) -> dict[str, Any]:
    """Render a stored run as a JSON-friendly dict for templates."""
    stored = store.get_run(run_id)
    if stored is None:
        abort(404)
    verdict = "PASS" if stored.failed_steps == 0 else "FAIL"
    return {
        "id": stored.id,
        "plan": stored.plan_name,
        "verdict": verdict,
        "duration_s": stored.duration_s,
        "total": stored.total_steps,
        "passed": stored.passed_steps,
        "failed": stored.failed_steps,
        "steps": [
            {
                "ordinal": s.ordinal + 1,
                "name": s.name,
                "device": s.device,
                "action": s.action,
                "register": s.register,
                "passed": s.passed,
                "measured": s.measured,
                "detail": s.detail,
                "duration_s": s.duration_s,
            }
            for s in sorted(stored.steps, key=lambda s: s.ordinal)
        ],
    }


def create_app(config: WebConfig | None = None) -> Flask:
    """Return a configured Flask application.

    The same factory is used by the CLI ``serve-web`` subcommand and by the
    unit tests, so test code never has to talk to a real socket.
    """
    cfg = config or WebConfig()
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["WEB_CFG"] = cfg
    broker = RunBroker()
    app.config["RUN_BROKER"] = broker
    app.config["RUN_STORE"] = RunStore(cfg.db_url)

    @app.route("/healthz")
    def healthz() -> Response:
        return Response("ok", mimetype="text/plain")

    @app.route("/")
    def index() -> str:
        plans = _list_plans(cfg.plans_dir)
        store: RunStore = app.config["RUN_STORE"]
        recent = []
        for r in store.list_runs(limit=10):
            recent.append(
                {
                    "id": r.id,
                    "plan": r.plan_name,
                    "verdict": "PASS" if r.failed_steps == 0 else "FAIL",
                    "passed": r.passed_steps,
                    "total": r.total_steps,
                    "duration_s": r.duration_s,
                }
            )
        return render_template("index.html", plans=plans, recent=recent)

    @app.route("/plans")
    def plans_json() -> Response:
        return jsonify(_list_plans(cfg.plans_dir))

    @app.route("/plans/<plan_name>/run", methods=["POST"])
    def run_plan(plan_name: str) -> Response:
        plan_path = _resolve_plan_path(cfg.plans_dir, plan_name)
        if plan_path is None:
            payload = jsonify({"error": f"no plan named {plan_name!r}"})
            payload.status_code = 404
            return payload
        run_uuid = broker.open(plan_name)
        thread = threading.Thread(
            target=_execute_run,
            args=(run_uuid, plan_path, cfg, broker),
            name=f"web-run-{run_uuid[:8]}",
            daemon=True,
        )
        thread.start()
        stream_url = url_for("stream_run", run_uuid=run_uuid)
        return jsonify({"run_id": run_uuid, "stream_url": stream_url})

    @app.route("/runs/stream/<run_uuid>")
    def stream_run(run_uuid: str) -> Response:
        channel = broker.get(run_uuid)
        if channel is None:
            return Response("unknown run", status=404, mimetype="text/plain")

        def _gen() -> Iterator[str]:
            yield _format_sse("open", {"run_uuid": run_uuid, "plan": channel.plan_name})
            while True:
                try:
                    event = channel.queue.get(timeout=30.0)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    if channel.finished.is_set() and channel.queue.empty():
                        break
                    continue
                yield _format_sse(event["kind"], event)
                if event["kind"] in ("done", "error"):
                    break

        return Response(
            stream_with_context(_gen()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/runs/<int:run_id>")
    def show_run(run_id: int) -> str:
        store: RunStore = app.config["RUN_STORE"]
        run = _stored_run_payload(store, run_id)
        return render_template("run.html", run=run)

    @app.route("/runs")
    def list_runs() -> str:
        store: RunStore = app.config["RUN_STORE"]
        runs = []
        for r in store.list_runs(limit=100):
            runs.append(
                {
                    "id": r.id,
                    "plan": r.plan_name,
                    "verdict": "PASS" if r.failed_steps == 0 else "FAIL",
                    "passed": r.passed_steps,
                    "total": r.total_steps,
                    "duration_s": r.duration_s,
                }
            )
        return render_template("runs.html", runs=runs)

    @app.route("/trends")
    def trends_view() -> str:
        store: RunStore = app.config["RUN_STORE"]
        results = []
        for device, register in store.measured_registers():
            values = [m for d, m in store.register_history(register) if d == device]
            if not values:
                continue
            results.append(analyse_register(register, device, values))
        markdown = render_trends_markdown(results) if results else ""
        return render_template("trends.html", trends=results, markdown=markdown)

    return app
