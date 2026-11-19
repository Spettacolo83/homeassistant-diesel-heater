# Fault codes and descriptions

Fault numbers are protocol-specific. The integration selects a fault table from
validated protocol/controller information; it does not apply AA55 descriptions
to every heater. Unknown descriptions remain unknown, and missing fault telemetry
is distinct from a reported fault. An unrecognized nonzero code still sets the
Problem sensor. Code and description formatting follows the relevant app.

| Controller | Fault decoding and description source |
|---|---|
| AA55, plain/encrypted | AirHeaterBLE 1.2.0 `errtext`: faults 1–10, CO warning 11, low battery 50 (Sunster). |
| AA66, plain/encrypted | AirHeaterBLE `errtext1`, distinct from AA55; newer Sunster family tags select JW descriptions when present. Sunster supplies low-battery/intake-sensor labels for slots 2/7 left blank in the older AirHeaterBLE app. |
| Motherboard version 6 | Sunster 2.2.000 `TWX-E-*` table, selected by decrypted byte 44. |
| ABBA/HeaterCC | AirHeaterCC and AirHeaterPro 1.1.4: mode byte 5 is FF, raw fault byte 6 selects E2–E10 and raw 11 selects the CO alarm (ECO). |
| CBFF/FEAA | Sunster 2.2.000: byte 15 contains the display code and family tag; byte 16 values 128/129/130 select XMZ/TY/JW and preserve the full display byte. Unknown families retain their code without another family's description. |
| Hcalory MVP variants | Hcalory 3.3.1 displays E-codes. MVP3_3 or manufacturer advertisement hex characters 12–15 equal to 05BD selects nibble formatting; otherwise the app's decimal formatting is used. No generic AA55 or unverified Hcalory descriptions are substituted. |
| HeatGenie/Boygu | HeatGenie 1.1.1 uses a 16-bit mask and the first active bit, E01–E16, with its English descriptions. |
| Warm Drive / legacy Neo | The respective Android app reads status byte 4, subtracting 1 only when greater than 1. Air-controller descriptions follow `WindMachineActivity`; water controllers retain the E-code because a separate water description table is not established by these APKs. |
| Webasto Cronus | ThermoConnect 3.4.0 exposes air/water interlock records. It is not assigned the generic Error/Problem entities or an invented E-code table. |

Sunster JW raw code 33 is displayed as E-00 (combustion sensor open circuit).
That display conversion does **not** clear the underlying nonzero fault.
Unknown telemetry does not imply either No fault or a positive reported fault.
An explicit Hcalory fault state with raw code zero displays E00 and still reports
a problem, matching the app's fault-state branch.

## APK evidence

- AirHeaterBLE 1.2.0 `app-service.js`: `errtext` / `errtext1`; md 3 and 4 use
  the alternate table; AA55 bytes 4, AA66 bytes 17/35.
- AirHeaterCC `app-service.js`: `faultCodeTable`, `checkFault`; AirHeaterPro
  1.1.4 independently uses the same raw byte and table indexing.
- Sunster 2.2.000 `app-service.js`: `fault_display`, `fault_code`, `faultType`,
  `errcodeEctype`; `E-*`, `X-E-*`, `JW-E-*`, `TWX-E-*` English localization.
- Hcalory 3.3.1 `r7/d.F` calls `q2/h.D` with the result of `w8/b.d`;
  `x8/c.j` identifies MVP3_3. The shared formatter covers MVP1, MVP2, MVP1_2,
  MVP1_3, MVP2_2, MVP2_3, MVP3, MVP3_2 and MVP3_3.
- Warm Drive 1.0.3 `BlueSearchActivity` / `WindMachineActivity`, and the
  equivalent classes in Sunster Neo: fault byte, adjustment, E-code and labels.
- ThermoConnect 3.4.0 `b9/m`, `b9/e`: interlock record catalog and decoding.
- [HeatGenie protocol reference](HEATGENIE.md#error-codes): mask priority and labels.

These are software mappings backed by the saved APKs. They do not establish a
fault meaning for an undocumented firmware variant or replace hardware testing.
