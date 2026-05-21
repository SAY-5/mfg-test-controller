# Web UI

The web UI ships as `mfg-ctl serve-web` and binds to `127.0.0.1:5050` by
default. It is a thin Flask layer that reuses the existing sequencer, store,
and trends modules; web-driven runs and CLI runs share the SQLite history
table.

## Layout

- `/` lists discoverable plans, recent runs, and provides a per-plan
  `run` button. The live-run panel below the plan table renders each step
  as the SSE stream delivers it.
- `/plans` returns a JSON listing of plans on disk.
- `POST /plans/<name>/run` allocates a run id, starts the plan on a
  background thread, and returns `{"run_id": ..., "stream_url": ...}`.
- `/runs/stream/<run_id>` is the Server-Sent Events stream. Events:
  - `open`, one event with the run id and plan name.
  - `step`, one event per step outcome with ordinal, name, device, action,
    register, pass/fail verdict, measured value, detail, and duration.
  - `done`, the final summary with total/passed/failed/duration and the
    stored `run_id`.
  - `error`, terminal failure with the message.
- `/runs/<id>` renders a completed run report from the store.
- `/runs` lists all stored runs.
- `/trends` renders the SPC trend analysis from `mfg_test_controller.trends`.
- `/healthz` returns `ok`.

## Screenshot placeholder

A screenshot of the live-run view belongs here once the build pipeline
captures one in CI. Until then, see the SSE sample below for the operator
experience.

## Sample SSE payload

```
event: step
data: {"action": "read", "detail": "measured 1200, expected 1200 +/- 25 (delta 0)", "device": "power_supply", "duration_s": 0.0002, "kind": "step", "measured": 1200.0, "name": "check_supply_voltage_readback", "ordinal": 3, "passed": true, "register": "voltage_readback"}
```
