# Warm Drive Protocol

**Controller identity:** exact advertised name `Air Heater`
**Controller app evidence:** Warm Drive Android application, version `1.0.3`
**Known hardware:** MUDIRO M-5S / M-5S EVO-H controller

## Scope and identification

Warm Drive is a distinct controller family. It is not inferred from the shared
FFF0 service alone. The integration offers this path only when the controller
advertises the exact local name `Air Heater` and, after connecting, exposes:

| Direction | Characteristic |
| --- | --- |
| Write | `0000FFF1-0000-1000-8000-00805F9B34FB` |
| Notify | `0000FFF2-0000-1000-8000-00805F9B34FB` |

The 16-byte manufacturer record identifies the controller type: byte 4 value
`1` is an air controller; another value is a water controller. The app uses
the same distinction to choose its air or water interface.

## Controller code

Warm Drive uses a numeric controller code in its `5C` session exchange. The
factory/master value in the app is `100000000` (`05 F5 E1 00`). A controller
with a changed code requires that numeric code in the integration's PIN field.

The app does not derive the controller code from the Bluetooth MAC address. It
uses the MAC address only to identify the controller and store its locally saved
code.

## Frames

The app writes a `29 0D` envelope with a Modbus CRC16. The initial `5C`
request includes an adjusted Unix timestamp and the four-byte big-endian
numeric controller code.

| Exchange | Purpose |
| --- | --- |
| `5C 16` | Controller information, type, temperature range, and code |
| `29 0D FF` / `A5` | Initial run settings, including run type, target, and altitude |
| `5D` | Board information, including temperature and altitude units |
| `5A 25` | 39-byte live status frame |

Temperature values on the wire are Celsius. Warm Drive converts Celsius to
Fahrenheit only for display.

## Exposed telemetry

All verified Warm Drive controllers expose controller-reported Motor Speed and
Fire Temperature. Water controllers additionally expose Hot Water Temperature
and Water Temperature. The integration does not create CO, independent
pump/fan/glow state, timer, or time-sync entities for this family because the
Warm Drive app does not provide those capabilities through this protocol.

The status frame also contains controller state, supply voltage, current level,
target temperature, remaining fuel, altitude, and other transport fields used
by the established heater entities. Unsupported app fields are not presented
as separate Home Assistant controls.

## State meanings

The app maps the main controller states as follows:

| Value | Meaning |
| --- | --- |
| 0 | Shutdown |
| 1 | Self-check |
| 2-5 | Running |
| 6-8 | Cooldown |
| 160 | Standby |
| 170 | Cleaning |
| 171 | Ventilation |

A shutdown or cooldown state is not treated as an immediate electrical
power-off.

## Evidence boundary

The Warm Drive facts above are specific to the verified app/controller path.
They do not extend to an arbitrary device sharing FFF0, nor do they change the
separate DZ06 Neo controller support described in
[DZ06 Sunster Neo](../DZ06_SUNSTER_NEO.md).
