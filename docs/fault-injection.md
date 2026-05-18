# Fault injection

A simulated device can be configured to misbehave. Fault injection is the
load-bearing piece for testing the controller: every robustness path is
exercised by configuring a device fault rather than by needing real broken
hardware.

## Configuring faults

Faults are listed under a device profile's `faults` key:

```yaml
name: dmm
unit_id: 2
kind: dmm
registers:
  - name: dc_voltage
    address: 0
    kind: input
    value: 4980
faults:
  - kind: drift
    register: 0
    amount: 5
```

## Fault taxonomy

| Kind | Effect | Relevant fields |
|------|--------|-----------------|
| `drift` | Adds `amount` per request to a register on every read, so the value walks off over time | `register`, `amount` |
| `stuck` | Freezes a register: writes to it are silently ignored | `register` |
| `delay` | Sleeps `delay_seconds` before the device responds | `delay_seconds` |
| `crc_corrupt` | Flips a bit in the outgoing CRC so the controller sees a CRC error | none |
| `drop` | Stops responding after `after_requests` requests, simulating a connection drop | `after_requests` |

When `register` is omitted, `drift` and `stuck` apply to every register.

## How each fault surfaces at the controller

- **drift** is silent on the wire: the frame is well-formed. It surfaces as a
  threshold failure once the drifting value leaves its expected range.
- **stuck** is also silent: a write is acknowledged normally but a later read
  returns the old value, which typically fails a readback threshold.
- **delay** surfaces as a `DeviceTimeout` if the delay exceeds the client's
  configured timeout; otherwise it only slows the run.
- **crc_corrupt** makes the response fail CRC validation on the controller,
  surfacing as a `DeviceError`.
- **drop** leaves the controller waiting for a reply that never comes; the
  client surfaces it as a `DeviceTimeout`.

## Observing a fault from the CLI

```
mfg-ctl simulate-fault --profile profiles/dmm.yaml --fault drift --register 0
```

This prints the device's baseline register values and confirms the fault is
configured. To see the fault change a run's outcome, copy the profile, add the
`faults` block, and run a plan against it.

## Scope

The five faults above are illustrative, not an exhaustive catalogue of
instrument failure modes. They were chosen because each one exercises a
distinct controller path: silent measurement error, silent write loss, slow
response, framing error, and lost connection.
