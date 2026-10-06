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
| 33 | Set temperature | Controller target temperature |

The flag byte contains independent component activity: bit 0 or 1 for the
fuel pump, bit 2 for the fan, and bit 3 for the glow plug. Intake and outlet
values of `32760` mean that the controller does not support that probe; the
integration does not create an entity for an omitted probe.

## Commands

HeatGenie command packets use an `AA` envelope with a CRC16. The integration
uses the app-backed operations for automatic status updates, mode, power,
target temperature, target level, temperature unit, and time synchronization.
Unsupported generic commands fail rather than being translated to guessed
register writes.
