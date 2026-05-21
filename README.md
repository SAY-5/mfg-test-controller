# mfg-test-controller

A Python TCP/IP manufacturing test controller simulator. It models a test
station: a controller issues Modbus-style register reads and writes to
simulated instruments over TCP, evaluates each measurement against a per-step
threshold, and produces a pass/fail station report. No real hardware is
involved; every device is simulated and every connection runs over loopback
TCP, so the whole pipeline is hermetic and runs in CI.

## What this studies

- **Two wire formats for the same four function codes.** The default
  `custom` framing is a hand-rolled 8-byte frame with a CRC16 (polynomial
  0xA001) on every frame, fully documented in `docs/modbus-frame.md`. The
  `modbus-tcp` framing is real Modbus TCP with the standard MBAP header and is
  wire-compatible with actual Modbus TCP devices and PLCs; see
  `docs/modbus-tcp.md`. The `--framing` flag selects the mode, and device
  profiles and test plans are framing-agnostic.
- **Simulated devices with fault injection.** A `SimulatedDevice` holds a
  register map and answers frames. Devices can be configured to drift, freeze a
  register, delay a response, corrupt a CRC, or drop the connection. Fault
  injection is the load-bearing piece: it exercises the controller's robustness
  paths without needing broken instruments.
- **Threshold-driven test sequencing.** A test plan is an ordered YAML list of
  steps. Each step reads or writes a register and, for reads, compares the
  value against an expected value plus tolerance or an expected range.
- **A concrete 11-to-4 step reduction.** See below.

## The 11-to-4 step reduction

A manual station bring-up for the four-instrument example
(`plans/station_bringup.yaml`) is 11 hands-on actions:

1. Connect to the power supply, set its voltage.
2. Set the power supply current limit.
3. Enable the power supply output.
4. Read the voltage meter, transcribe the value, compare to spec.
5. Read the current meter, transcribe the value, compare to spec.
6. Connect to the actuator, command its position.
7. Read back the actuator position, compare to spec.
8. Read the actuator status word, compare to spec.
9. Connect to the multimeter, read DC voltage, compare to spec.
10. Connect to the thermocouple module, read channel 0, compare to spec.
11. Read the thermocouple cold-junction value, compare to spec.

Those 11 steps become the 11 entries of the plan file. The operator-facing
flow collapses to four:

1. `mfg-ctl run plans/station_bringup.yaml` runs all 11 steps, reads and
   writes every register, and applies every threshold.
2. Review the station report (pass/fail per step, first failing step,
   wall-clock duration).
3. `mfg-ctl run plans/station_bringup.yaml --only-failed` re-runs just the
   steps that failed in the previous recorded run.
4. `mfg-ctl run ... --json-out report.json --md-out report.md` exports the
   report for records.

The reduction is in operator actions, not in the work itself: the controller
still performs all 11 register operations. What collapses is the manual
connect/transcribe/compare loop, which becomes one command and a recorded
report.

## Web UI

A small Flask web UI wraps the same modules the CLI uses. It lists plans on
disk, kicks off a run in a background thread, and streams each step to the
browser over Server-Sent Events so an operator can watch the plan execute
step-by-step. Web-driven runs persist through the same `RunStore` as CLI
runs, so the history table is shared.

```
poetry run mfg-ctl serve-web --port 5050
# open http://127.0.0.1:5050 in a browser
```

Routes: `/` lists plans and recent runs, `/plans` is JSON, `POST
/plans/<name>/run` allocates a run id and starts the plan, `/runs/stream/<id>`
is the SSE stream, `/runs/<int:id>` renders a stored run, `/runs` lists all
runs, `/trends` reuses the trend analysis, `/healthz` returns `ok`.

Pages render in vanilla HTML and a small static JS bundle; the live-run view
uses the browser `EventSource` API. A placeholder for a screenshot lives at
`docs/web-ui.md`.

## Modules

| Module | Responsibility |
|--------|----------------|
| `modbus/frame.py` | Fixed-length frame, CRC16, function codes |
| `modbus/codec.py` | Encode/decode the four function codes |
| `modbus/exceptions.py` | Exception frames |
| `modbus/mbap.py` | Real Modbus TCP MBAP header encode/decode |
| `modbus/framing.py` | `Framer`: custom vs modbus-tcp wire translation |
| `device/simulated.py` | `SimulatedDevice` and its register map |
| `device/profiles.py` | Built-in power_supply, dmm, actuator, thermocouple |
| `device/faults.py` | Drift, stuck, delay, crc-corrupt, drop |
| `controller/client.py` | Async TCP client |
| `controller/sequencer.py` | Runs a test plan step by step |
| `controller/thresholds.py` | Measurement-vs-spec evaluation |
| `server.py` | Async TCP server hosting a device |
| `store.py` | SQLAlchemy: TestRun, StepResult, Device |
| `report.py` | JSON and Markdown station reports |
| `trends.py` | SPC trend analysis, drift detection, runs-to-failure |
| `config.py` | Pydantic models and YAML loaders |
| `runner.py` | Wires a plan to in-process devices over loopback |
| `web/app.py` | Flask app, SSE broker, route handlers |
| `cli.py` | Click CLI: run, devices, report, replay, simulate-fault, serve, serve-web, trends |

## Architecture

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
            (async, 0x03/04/06/10)            (length-prefixed frames)
                  |
                  v
        StationReport  -->  SQLite store  +  JSON / Markdown
```

## Quickstart

With Poetry:

```
make dev          # poetry install
make test         # unit tests + hypothesis property tests, 70% coverage gate
make typecheck    # mypy strict on src/
make lint         # ruff + black --check
make run          # run plans/station_bringup.yaml against simulated devices
```

`make test` runs the example-based unit tests plus a hypothesis property and
fuzz suite (codec round-trips, CRC single-bit-flip detection, threshold
verdicts against a hand-computed reference, register-map consistency, and a
frame-parser fuzz that asserts random byte streams never crash the parser).
It fails the build if line coverage drops below 70%.

The four simulated devices and a controller also run under Docker:

```
make up           # docker compose: 4 device containers + controller
```

## Sample station report

```
Plan: station_bringup  [PASS]
   1 ok   set_supply_voltage: wrote 1200 to voltage_setpoint
   2 ok   set_supply_current_limit: wrote 500 to current_limit
   3 ok   enable_supply_output: wrote 1 to output_enable
   4 ok   check_supply_voltage_readback: measured 1200, expected 1200 +/- 25 (delta 0)
   5 ok   check_supply_current_readback: measured 480, expected within [400, 520]
   6 ok   command_actuator_position: wrote 500 to target_position
   7 ok   check_actuator_position: measured 500, expected 500 +/- 10 (delta 0)
   8 ok   check_actuator_status: measured 1, expected 1 +/- 0 (delta 0)
   9 ok   check_dmm_dc_voltage: measured 4980, expected 5000 +/- 50 (delta 20)
  10 ok   check_thermocouple_channel_0: measured 2300, expected within [2200, 2400]
  11 ok   check_thermocouple_cold_junction: measured 2500, expected within [2300, 2700]
  11/11 passed in 0.010s
```

A committed copy of the JSON and Markdown forms lives in `docs/`.

## Test-cycle benchmark

`bench/cycle_bench.py` runs the `station_bringup` plan repeatedly against the
four simulated devices over loopback TCP and measures per-cycle wall-clock,
per-command round-trip latency, and controller throughput. It runs once with
clean devices and once with drift and delay faults injected so the
fault-handling cost is visible.

```
make bench            # run the benchmark, write bench/results/<timestamp>.json
make bench-regress    # fail if per-cycle wall-clock regresses past 30%
```

Indicative numbers from a 200-cycle run (11 commands per cycle):

| Pass | Per-cycle wall-clock (mean) | Command latency P50 / P95 / P99 | Throughput |
|------|-----------------------------|---------------------------------|------------|
| Clean | ~1.0 ms | ~0.09 / 0.13 / 0.15 ms | ~10,600 commands/s |
| Fault-injected | ~2.6 ms | ~0.08 / 1.36 / 1.55 ms | ~4,200 commands/s |

The drift and delay faults roughly halve throughput, which is the expected
cost of the controller's fault-handling paths. `make bench-regress` compares a
fresh run against the most recent stored result and fails the build if the
mean per-cycle wall-clock drifts up by more than 30%. CI runs a small-scale
bench-smoke pass on every push.

## Trend analysis and drift detection

A measured register can stay inside its threshold for many runs while it
steadily walks toward the limit. `mfg-ctl trends` reads the stored run history
and, per measured register, computes mean, standard deviation, min/max, a
least-squares linear-fit slope (the per-run drift rate), and a Statistical
Process Control control-chart classification of `in-control`, `trending`, or
`out-of-control`.

```
mfg-ctl trends --station station_bringup            # summary per register
mfg-ctl trends --register dc_voltage --station station_bringup --limit 5000
mfg-ctl trends --station station_bringup --export trend-report.md
```

A register still passing its threshold but drifting toward a limit is flagged
`trending`. When a `--limit` is supplied, the linear fit is extrapolated to the
limit boundary to estimate the runs-to-failure: how many further runs before
the measurement is expected to breach the threshold. `--export` writes a
Markdown control-chart report; with no value it prints to stdout. See
`docs/trend-analysis.md` for the SPC rules, the linear-fit method, and the
runs-to-failure extrapolation.

## What this is not

- Not a real Modbus implementation. There is no Modbus TCP/RTU library, no MBAP
  header, no real transaction handling. The framing is a documented, hand-rolled
  approximation chosen for testability.
- Not a real PLC, and there are no real instruments. Every device is simulated.
- No OPC-UA, no test-stand hardware abstraction layer, no safety interlocks.
- No GUI and no multi-station orchestration.
- The fault model (drift, stuck, delay, crc-corrupt, drop) is illustrative, not
  an exhaustive catalogue of instrument failure modes.

## License

MIT, see `LICENSE`.
