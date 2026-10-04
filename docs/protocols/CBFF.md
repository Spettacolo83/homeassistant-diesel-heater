# CBFF / FEAA Protocol (Sunster V2.1)

**Integration mode:** 6
**Controller app evidence:** AirHeaterBLE Sunster parser and command builder;
encrypted command vectors confirmed by captured traffic

## Scope

Sunster V2.1 controllers send CBFF status notifications and use FEAA command
packets. They are not AA55 command devices. An `AA77` notification identifies a
locked V2.1 session and causes the integration to use the encrypted path.

## Transport and encryption

CBFF is reached through the supported FFF0 transport, with characteristic
direction verified during connection. V2.1 applies two XOR passes to command
and status data:

1. ASCII key `passwordA2409PW`.
2. Uppercase BLE MAC address with separators removed.

The integration accepts raw CBFF, encrypted CBFF, and valid FEAA frames. A
FEAA frame is validated by its header, embedded little-endian total length, and
checksum; length alone is not a protocol identifier.

## Status frame

CBFF status frames are 47 bytes when unencrypted or after decryption.

| Offset | Field | Interpretation |
| --- | --- | --- |
| 0-1 | Header | `CB FF` |
| 2 | Protocol version | Diagnostic value |
| 10 | Run state | `2`, `5`, and `6` are active; all other observed values are inactive |
| 11 | Run mode | `1` level, `2` temperature, `3` ventilation |
| 12 | Run parameter | Level or target temperature |
| 13 | Current gear | Used as level while in temperature mode |
| 14 | Running step | Controller step value |
| 15 | Fault display | Lower six bits are the fault value |
| 17 | Temperature unit | Low nibble: `0` Celsius, `1` Fahrenheit |
| 18-19 | Cabin temperature | Little-endian signed 16-bit value |
| 20 | Altitude unit | Low nibble: `0` metres, `1` feet |
| 21-22 | Altitude | Little-endian unsigned value |
| 23-24 | Supply voltage | Little-endian unsigned value, divided by 10 |
| 25-26 | Case temperature | Little-endian signed value, divided by 10 |
| 27-28 | CO | Little-endian unsigned value, divided by 10 |

## FEAA command frame

```text
FE AA VERSION PACKAGE LENGTH_LO LENGTH_HI CMD_1 CMD_2 PAYLOAD... CHECKSUM
```

The checksum is the sum of all preceding bytes modulo 256. Confirmed command
semantics are:

| Action | `CMD_1`, `CMD_2` | Payload |
| --- | --- | --- |
| Status | `00`, `00` | none |
| Power on | `01`, `01` | last mode, last parameter, `FF FF` |
| Power off | `01`, `00` | last mode, last parameter, `FF FF` |
| Set temperature | `01`, `01` | `02`, target, `FF FF` |
| Set level | `01`, `01` | `01`, level, `FF FF` |
| V2.1 PIN handshake | `06`, `00` | PIN encoded as `[PIN % 100, PIN // 100]` |

The heater requires mode and parameter together. For power and mode changes,
the integration preserves the last controller-reported mode and parameter.
FEAA settings commands are a separate command family and are not implemented;
the integration safely falls back to a FEAA status query, never to AA55.

## Detection

`CB FF` identifies an unencrypted status frame. Encrypted V2.1 frames do not
have a stable visible header, so after `AA77` the active controller session is
routed to CBFF and decrypted before field parsing.
