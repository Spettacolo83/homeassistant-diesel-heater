# AA55 Encrypted Protocol

**Integration mode:** 2
**Controller app evidence:** AirHeaterBLE encrypted parser and XOR routine

## Transport and encryption

Encrypted AA55 uses the AA-family FFE0/FFE1 transport and sends 48-byte status
notifications. Every byte is XORed with the repeating ASCII key `12345678`.
The integration decrypts the notification before checking its inner `AA 55`
header. Commands remain the normal unencrypted eight-byte AA55 packets.

## Decrypted status frame

| Offset | Field | Interpretation |
| --- | --- | --- |
| 0-1 | Header | `AA 55` after decryption |
| 3 | Running state | Controller state value |
| 4 | Error code | AA55 error position |
| 5 | Running step | Controller step value |
| 6-7 | Altitude | Big-endian unsigned value, divided by 10 |
| 8 | Running mode | Controller mode value |
| 9 | Target temperature | Controller value, clamped to supported Celsius range |
| 10 | Level | Controller value, clamped to 1-10 |
| 11-12 | Supply voltage | Big-endian unsigned value, divided by 10 |
| 13-14 | Case temperature | Big-endian signed 16-bit value |
| 19-20 | Device time | Big-endian minutes since midnight |
| 21-25 | Timer | Big-endian start and duration minutes, then enable flag |
| 32-33 | Cabin temperature | Big-endian signed value, divided by 10 |
| 34 | Heater offset | Signed 8-bit value |
| 36 | Backlight | Controller brightness value |
| 37-39 | CO | Presence flag and big-endian ppm value |
| 40-43 | Part number | Little-endian unsigned value rendered as hexadecimal |
| 44 | Motherboard version | Controller value |

## Commands and detection

AA55 encrypted controllers use the same command envelope documented in
[AA55](AA55.md). The integration selects this mode only when decrypting a
48-byte notification produces a valid `AA 55` status frame.
