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

For legacy ABBA commands on FFF2, a characteristic advertising only `write`
uses an acknowledged GATT write. Characteristics supporting
`write-without-response` retain that write type. The same rule applies to the
ABBA identification probe before protocol selection. A GATT acknowledgement
is not a heater status response; a parsed notification is still required.

AirHeaterCC's `utils/ecBLEApp.js` writes through the discovered FFF2
characteristic without forcing `writeNoResponse`. Its bundled Android
`BluetoothBaseAdapter.writeBLECharacteristicValue()` likewise preserves the
characteristic's native write type.

## Status fields

ABBA status frames begin with `AB BA 11 CC` and have at least 21 bytes.
AirHeaterCC handles `AB BA 24 EC` clock records and `AB BA 04 DC`
auto-start/stop configuration separately; they are not telemetry and must not
complete a pending status request. The fields used by the integration
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

## Target units and toggle controls

The `DB` target command is `BA AB 04 DB target 00 unit checksum`, where unit is
0 for Celsius and 1 for Fahrenheit. The received target is retained in that
native unit. Auto Start/Stop uses the app's `A6` toggle; Home Assistant checks
the current state before issuing a desired-state switch action.

## CY-5004 mode-change limitation

Live testing by stefanr09 in [issue #156](https://github.com/Spettacolo83/homeassistant-diesel-heater/issues/156#issuecomment-6586788001)
found that the CY-5004 controller used with AirHeaterCC accepts AC/AD mode changes
while Running, but ignores them in Standby and Cooldown. This is a reported
limitation of that controller; it is not imposed on every ABBA model.

Home Assistant confirms mode changes from the reported mode, rather than treating
any status reply as acceptance. If the requested mode is not confirmed, dependent
burn-off level/target writes are stopped. A mode request does not automatically
start the heater. The same hardware report confirms that DB temperature writes
work in both Level and Temperature modes; this does not change which temperature
controls the climate entity exposes.

## Shared FFF0 advertisement identity

The short six-byte `ECB…` manufacturer record is a legacy Hcalory MVP1 hint,
not a unique protocol identifier. The CY-5004 report in [issue #156](https://github.com/Spettacolo83/homeassistant-diesel-heater/issues/156#issuecomment-6607383808)
shows that excluding only the full `Heater<PIN>-<MAC>` name is insufficient.

For that legacy candidate on FFF0, the integration subscribes first and sends
AirHeaterCC's read-only `BA AB 04 CC 00 00 00` status request. A validated ABBA
status selects ABBA even when the advertised name is missing or different.
If no ABBA status arrives, the existing MVP1 query still has to return valid
status before setup completes. Versioned Hcalory advertisements and the dedicated
BD39 transport retain their existing authentication and query paths. No power
or mode command is used for identification.
