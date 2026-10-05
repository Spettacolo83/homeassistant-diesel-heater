# Diesel Heater BLE Protocol Reference

This reference records the protocol facts used by the integration. A BLE
service UUID is transport evidence, not enough to identify a heater protocol:
shared UUIDs require the characteristic directions and a valid status frame.

## Supported protocol modes

| Mode | Protocol | Status / command identifiers | Reference |
| --- | --- | --- | --- |
| 1 | AA55 | `AA 55` status and commands | [AA55](AA55.md) |
| 2 | AA55 encrypted | Decrypted `AA 55` status | [AA55 encrypted](AA55_ENCRYPTED.md) |
| 3 | AA66 | `AA 66` status, `AA 55` commands | [AA66](AA66.md) |
| 4 | AA66 encrypted | Decrypted `AA 66` status | [AA66 encrypted](AA66_ENCRYPTED.md) |
| 5 | ABBA / HeaterCC | `AB BA` status, `BA AB` commands | [ABBA](ABBA.md) |
| 6 | CBFF / Sunster V2.1 | `CB FF` status, `FE AA` commands | [CBFF](CBFF.md) |
| 7 | Hcalory MVP1/MVP2 | Hcalory envelope and status layout | [Hcalory](HCALORY.md) |
| 8 | HeatGenie / Boygu | `AA` register report with `F2` status type | [HeatGenie](HEATGENIE.md) |
| 9 | Webasto Cronus | ThermoConnect record protocol | [Cronus](CRONUS.md) |

The experimental DZ06 Neo controller is documented separately in
[DZ06 Sunster Neo](../DZ06_SUNSTER_NEO.md). It is a single verified controller,
not a claim about every FFF0 device.

## Transport is not discovery

| Family | Service | Characteristic evidence |
| --- | --- | --- |
| AA55 / AA66 | FFE0 | FFE1 read/write/notify; frame selects AA55 or AA66 |
| ABBA legacy | FFF0 | FFF1 notify and FFF2 write; `AB BA` status validates the protocol |
| CBFF / Sunster V2.1 | FFF0 | Verified session plus CBFF/FEAA protocol; `AA77` starts encrypted V2.1 handling |
| Hcalory MVP1 | FFF0 | FFF2 write and FFF1 notify, then Hcalory packet validation |
| Hcalory MVP2 | BD39 | BDF7 write and BDF8 notify, then Hcalory packet validation |
| HeatGenie / Boygu | 181A | One notify/indicate and one write characteristic, plus supported name identity and a valid `F2` report |
| Webasto Cronus | Proprietary | `4229d528-33d0-4aa7-9af1-00b03fc128f9` notify and `2ed964d9-1371-45ee-a84b-1d134d5ce7b7` write, plus a Cronus name |

The integration uses known advertised-name patterns only to decide whether to
offer a discovery flow. It confirms the protocol after connecting; an arbitrary
BLE peripheral with a shared FFF0 or FFE0 service must not become a heater.

## AA-family command rule

AA55, AA55 encrypted, AA66, and AA66 encrypted share the eight-byte command
shape below. Their response headers and field positions are different.

```text
AA 55 PIN_HI PIN_LO COMMAND ARG_LO ARG_HI CHECKSUM
```

For encrypted AA-family traffic, the integration decrypts the complete
48-byte notification before examining its inner `AA55` or `AA66` status
header. A visible raw header is therefore not required.

## Evidence standard

Field offsets, command bytes, state meanings, and transports in these pages are
grounded in the supported controller applications and validated integration
protocol paths. A value observed only for one controller is labelled as such;
it is not promoted to a universal rule for another protocol family.
