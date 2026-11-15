# CBFF / FEAA Protocol (Sunster V2.1)

**Integration mode:** 6
**Controller app evidence:** Sunster 2.2.000 V2.1 parser and command builder;
encrypted command vectors also confirmed by captured traffic

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
| 8 | Mainboard type | Ventilation is advertised for `1`, `11`, and `21` |
| 10 | Run state | `2`, `5`, and `6` are active; all other observed values are inactive |
| 11 | Run mode | `1` level, `2` temperature, `3` ventilation |
| 12 | Run parameter | Level or target temperature |
| 13 | Current gear | Used as level while in temperature mode |
| 14 | Running step | Controller step value |
| 15 | Fault display | Lower six bits are the fault value |
| 17 | Temperature unit | Low nibble: `0` Celsius, `1` Fahrenheit |
| 18-19 | Cabin temperature | Little-endian signed 16-bit value |
| 20 | Altitude unit | Low nibble: `0` metres, `1` feet |
| 21-22 | Altitude | Little-endian unsigned value; protocol version 1 uses whole units, other versions divide by 10 |
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
| Select ventilation | `01`, current power state | `03`, remembered fan level or `01`, `FF FF` |
| Set ventilation level | `01`, current power state | `03`, level, `FF FF` |
| Read settings | `03`, `00` | none |
| Read metadata | `00`, `03` | none |
| V2.1 PIN handshake | `06`, `00` | PIN encoded as `[PIN % 100, PIN // 100]` |

The heater requires mode and parameter together. For power and mode changes,
the integration preserves the last controller-reported mode and parameter.
Ventilation is offered only for validated mainboard types `1`, `11`, and `21`,
matching the app's mode list. Selecting ventilation preserves the reported
on/off state. Fan-level changes retain mode `3` rather than selecting heating.

FEAA settings use the app's `03/01` command and a complete 13-byte settings
snapshot. A settings change reads current attributes with `03/00`, modifies
one supported field, then reads back the applied value under one transaction
lock. Full validated `83/00`, `83/01`, and `83/02` attribute replies refresh the
snapshot; a short acknowledgement alone does not confirm a changed value.
Missing snapshots and unsupported (`255`) fields are rejected.

Clock writes use the same packet family but a different payload form: offsets
2-3 contain local minutes plus `0x8000`; offsets 4-7 contain the low byte of the
year, month, day of month, and JavaScript weekday (Sunday `0`). These slots carry
offset, language, tank size, and pump type only in the ordinary settings form.
Building a clock packet does not replace the cached ordinary settings.

## Language capabilities

The Sunster V2.1 language codes differ from AA66: `0` Off, `1` English,
`2` Chinese, `3` Russian, `4` German, `5` Turkish, `6` Korean, `7` French,
`8` Polish. The app filters these using the `00/03` metadata response's
little-endian language mask at bytes 16-17 (bit 0 enables code 1).
The integration uses the same mask; before it is known it offers only Off and
the currently reported language, and rejects unsupported writes.

The app names this field `broadcast_language`. This establishes the protocol
setting, not whether every LCD firmware shares it with the menu language or
persists it across power loss. No separate EEPROM-save command was identified
in this path. Unsupported generic commands raise an error instead of silently
becoming status queries.

## Detection

`CB FF` identifies an unencrypted status frame. Encrypted V2.1 frames do not
have a stable visible header, so after `AA77` the active controller session is
routed to CBFF and decrypted before field parsing.
