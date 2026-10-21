"""Hcalory controller identification from the Air Heater app advertisement format."""
from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from .const import HCALORY_MVP1_SERVICE_UUID, HCALORY_MVP2_SERVICE_UUID


class HcaloryVariant(StrEnum):
    """Controller variants identified by the Hcalory Android app."""

    MVP1 = "mvp1"
    MVP2 = "mvp2"
    MVP1_2 = "mvp1_2"
    MVP1_3 = "mvp1_3"
    MVP2_2 = "mvp2_2"
    MVP2_3 = "mvp2_3"
    MVP3 = "mvp3"
    MVP3_2 = "mvp3_2"
    MVP3_3 = "mvp3_3"


_VERSION_PREFIXES: dict[bytes, HcaloryVariant] = {
    b"\x01\x02": HcaloryVariant.MVP1_2,
    b"\x01\x03": HcaloryVariant.MVP1_3,
    b"\x02\x02": HcaloryVariant.MVP2_2,
    b"\x02\x03": HcaloryVariant.MVP2_3,
    b"\x03\x01": HcaloryVariant.MVP3,
    b"\x03\x02": HcaloryVariant.MVP3_2,
    b"\x03\x03": HcaloryVariant.MVP3_3,
}


def classify_hcalory_manufacturer_data(
    manufacturer_data: Mapping[int, bytes],
) -> HcaloryVariant | None:
    """Classify manufacturer data exactly as the Hcalory Android app does."""
    raw = b"".join(
        company_id.to_bytes(2, byteorder="little") + bytes(payload)
        for company_id, payload in sorted(manufacturer_data.items())
    )

    # The legacy MVP1 branch is the app's short "ECB..." record.
    if len(raw) == 6 and raw.hex().upper().startswith("ECB"):
        return HcaloryVariant.MVP1

    # All remaining app-recognized records are 16 bytes long.
    if len(raw) != 16:
        return None

    version = raw[2:5]
    if version == b"\x06\xbd\x01":
        return HcaloryVariant.MVP2
    return _VERSION_PREFIXES.get(version[:2])


def hcalory_variant_from_discovery(
    discovery_info: BluetoothServiceInfoBleak,
) -> HcaloryVariant | None:
    """Return an app-recognized Hcalory variant only on an Hcalory GATT transport."""
    service_uuids = {uuid.lower() for uuid in discovery_info.service_uuids}
    if not service_uuids.intersection(
        {HCALORY_MVP1_SERVICE_UUID, HCALORY_MVP2_SERVICE_UUID}
    ):
        return None
    return classify_hcalory_manufacturer_data(discovery_info.manufacturer_data)


def uses_mvp2_commands(variant: HcaloryVariant) -> bool:
    """Return whether the app uses the authenticated 0A0A command family."""
    return variant is not HcaloryVariant.MVP1
