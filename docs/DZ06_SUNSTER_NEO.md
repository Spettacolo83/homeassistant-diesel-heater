# Experimental DZ06 / Sunster Neo support

This is experimental compatibility support for the existing Home Assistant Diesel Heater integration, maintained by the project owner (@Spettacolo83). It was tested on one combination only: a Sunster HTB1 heater with an A322 motherboard and DZ06/S-DZ06 controller, advertised as `Air Heater`.

## Verified transport and features

The tested device exposes service FFF0 with the split layout FFF1 write/write-without-response and FFF2 notify. This is the reverse direction of the legacy ABBA layout. The integration narrowly detects that property combination.

Verified features are native authorization, status reception, supply voltage, target temperature, cabin temperature, temperature setting, ON, and controlled OFF. The 39-byte `5A25` status frame is parsed only for those confirmed fields. Unknown fields and unknown state values are intentionally not interpreted.

Observed running states are 1, 2, 4, and 5. Observed shutdown/off states are 7, 8, and 0. A controlled shutdown was observed as `5 -> 7 -> 8 -> 0`; OFF is a normal cooldown request, not an electrical power cut.

## Limitations and authorization

Fuel level, case temperature, fan level, altitude, pump settings, timers, and other undocumented fields are not implemented for this transport. Generic legacy commands fail closed, and legacy time synchronization is skipped.

The current default connection password is `100000000` (`05 F5 E1 00`). The controller app exposes a device-password entry, so this value is configurable rather than a universal credential. The default successfully re-authorized the tested heater, but the implementation has only been validated on that one controller.

## Examples

```yaml
service: climate.set_temperature
target:
  entity_id: climate.diesel_heater
data:
  temperature: 30
```

Replace `climate.diesel_heater` with the climate entity for your heater. To turn it on:

```yaml
service: climate.turn_on
target:
  entity_id: climate.vevor_heater
```

To request controlled shutdown:

```yaml
service: climate.turn_off
target:
  entity_id: climate.vevor_heater
```

Allow the heater to complete its cooldown sequence.

## Troubleshooting

Enable debug logging for `custom_components.diesel_heater` and `diesel_heater_ble`. Confirm that the service is FFF0 and that FFF1 has a write property while FFF2 has notify. Do not include MAC addresses or raw device-specific captures in issue reports.
