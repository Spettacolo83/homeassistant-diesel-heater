# Webasto Cronus Protocol

**Integration mode:** 9
**Controller app evidence:** Webasto ThermoConnect application record protocol

## Transport and detection

ThermoConnect identifies Cronus controllers by a Cronus advertised name and
this proprietary characteristic pair:

| Direction | Characteristic UUID |
| --- | --- |
| Notify | `4229d528-33d0-4aa7-9af1-00b03fc128f9` |
| Write | `2ed964d9-1371-45ee-a84b-1d134d5ce7b7` |

Cronus is not selected from a generic service UUID. The integration verifies
the characteristic pair after connecting.

## Record protocol

Cronus has no single status frame. The integration reads ThermoConnect records
with `U` (`0x55`) and receives records with `V` (`0x56`); fragmented writes and
responses use `Q` (`0x51`) and `W` (`0x57`). Controller mode is determined
from the app available-controller record:

- **Air** controllers expose air level, Heating/Ventilation/Boost/Eco modes,
  and temperature setpoints for Heating, Boost, and Eco.
- **Water** controllers expose the same controller modes but do not expose an
  air level or air temperature setpoint.

The shared records provide interior, external, and coolant temperature, supply
voltage, current and maximum run duration, continuous-run state, and interlock
state. Air controllers additionally provide air pressure.

ThermoConnect exposes `state` and `state_real` records for controller state,
but does not provide a named AA-family running-step mapping. The integration
therefore does not label those values as generic running steps or infer
pump, fan, glow-plug, inlet-temperature, or outlet-temperature entities.

## Commands

Cronus writes controller records rather than accepting the generic AA command
table. The integration uses app-backed record writes for power, mode, air
level, and the applicable air setpoint. Unsupported generic commands fail
rather than being translated to guessed record writes.
