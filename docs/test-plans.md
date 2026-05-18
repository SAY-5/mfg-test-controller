# Test plans

A test plan is a YAML file describing an ordered list of steps run against one
or more simulated devices.

## Plan structure

```yaml
name: station_bringup
description: free text
steps:
  - name: unique_step_name
    device: power_supply
    action: read            # read or write
    register: voltage_readback
    expected_value: 1200    # for read steps
    tolerance: 25
```

### Step fields

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Unique step name, used by `--only-failed` |
| `device` | yes | Name of a device profile |
| `action` | yes | `read` or `write` |
| `register` | yes | A register name on that device's profile |
| `expected_value` | read steps | Target value for the measurement |
| `tolerance` | optional | Allowed absolute deviation from `expected_value` |
| `expected_range` | read steps | A `[low, high]` inclusive range |
| `write_value` | write steps | Value to write to the register |

A read step must declare either `expected_value` (optionally with
`tolerance`) or `expected_range`. A write step must declare `write_value`.
These rules are enforced by the config layer when the plan loads.

## Threshold evaluation

For `expected_value`, the step passes when
`abs(measured - expected_value) <= tolerance`. With `tolerance: 0` the match
must be exact.

For `expected_range`, the step passes when `low <= measured <= high`, with
both bounds inclusive.

Write steps always record a pass once the device acknowledges the write; they
do not carry a threshold.

## Running a plan

```
mfg-ctl run plans/station_bringup.yaml
```

The runner starts an in-process simulated device per referenced profile on an
ephemeral loopback TCP port, connects a client to each, runs every step in
order, and records the result to the SQLite store. The exit code is non-zero
when any step fails.

### Re-running failed steps

```
mfg-ctl run plans/station_bringup.yaml --only-failed
```

This looks up the most recent recorded run of the same plan, collects the
names of its failing steps, and runs only those.

### Exporting reports

```
mfg-ctl run plans/station_bringup.yaml --json-out report.json --md-out report.md
```

## Profile resolution

For each device name referenced by a plan, the runner looks first for
`profiles/<name>.yaml` on disk, then falls back to the built-in profile of the
same name. A device name with neither is an error.
