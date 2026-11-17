# HeatGenie / Boygu Protocol

**Integration mode:** 8
**Controller app evidence:** Heat Genie application register protocol

## Transport and detection

HeatGenie/Boygu controllers use the Environmental Sensing service
`0000181a-0000-1000-8000-00805f9b34fb`. The integration requires a
HeatGenie-recognized advertised identity, one notify or indicate characteristic,
one write characteristic, and a valid status report. The service UUID alone is
not enough to identify a controller.

## Status report

The automatic register report begins with `AA`, has status type `F2` at byte
7, contains 40 register bytes from offset 8, and has a valid CRC16. The
integration reads:

| Register bytes | Field | Interpretation |
| --- | --- | --- |
| 0 | State | Controller running state and step |
| 1 | Flags | Temperature unit, mode, and component state bits |
| 2-3 | Supply voltage | Little-endian value, divided by 10 |
| 4-5 | Altitude | Little-endian unsigned value |
| 6-7 | Cabin temperature | Little-endian signed value, divided by 10 |
| 8-9 | Case temperature | Little-endian signed value, divided by 10 |
| 16-17 | Intake temperature | Little-endian signed value, divided by 10 when supported |
| 18-19 | Outlet temperature | Little-endian signed value, divided by 10 when supported |
| 20-21 | Error flags | Lowest set bit is the current error |
| 32 | Set level | Controller level |
| 33 | Set temperature | Target in the display-selected unit; normalized to Celsius in HA |

The flag byte contains independent component activity: bit 0 or 1 for the
fuel pump, bit 2 for the fan, and bit 3 for the glow plug. Intake and outlet
values of `32760` mean that the controller does not support that probe; the
integration does not create an entity for an unsupported probe. A later unsupported marker clears the previous reading rather than retaining stale telemetry.

## Commands

HeatGenie command packets use an `AA` envelope with a CRC16. The integration
uses the app-backed operations for automatic status updates, mode, power,
target temperature, target level, temperature unit, and time synchronization.
Unsupported generic commands fail rather than being translated to guessed
register writes.

Measured cabin, case, intake, and outlet values are native Celsius tenths. The
Fahrenheit bit selects the controller/app display and target command encoding;
it does not change the measured wire values into Fahrenheit. HA keeps measured
values and its target in Celsius and converts only the outgoing target when
that display bit is set.


## Error codes

Registers 20–21 contain a 16-bit little-endian fault mask. The parser retains
its existing lowest-set-bit priority. The Error sensor maps that bit to the
app's displayed E-code: `0x0001` → E01, `0x0080` → E08, through `0x8000` → E16.
Zero means No fault. AA55 and Warm Drive fault tables are not used for HeatGenie.

APK evidence: HeatGenie 1.1.1 (`uni.UNIC97AE27`, versionCode 111), bundled
`app-service.js`: `regInfoAreaArray` defines `errorCode` at offset 20 with size 2;
the error display tests the bits in ascending order and selects
`device.error-E-01` through `device.error-E-16`. `showErrorToast` explicitly maps
128 to `device.error-E-08-info` and continues through 32768/E16.

Fault descriptions follow the APK's English `device.error-E-01` through
`device.error-E-16` strings. For example, `0x0080` displays
`E08 - Flame extinction fault`. The app labels E05 as machine overheating and
E12 as overtemperature. The reporter in issue #171 confirmed that the controller
displays E08 only; the initial overheat description came from an LLM rather
than the controller or manual. Descriptions therefore follow the APK rather
than another protocol's fault table. Error flags, parser priority and fault detection
are unchanged.
