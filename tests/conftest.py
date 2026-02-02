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
