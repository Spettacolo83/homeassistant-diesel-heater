# Fuel estimates and their sources

Fuel quantities remain **estimates**, not measurements from a fuel-flow sensor.
No combustion, pump-calibration or tank settings are changed by this integration's
fuel accounting.

## Hcalory MVP3_3 session report

Hcalory 3.3.1 exposes Fuel Consumption only for MVP3_3 (`d8/u.S0` → `x8/c.q`).
Its fuel page sends `q2/h.h()`'s DPID14 read:
`0002000100010006140000010015`.

`q2/h.H` decodes a 24-bit big-endian session runtime in minutes, then a
16-bit whole-litre value plus an additional byte divided by 100. The report is
separate from normal DPID03 telemetry. The app explicitly describes it as a
pump-frequency-based estimate for the **current operating cycle**, reset after
shutdown, with no historical log.

After the first validated report establishes a baseline, the integration adds
positive changes to its daily, lifetime and since-refuel estimates. It preserves
that baseline and the corresponding totals together in storage. Duplicate and
regressive reports cannot subtract from totals or trigger fresh generic estimates.
Observed shutdowns permit session resets; reconnects/restarts with lower counters
establish a new baseline without inventing consumption during the missing period.
The first baseline does not add fuel from before observation began.

The optional read is serialized with Hcalory commands. A 1.5-second budget bounds
the entire transaction, including the GATT write; this is an integration transport
budget, not a claimed APK response deadline. Missing/invalid replies do not mark
otherwise-valid heater telemetry offline. Before a report has ever been confirmed,
the existing estimate remains available. After activation, report loss freezes
accumulated consumption until a subsequent counter arrives, avoiding double counts.

Refuelling/partial-refill operations attempt a read before moving the tank's
accounting boundary. If that read fails, lifetime/daily deltas are still retained,
but the next valid sample establishes a new tank boundary rather than assigning
unknown pre-refuel fuel to the refilled tank. This can omit fuel burned during that
uncertain interval from the remaining-fuel estimate. Lifetime fuel is not overwritten.

The **Estimated Hourly Fuel Consumption** entity remains the existing level-based
rate, not a noisy derivative of the controller's coarse session counter. Its
`estimate_basis` attribute identifies that distinction. The total-consumed entity
shows the session-derived basis, last session quantity/runtime and report availability.
Existing runtime entities retain their existing accounting; the controller's session
runtime is metadata, not a replacement lifetime counter.

The report has no session identifier or historical log. Whole sessions missed while
HA is disconnected, a final increment lost before controller reset, and the exact
allocation of a counter delta across midnight cannot be reconstructed. Deltas are
assigned to the day they are observed. No physical precision guarantee is implied.

## Other families

| Family | Available APK evidence and accounting |
|---|---|
| Other eight Hcalory MVP variants | The app does not expose the DPID14 fuel page for these variants. Keep the existing level estimate, including its existing temperature-mode level approximation. No new report requests are sent. |
| AA55/AA66 | AirHeaterBLE exposes level and some pump/tank configuration fields, but no equivalent consumption report or complete model-specific burn curve was identified. Retain the maintained level table; configuration indexes alone are not flow measurements. |
| ABBA/HeaterCC | AirHeaterCC/AirHeaterPro's status/control paths expose levels but no established session fuel total or pump-frequency conversion. Keep existing estimates. |
| CBFF/Sunster | `pump_model`/`oil_volume` are settings. No complete live pump-frequency-to-litres conversion is established by those fields alone. Keep existing estimates. |
| HeatGenie/Boygu | The APK defines `oilPumpFreq` and selectable 16ML/22ML/28ML pump labels. No complete litres-per-pulse calibration or fuel-total calculation was established in this trace. Do not silently infer a model-specific burn curve from these labels. Existing estimates remain unchanged. |
| Warm Drive | PR #170 already provides the separate pump-frequency correction and configured-displacement estimate. This work does not duplicate that PR; combined validation is required before merging the two implementations. |
| Legacy Neo | Keep existing estimates where already exposed. Do not apply Warm Drive's calibration to a controller identified only by shared GATT layout. |
| Webasto Cronus | Keep the explicit matching model profiles and ventilation-zero rule. No generic Hcalory session query or shared air-heater curve is added. |

These boundaries preserve existing support without presenting unsupported conversions
as measured telemetry. The shared table is an approximate maintained default, not a
claim that every heater brand/model burns the same amount.
