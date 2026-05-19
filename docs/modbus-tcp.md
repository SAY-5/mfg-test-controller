# Modbus TCP framing mode

The controller ships with two wire formats, selected with `--framing`:

* `custom` (default): the hand-rolled 8-byte frame with a trailing CRC16,
  documented in [modbus-frame.md](modbus-frame.md).
* `modbus-tcp`: real Modbus TCP framing. This mode is wire-compatible with
  actual Modbus TCP devices and PLCs.

The four function codes (0x03 Read Holding Registers, 0x04 Read Input
Registers, 0x06 Write Single Register, 0x10 Write Multiple Registers) work in
both modes. Device profiles and test plans are framing-agnostic: the same
YAML runs unchanged under either format.

## MBAP header

A Modbus TCP message is an MBAP (Modbus Application Protocol) header followed
by the PDU (Protocol Data Unit):

```
offset  size  field
0       2     transaction_id     (big-endian)
2       2     protocol_id = 0    (big-endian, always zero for Modbus)
4       2     length             (big-endian)
6       1     unit_id
7       N     PDU
```

* `transaction_id` is chosen by the client and echoed verbatim by the server
  so replies can be matched to requests on a multiplexed connection.
* `protocol_id` is always `0`. A non-zero value is rejected as not Modbus.
* `length` counts every byte that follows the length field itself, that is
  `unit_id` (1 byte) plus the PDU. It is what frames the message on the TCP
  stream: a reader consumes the 7-byte header, reads `length - 1` more bytes,
  and has exactly one complete message.
* `unit_id` identifies the target device, equivalent to the Modbus RTU slave
  address.

## No CRC

Modbus TCP carries **no CRC**. TCP already guarantees byte-stream integrity,
and the MBAP `length` field handles message framing. This is the key
difference from the custom framing, where every frame ends in a CRC16 over
the polynomial 0xA001 and the transport adds a separate 2-byte length prefix.

| Aspect | `custom` framing | `modbus-tcp` framing |
|--------|------------------|----------------------|
| Header | 8-byte fixed frame | 7-byte MBAP header |
| Integrity | CRC16 (0xA001) per frame | none (TCP handles it) |
| Message framing | 2-byte length prefix | MBAP `length` field |
| Request matching | none | `transaction_id` |
| Read response | variable, CRC-checked | `[fc][byte_count][regs]` |

## PDU shapes

The PDU is `[1 byte function_code][data]`. The shapes for the four function
codes:

| Direction | Function code | PDU layout |
|-----------|---------------|------------|
| request | 0x03 / 0x04 | `[fc][2B start_addr][2B quantity]` |
| request | 0x06 | `[fc][2B addr][2B value]` |
| request | 0x10 | `[fc][2B start_addr][2B quantity][1B byte_count][regs]` |
| response | 0x03 / 0x04 | `[fc][1B byte_count][regs]` |
| response | 0x06 / 0x10 | `[fc][2B addr][2B value]` (echo) |
| exception | any | `[fc \| 0x80][1B exception_code]` |

An exception is signalled by setting the high bit (0x80) of the function
code, exactly as in Modbus RTU; the exception codes are the same set listed
in [modbus-frame.md](modbus-frame.md).

## Worked example

A Read Holding Registers request for unit 7, start address 4, quantity 2,
with transaction id 0x0001:

```
00 01   transaction_id = 1
00 00   protocol_id = 0
00 06   length = 6  (unit_id + 5-byte PDU)
07      unit_id = 7
03      function_code = 0x03
00 04   start_addr = 4
00 02   quantity = 2
```

That is 12 bytes total: 7 header bytes plus a 5-byte PDU, and no trailing
CRC.

## Implementation

`modbus/mbap.py` encodes and decodes the MBAP header. `modbus/framing.py`
provides a `Framer` that translates between the internal custom frame
representation and either wire format, so the `SimulatedDevice`, sequencer,
and threshold logic are written once and run unchanged in both modes. The
`--framing` flag on `mfg-ctl run` and `mfg-ctl serve` selects the mode.
