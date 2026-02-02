"""Shared test fixtures for Vevor Heater tests.

For pure-Python tests (protocol, helpers) we stub out the homeassistant
package so that ``custom_components.vevor_heater`` can be imported without
having Home Assistant installed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


class _HAStubFinder:
    """Meta-path finder that intercepts homeassistant.* and bleak* imports.

    Returns a fresh MagicMock-based module for any submodule, so that
    ``from homeassistant.components.recorder import get_instance`` works
    without the real HA package installed.
    """

    _PREFIXES = ("homeassistant", "bleak", "bleak_retry_connector")

    def find_module(self, fullname, path=None):
        for prefix in self._PREFIXES:
            if fullname == prefix or fullname.startswith(prefix + "."):
                return self
        return None

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        mod = types.ModuleType(fullname)
        mod.__path__ = []          # make it a package
        mod.__loader__ = self
        mod.__spec__ = None
        # Attribute access returns MagicMock so `from x import y` works
        mod.__getattr__ = lambda name: MagicMock()
        sys.modules[fullname] = mod
        return mod


# Install the finder BEFORE any test import
sys.meta_path.insert(0, _HAStubFinder())

# Ensure custom_components is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Config flow stubs
# ---------------------------------------------------------------------------
# Provide real base classes so that
#   class Foo(config_entries.ConfigFlow, domain=DOMAIN): ...
# produces a proper class (not a MagicMock).

class _AbortFlow(Exception):
    """Stub for homeassistant.data_entry_flow.AbortFlow."""

    def __init__(self, reason="", description_placeholders=None):
        self.reason = reason
        self.description_placeholders = description_placeholders or {}
        super().__init__(reason)


class _StubConfigFlow:
    """Stub for homeassistant.config_entries.ConfigFlow.

    Tests can set ``_existing_unique_ids`` (set) to make
    ``_abort_if_unique_id_configured()`` raise AbortFlow.
    Tests can set ``_current_ids`` (set) to control ``_async_current_ids()``.
    """

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if domain:
            cls.domain = domain

    async def async_set_unique_id(self, unique_id: str):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        existing = getattr(self, "_existing_unique_ids", set())
        if getattr(self, "_unique_id", None) in existing:
            raise _AbortFlow("already_configured")

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self, *, step_id, data_schema=None, errors=None, description_placeholders=None
    ):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders or {},
        }

    def async_abort(self, *, reason, description_placeholders=None):
        return {"type": "abort", "reason": reason}

    def _set_confirm_only(self):
        pass

    def _async_current_ids(self):
        return getattr(self, "_current_ids", set())

    @property
    def hass(self):
        # Lazy init: subclass __init__ may not call super().__init__()
        if not hasattr(self, "_hass"):
            self._hass = MagicMock()
        return self._hass

    @hass.setter
    def hass(self, value):
        self._hass = value


class _StubOptionsFlow:
    """Stub for homeassistant.config_entries.OptionsFlow."""

    def __init__(self):
        self._hass = MagicMock()
        self._config_entry = None

    @property
    def config_entry(self):
        return self._config_entry

    @config_entry.setter
    def config_entry(self, value):
        self._config_entry = value

    @property
    def hass(self):
        return self._hass

    @hass.setter
    def hass(self, value):
        self._hass = value

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(
        self, *, step_id, data_schema=None, errors=None, description_placeholders=None
    ):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders or {},
        }


class _StubConfigEntry:
    """Stub for homeassistant.config_entries.ConfigEntry."""

    def __init__(self, *, domain="", data=None, options=None, unique_id=None, entry_id="test"):
        self.domain = domain
        self.data = data or {}
        self.options = options or {}
        self.unique_id = unique_id
        self.entry_id = entry_id
        self.runtime_data = None

    def __class_getitem__(cls, item):
        """Support ConfigEntry[T] syntax for type aliases."""
        return cls


# ---------------------------------------------------------------------------
# Inject stubs into the HA stub modules
# ---------------------------------------------------------------------------
# Force-create the modules via our finder, then override specific attributes
# with real classes.  This must happen BEFORE any test imports config_flow.py.

import homeassistant.config_entries  # noqa: E402
import homeassistant.data_entry_flow  # noqa: E402
import homeassistant.const  # noqa: E402

sys.modules["homeassistant.config_entries"].ConfigFlow = _StubConfigFlow
sys.modules["homeassistant.config_entries"].OptionsFlow = _StubOptionsFlow
sys.modules["homeassistant.config_entries"].ConfigEntry = _StubConfigEntry

sys.modules["homeassistant.data_entry_flow"].AbortFlow = _AbortFlow
sys.modules["homeassistant.data_entry_flow"].FlowResult = dict

sys.modules["homeassistant.const"].CONF_ADDRESS = "address"
