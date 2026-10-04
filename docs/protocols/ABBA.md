# ABBA Protocol (HeaterCC)

**Integration mode:** 5
**Controller app and hardware evidence:** AirHeaterCC command behavior and
confirmed HeaterCC hardware captures

## Transport

| Item | Value |
| --- | --- |
| Service | `0000FFF0-0000-1000-8000-00805F9B34FB` |
| Legacy notify | `0000FFF1-0000-1000-8000-00805F9B34FB` |
| Legacy write | `0000FFF2-0000-1000-8000-00805F9B34FB` |
| Notification header | `AB BA` |
| Command header | `BA AB` |

The coordinator verifies characteristic direction. A split FFF0 layout with
FFF1 write and FFF2 notify is DZ06 Neo, not legacy ABBA.

## Status fields

ABBA status frames have at least 21 bytes. The fields used by the integration
are:

| Offset | Field | Interpretation |
| --- | --- | --- |
| 4 | Status | `0` off, `1` heating, `2` cooldown, `4` ventilation, `6` standby |
| 5 | Mode | `0` level, `1` temperature, `FF` error |
| 6 | Value | Level, target temperature, or error code when mode is `FF` |
| 8 | Auto start/stop | `1` enabled |
| 9 | Supply voltage | Whole volts |
| 10 | Temperature unit | `0` Celsius, `1` Fahrenheit |
| 11 | Cabin temperature | Raw value minus 30 in Celsius or 22 in Fahrenheit |
| 12-13 | Case temperature | Big-endian unsigned value |
| 14 | Altitude unit | Controller value |
| 15 | High-altitude mode | Controller value |
| 16-17 | Altitude | Big-endian unsigned value |

Cooldown and ventilation are active states: they must not be presented as an
immediate power-off merely because fuel heating has stopped.

## Commands

Commands consist of the command bytes below followed by their additive checksum.

| Action | Bytes before checksum | Evidence-backed behavior |
| --- | --- | --- |
| Status request | `BA AB 04 CC 00 00 00` | Request current status |
| Heat toggle | `BA AB 04 BB A1 00 00` | One toggle for start and controlled cooldown |
| Set temperature | `BA AB 04 DB TT 00 00` | `TT` is target temperature |
| Increase level | `BA AB 04 BB A2 00 00` | One relative level step up |
| Decrease level | `BA AB 04 BB A3 00 00` | One relative level step down |
| Level to temperature | `BA AB 04 BB AD 00 00` | Transition from level mode |
| Temperature to level | `BA AB 04 BB AC 00 00` | Transition from temperature mode |
| Ventilation | `BA AB 04 BB A4 00 00` | Works from standby/off on confirmed hardware |

Level is not set with a single absolute packet. The integration compares the
reported level with the requested level and sends the required number of A2 or
A3 steps. Controller level counts can vary; documentation must not claim a
universal six-level ABBA range.

## Detection

ABBA is selected after the FFF0 service and legacy characteristic layout have
been established, or when a notification begins `AB BA`. It is not identified
by the AA-family FFE0/FFE1 transport.
