# Hcalory Protocol

**Integration mode:** 7
**Controller app evidence:** Hcalory protocol implementations and Hcalory app
transport definitions

## Scope

The Hcalory Android app identifies these controller variants from manufacturer
advertisement data: `MVP1`, `MVP2`, `MVP1_2`, `MVP1_3`, `MVP2_2`, `MVP2_3`,
`MVP3`, `MVP3_2`, and `MVP3_3`. They share the Hcalory envelope and status
layout. The app selects a GATT transport independently from the command family,
so an FFF0 service alone must not be treated as ABBA or as Hcalory.

## Transport

| Variant | Service | Write characteristic | Notify characteristic |
| --- | --- | --- | --- |
| MVP1 | `0000FFF0-0000-1000-8000-00805F9B34FB` | `0000FFF2-0000-1000-8000-00805F9B34FB` | `0000FFF1-0000-1000-8000-00805F9B34FB` |
| MVP2 | `0000BD39-0000-1000-8000-00805F9B34FB` | `0000BDF7-0000-1000-8000-00805F9B34FB` | `0000BDF8-0000-1000-8000-00805F9B34FB` |

Legacy `MVP1` sends its status query using `0E 04`. `MVP2` and all seven
numbered MVP variants use authenticated `0A 0A` status requests with the current
time encoded as raw hour, minute, second, ISO weekday, and a trailing `00`.
This is neither a Unix timestamp nor BCD.

## Command envelope

```text
00 02 00 01 00 01 00 CMD_HI CMD_LO 00 00 LENGTH PAYLOAD... CHECKSUM
```

The checksum is the additive sum from byte 8 through the final payload byte,
modulo 256. Confirmed control commands are:

| Action | Command | Payload / behavior |
| --- | --- | --- |
| Set level | `06 07` | Direct controller level, `1` through `10` |
| Set temperature | `07 06` | Target temperature and unit |
| Power | `0E 04` | Final value `01` off, `02` on |
| Automatic start/stop | `0E 04` | Final value `05` toggles the controller setting |
| Temperature mode | `0E 04` | Final value `06` |
| Level mode | `0E 04` | Final value `07` |
| Temperature unit | `0E 04` | Final value `0A` Celsius, `0B` Fahrenheit |
| MVP2 status request | `0A 0A` | Raw current-time payload |
| PIN update | `0A 0C` | Four PIN digits |

The Hcalory app defaults MVP2 controller authentication to `0000`. The integration
stores PINs numerically, so enter that factory value as `0`.

The app and implementation both use direct levels `1` through `10`. Older
claims that Hcalory universally exposes only six levels are incorrect. The
integration does not advertise ventilation or altitude-control packets as
confirmed universal behavior because those commands vary by controller and lack
equivalent protocol evidence.

## Status frame

Hcalory status packets are at least 38 bytes. The integration reads these
fields:

| Offset | Field | Interpretation |
| --- | --- | --- |
| 18 | Altitude mode | Controller value |
| 20 | State and step | High nibble is state; low nibble is operating step |
| 21 | Mode | `0` off, `1` temperature, `2` level, `3` ventilation |
| 22 | Set value / error | Setpoint normally; fault value while in error state |
| 23 | Automatic start/stop | `1` enabled, `2` disabled |
| 24-25 | Supply voltage | Big-endian unsigned value, divided by 10 |
| 27-28 | Case temperature | Big-endian unsigned value, divided by 10 |
| 30-31 | Cabin temperature | Big-endian unsigned value, divided by 10 |
| 37 | Temperature unit | Controller unit value |

The state high nibble is `0` off, `4` turning off, `8` heating, `C`
ventilation, or `F` error. The step low nibble is `0` inactive, `1` fan,
`3` igniting, `5` running, or `7` standby. Turning off is an active,
controlled state rather than an immediate off indication.

## Detection

The integration preserves the app-recognized advertisement variant in the
config entry, chooses the verified FFF0 or BD39 characteristic pair, and then
uses the matching Hcalory command family. FFF0 alone is shared with other
heater families and is not sufficient evidence.
