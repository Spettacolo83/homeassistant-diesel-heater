"""Cross-family discovery regressions for shared Bluetooth transports."""
from types import SimpleNamespace

import pytest

from custom_components.diesel_heater.config_flow import (
    _is_likely_heater,
    _warm_drive_controller_type,
)
from custom_components.diesel_heater.const import HCALORY_MVP1_SERVICE_UUID
from custom_components.diesel_heater.hcalory import (
    HcaloryVariant,
    hcalory_variant_from_discovery,
)


def test_abba_pin_mac_identity_does_not_select_hcalory():
    info = SimpleNamespace(
        name="Heater5593-EC:B1:D2:00:9C:F8",
        service_uuids=[HCALORY_MVP1_SERVICE_UUID],
        manufacturer_data={0xB1EC: bytes.fromhex("d2009cf8")},
    )
    assert _is_likely_heater(info)
    assert hcalory_variant_from_discovery(info) is None
    info.name = "Heater5593"
    assert hcalory_variant_from_discovery(info) is HcaloryVariant.MVP1


@pytest.mark.parametrize("device_type, expected", [(1, "air"), (2, "water")])
def test_warm_drive_record_excludes_company_identifier(device_type, expected):
    info = SimpleNamespace(
        name="Air Heater",
        manufacturer_data={0xFFFF: bytes((0, 0, device_type)) + bytes(11)},
    )
    assert _warm_drive_controller_type(info) == expected
    info.name = "Heater5816"
    assert _warm_drive_controller_type(info) is None
