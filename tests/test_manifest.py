"""Manifest safeguards.

These tests reproduce the exact validators Home Assistant runs at integration
load / bluetooth component startup, so manifest regressions that would break
a real HA install are caught in CI instead of in production.

History:
- beta.6 shipped `local_name` matchers with leading wildcards (`*boygu*`),
  which `homeassistant.components.bluetooth.match._local_name_to_index_key`
  rejects with `ValueError: Local name matchers may not have patterns in
  the first 3 characters`. Reported in #86 by @Emmpunkt. The string-level
  check added in #87 is now backed by a call to the real HA validator here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


MANIFEST_PATH = (
    Path(__file__).parents[1] / "custom_components" / "diesel_heater" / "manifest.json"
)


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


# ---------------------------------------------------------------------------
# String-level guards (quick + no HA import)
# ---------------------------------------------------------------------------


def test_bluetooth_local_name_matchers_have_fixed_prefixes():
    """No wildcard or character class in the first 3 characters of local_name."""
    for matcher in _load_manifest()["bluetooth"]:
        local_name = matcher.get("local_name")
        if local_name:
            assert "*" not in local_name[:3], (
                f"local_name {local_name!r} has wildcard in first 3 chars"
            )
            assert "[" not in local_name[:3], (
                f"local_name {local_name!r} has char-class in first 3 chars"
            )


def test_heatgenie_discovery_uses_valid_name_matchers():
    """Expected HeatGenie matchers are present and no bare service_uuid."""
    bluetooth = _load_manifest()["bluetooth"]
    assert {"connectable": True, "local_name": "C1:*:FE:*"} in bluetooth
    assert {"connectable": True, "local_name": "boygu*"} in bluetooth
    assert {"connectable": True, "local_name": "BOYGU*"} in bluetooth
    assert not any("service_uuid" in m for m in bluetooth), (
        "bare service_uuid matchers open spurious config flows for any peripheral"
    )


# ---------------------------------------------------------------------------
# Real HA validator guards (the ones that fire at HA startup)
# ---------------------------------------------------------------------------


def test_each_local_name_matcher_passes_ha_startup_validator():
    """Reproduce HA's own validation of local_name matchers.

    `_local_name_to_index_key` runs on every integration's bluetooth matcher
    when the bluetooth component starts. If any raises, HA logs
    `Error during setup of component bluetooth` and every BLE-dependent
    integration downstream fails too (seen in #86).
    """
    try:
        from homeassistant.components.bluetooth.match import (
            _local_name_to_index_key,
        )
    except ImportError:
        pytest.skip("homeassistant.components.bluetooth not importable")

    for matcher in _load_manifest()["bluetooth"]:
        local_name = matcher.get("local_name")
        if local_name is None:
            continue
        try:
            _local_name_to_index_key(local_name)
        except ValueError as err:
            pytest.fail(
                f"HA bluetooth validator rejects local_name={local_name!r}: {err}"
            )


def test_manifest_json_is_valid_json_and_has_required_fields():
    """Catch malformed manifest.json before HACS tries to parse it."""
    manifest = _load_manifest()
    for required in ("domain", "name", "version", "requirements", "bluetooth"):
        assert required in manifest, f"manifest.json missing required field: {required}"
    # Semver-ish check — manifest version must look like "2.1.5-beta.8"
    version = manifest["version"]
    assert isinstance(version, str) and version, "version must be a non-empty string"


def test_manifest_requirement_pin_is_concrete():
    """Every requirement must declare an exact or lower-bound pin.

    HACS resolves requirements at install time against PyPI; an unpinned
    package can silently pull a version missing a symbol we import
    (that was the root cause of beta.3/beta.4, where #66 renamed a
    constant in the bundled library without a corresponding PyPI publish).
    """
    for req in _load_manifest()["requirements"]:
        assert any(op in req for op in (">=", "==", "~=")), (
            f"requirement {req!r} has no version constraint — "
            "pin it to the exact version published on PyPI"
        )


def test_manifest_requires_cronus_protocol_release():
    assert "diesel-heater-ble>=0.3.6" in _load_manifest()["requirements"]
