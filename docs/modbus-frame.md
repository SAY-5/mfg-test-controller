# Modbus-style frame layout

This project uses a hand-rolled framing layer. It borrows the function codes,
register addressing, and CRC16 of Modbus RTU, but it is not Modbus: there is no
MBAP header, no transaction identifier, and the fixed-length request form below
is a deliberate simplification chosen so the wire format is trivial to test.

## Fixed request frame (8 bytes)

Every request, and every write response, uses this layout:

```
offset  size  field
0       1     unit_id
1       1     function_code
2       2     start_addr            (big-endian)
4       2     quantity_or_value     (big-endian)
6       2     crc16                 (low byte first)
```

The CRC16 is computed over bytes 0 through 5 (the six header bytes) and
appended low byte first, matching Modbus RTU byte order.

## Function codes

| Code | Name | Meaning of `quantity_or_value` |
|------|------|--------------------------------|
| 0x03 | Read Holding Registers | register count to read |
| 0x04 | Read Input Registers | register count to read |
| 0x06 | Write Single Register | the value to write |
| 0x10 | Write Multiple Registers | register count to write |

## Read response (variable length)

Reads return register data, so the response is variable length:

```
offset  size      field
0       1         unit_id
1       1         function_code
2       1         byte_count            (= register_count * 2)
3       N*2       registers             (each big-endian)
3+N*2   2         crc16                 (low byte first)
```

The CRC covers every byte before it.

## Write Multiple Registers payload

A 0x10 request is the fixed 8-byte frame followed, in the same transport
message, by a bare register block: `register_count` big-endian 16-bit values
with no CRC of their own (the request frame's CRC and the count field guard
it). The server splits the transport message at the 8-byte frame boundary.

## CRC16

The CRC uses the Modbus polynomial 0xA001, seed 0xFFFF, processing each byte
low bit first. A worked check value: `crc16(b"123456789") == 0x4B37`.

A frame whose recomputed CRC does not match the transmitted CRC is rejected.
On the device side a bad request CRC produces an exception frame with
exception code 0x05 (CRC_ERROR). On the controller side a bad response CRC is
surfaced as a `DeviceError`.

## Exception frame

When a device cannot service a request it replies with an exception frame.
The function code is OR-ed with 0x80 and the exception code follows. The frame
is padded to the fixed 8-byte length so the transport never has to special-case
its length:

```
offset  size  field
0       1     unit_id
1       1     function_code | 0x80
2       1     exception_code
3       3     padding (zero)
6       2     crc16 (low byte first)
```

| Exception code | Name |
|----------------|------|
| 0x01 | ILLEGAL_FUNCTION |
| 0x02 | ILLEGAL_DATA_ADDRESS |
| 0x03 | ILLEGAL_DATA_VALUE |
| 0x04 | DEVICE_FAILURE |
| 0x05 | CRC_ERROR |

## Transport framing

Over TCP every message (request or response) is length-prefixed with a 2-byte
big-endian length. This sits below the Modbus-style frame and lets the reader
know exactly how many bytes to consume before parsing.
