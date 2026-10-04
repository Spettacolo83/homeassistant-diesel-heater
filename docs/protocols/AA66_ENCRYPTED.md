# AA66 Encrypted Protocol

**Integration mode:** 4
**Controller app evidence:** AirHeaterBLE encrypted parser and XOR routine

## Transport and encryption

Encrypted AA66 uses the AA-family FFE0/FFE1 transport and sends 48-byte status
notifications. Every byte is XORed with the repeating ASCII key `12345678`.
The integration decrypts before checking its inner `AA 66` header. Commands
remain the normal unencrypted eight-byte AA55 packets.

## Decrypted status frame

| Offset | Field | Interpretation |
| --- | --- | --- |
| 0-1 | Header | `AA 66` after decryption |
| 3 | Running state | Controller state value |
| 5 | Running step | Controller step value |
| 6-7 | Altitude | Big-endian unsigned value, divided by 10 |
| 8 | Running mode | Controller mode value |
| 9 | Target temperature | Converted from Fahrenheit when the effective unit is Fahrenheit |
| 10 | Level | Controller value, clamped to 1-10 |
| 11-12 | Supply voltage | Big-endian unsigned value, divided by 10 |
| 13-14 | Case temperature | Big-endian signed 16-bit value |
| 19-20 | Device time | Big-endian minutes since midnight |
| 21-25 | Timer | Big-endian start and duration minutes, then enable flag |
| 26 | Language | Controller value |
| 27 | Temperature unit | `0` Celsius, `1` Fahrenheit |
| 28 | Tank volume | Controller value |
| 29 | Pump type / RF433 | `20` RF433 off, `21` RF433 on, otherwise pump type |
| 30 | Altitude unit | Controller value |
| 31 | Automatic start/stop | `1` enabled |
| 32-33 | Cabin temperature | Big-endian signed value, divided by 10 |
| 34 | Heater offset | Signed 8-bit value |
| 35 | Error code | AA66 encrypted error position |
| 36 | Backlight | Controller brightness value |
| 37-39 | CO | Presence flag and big-endian ppm value |
| 40-43 | Part number | Little-endian unsigned value rendered as hexadecimal |
| 44 | Motherboard version | Controller value |

Some faulty controllers report the temperature-unit byte incorrectly. The
integration's Force Celsius / Force Fahrenheit option is deliberately applied
before parsing byte 9, so the target-temperature conversion uses the selected
unit at the protocol boundary.

## Commands and detection

AA66 encrypted controllers use the AA-family command envelope in
[AA55](AA55.md). The integration selects this mode only when decrypting a
48-byte notification produces a valid `AA 66` status frame.
