# APK evidence for protocol repairs

The linked protocol documents describe the repaired behavior. The accompanying docs/apk-audit-repairs.md records the app source locators:

- AirHeaterCC app-service.js: setTemperature (17171) explicitly writes the DB unit byte; openOnAuto (17158) sends the A6 toggle.
- AirHeaterBLE 1.2.0 app-service.js: UnsignToSign(256*i[14]+i[13]) decodes signed whole degrees.
- Hcalory 3.3.1 q2/h.java: q() (953), signed-temperature decode (186-200); p2/e0.java: p() (239), k() (159), select transport-specific query/clock encoding.
- Sunster 2.2.000 app-service.js: altitude branch (pretty-source 30623) and protocol-version handling (30318) establish version-dependent scaling.
- HeatGenie 1.1.1 app-service.js: temperature display branches and 32760==o separate Celsius measurements from display preference and absent probes.
- Warm Drive 1.0.3 BlueSearchActivity.java: A5 (900-914) reads target byte 5; 5D (890-896) reads display-unit byte 17. DataConvertUtil.getT1 (152-167) applies integer Fahrenheit conversion.


APK evidence establishes wire behavior; Home Assistant lifecycle behavior is tested separately. Physical validation of every firmware is not claimed.
