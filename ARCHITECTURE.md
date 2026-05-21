# Architecture

This document describes how the manufacturing test controller simulator is put
together and the reasoning behind the main design choices.

## Overview

The system has two sides connected by loopback TCP:

- The **device side**: a `SimulatedDevice` holding register banks, wrapped by a
  `DeviceServer` that speaks a length-prefixed wire protocol.
- The **controller side**: a `DeviceClient` that issues Modbus-style requests,
  and a `Sequencer` that runs a YAML test plan and evaluates each measurement
  against a threshold.

```
            test plan (YAML)            device profiles (YAML)
                  |                              |
                  v                              v
   +-----------------------------+   +---------------------------+
   |        Sequencer            |   |     SimulatedDevice       |
   |  step -> client request     |   |  register map + faults    |
   |  response -> threshold eval  |   +-------------+-------------+
   +--------------+--------------+                 |
                  |                                |
            DeviceClient  --- loopback TCP --->  DeviceServer
                  |
                  v
        StationReport  -->  SQLite store  +  JSON / Markdown
```

## Modbus-style frame layer

The framing is hand-rolled, not a real Modbus library. The full byte layout is
in `docs/modbus-frame.md`. The reasons for hand-rolling it:

- The wire format is fully documented and owned by this project, so every byte
  is testable.
- A fixed 8-byte request form means the transport never has to frame
  variable-length request buffers.
- It keeps the project self-contained: no dependency surface for the part of
  the system most worth understanding.

Every frame carries a CRC16 using the Modbus polynomial 0xA001. The codec is a
pure module: encode and decode for the four function codes, with no I/O. This
makes it suitable for a hypothesis property test that random frames round-trip
and that any single-bit flip is either caught by the CRC or decodes to a
different frame.

Read responses are variable length (they carry register data), so they use a
separate `byte_count`-prefixed form. Write responses echo the request and use
the fixed 8-byte form.

## Simulated devices

A `SimulatedDevice` is constructed from a `DeviceProfile` (a Pydantic model
loaded from YAML). It holds two register banks, holding and input, each a
dict keyed by 16-bit address. `handle_frame` decodes a request, dispatches on
function code, and returns response bytes. It is synchronous and pure with
respect to I/O: the async transport lives in `DeviceServer`.

Four built-in profiles model distinct instrument shapes:

- `power_supply`: voltage and current setpoints (holding) plus readbacks
  (input).
- `dmm`: measurement registers (input) and a range selector (holding).
- `actuator`: a commanded position (holding) and an actual position plus
  status word (input).
- `thermocouple`: temperature channels (input only).

## Fault-injection taxonomy

Fault injection is the load-bearing piece for testing the controller. A
`FaultEngine` wraps register access and response handling. Five faults are
modelled, each chosen to exercise a distinct controller path:

| Fault | Controller path exercised |
|-------|---------------------------|
| `drift` | Silent measurement error caught only by a threshold |
| `stuck` | Silent write loss caught only by a readback |
| `delay` | Slow response, possibly a client timeout |
| `crc_corrupt` | Framing error: response fails CRC validation |
| `drop` | Lost connection: client times out waiting |

The set is illustrative, not exhaustive. See `docs/fault-injection.md`.

## Sequencer and threshold evaluation

The `Sequencer` walks a `TestPlan` step by step. For each step it resolves the
device profile and the named register, issues the matching client call (read
or write), and for read steps passes the measurement to `evaluate_step`.

`evaluate_step` supports two threshold forms: an `expected_value` with a
`tolerance`, and an `expected_range` with inclusive bounds. Each step produces
a `StepOutcome` with a pass/fail verdict, the measured value, a human-readable
detail string, and a per-step duration. Device errors (timeouts, CRC errors,
exception frames) are caught and recorded as failed steps rather than aborting
the run, so a single bad device does not hide the rest of the report.

A `StationReport` aggregates the outcomes: total steps, passed, failed, the
first failing step, and the wall-clock duration.

## Persistence and reporting

`store.py` defines three SQLAlchemy tables: `test_run`, `step_result`, and
`device`. Each run of a plan is persisted so that `--only-failed` and `replay`
can look up prior results. `report.py` renders a `StationReport` as JSON, as
Markdown, or as a compact console summary.

## The 11-to-4 step mapping

The honest framing of the "11 steps to 4 steps" claim:

The manual bring-up of the four-instrument example station is 11 hands-on
actions: connect to the power supply and set its voltage; set its current
limit; enable its output; read and transcribe and compare the voltage meter;
the same for the current meter; connect to the actuator and command its
position; read back and compare the position; read and compare the status
word; connect to the multimeter and read and compare DC voltage; connect to
the thermocouple module and read and compare channel 0; read and compare the
cold-junction value.

Those 11 actions become the 11 steps of `plans/station_bringup.yaml`. The
operator-facing flow then collapses to four: run the plan, review the report,
re-run failed steps with `--only-failed`, export the report.

The reduction is in operator actions, not in the underlying work. The
controller still performs all 11 register operations on every run. What
collapses is the manual connect / transcribe / compare loop, which the
controller automates and the SQLite store records.

## Web layer

The optional Flask web UI in `web/app.py` is a thin adapter over the
existing modules, not a re-implementation. The same `Sequencer`, `RunStore`,
and `trends` code that the CLI uses also backs the browser, so a web-driven
run is byte-for-byte the same as `mfg-ctl run`.

The interesting piece is the live step stream. The browser opens a Server-
Sent Events connection to `/runs/stream/<run_id>` and receives one `step`
event per outcome plus a terminal `done` event. The server side has three
components:

- A `RunBroker` that holds a per-run thread-safe queue and a completion
  event. The broker is process-local: a single `serve-web` process owns its
  run state and restart loses any in-flight runs. Completed runs remain in
  SQLite.
- A background `threading.Thread` that constructs a fresh `asyncio` loop,
  awaits `run_plan_locally`, and publishes one queue entry per outcome. The
  thread terminates by publishing either a `done` or `error` event.
- A streaming Flask response that reads from the queue with a 30-second
  blocking `get`, formats each entry as an SSE block, and emits a keepalive
  comment when the queue is idle.

SSE was chosen over WebSockets because step events only flow server-to-
client, the browser `EventSource` API handles reconnection and parsing on
its own, and the SSE wire format is plain text that the integration tests
parse with a few lines of split-and-decode rather than a WebSocket client.

`mfg-ctl serve-web` boots the app under `waitress`, the same pure-Python
WSGI server `pip` itself uses for its index server, so the production
dependency footprint stays in the standard ecosystem and there is no C
extension to compile.

## Hermetic execution

There is no real hardware and no external network. The `runner` module starts
each simulated device on an ephemeral `127.0.0.1` port, so `mfg-ctl run`, the
integration tests, and CI all run the full client/server path over loopback
with nothing to provision.
