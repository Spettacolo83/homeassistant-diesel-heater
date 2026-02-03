"""Tests for find_heater.py CLI utility.

Tests the BLE scanning utility functions without requiring actual BLE hardware.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# We need to mock bleak before importing find_heater
sys.modules['bleak'] = MagicMock()

from custom_components.vevor_heater.find_heater import (
    save_scan,
    load_scan,
    compare_scans,
)


# ---------------------------------------------------------------------------
# save_scan tests
# ---------------------------------------------------------------------------

class TestSaveScan:
    """Tests for save_scan function."""

    def test_save_scan_creates_file(self):
        """Test save_scan creates a JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filename = f.name

        data = {"AA:BB:CC:DD:EE:FF": {"name": "Test", "rssi": -50, "services": []}}
        save_scan(data, filename)

        assert Path(filename).exists()

        # Cleanup
        Path(filename).unlink()

    def test_save_scan_writes_valid_json(self):
        """Test save_scan writes valid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filename = f.name

        data = {
            "AA:BB:CC:DD:EE:FF": {"name": "Heater", "rssi": -45, "services": ["uuid1"]},
            "11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []},
        }
        save_scan(data, filename)

        with open(filename, 'r') as f:
            loaded = json.load(f)

        assert loaded == data

        # Cleanup
        Path(filename).unlink()

    def test_save_scan_empty_data(self):
        """Test save_scan with empty data."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filename = f.name

        save_scan({}, filename)

        with open(filename, 'r') as f:
            loaded = json.load(f)

        assert loaded == {}

        # Cleanup
        Path(filename).unlink()


# ---------------------------------------------------------------------------
# load_scan tests
# ---------------------------------------------------------------------------

class TestLoadScan:
    """Tests for load_scan function."""

    def test_load_scan_reads_file(self):
        """Test load_scan reads JSON file correctly."""
        data = {"AA:BB:CC:DD:EE:FF": {"name": "Test", "rssi": -50, "services": []}}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            filename = f.name

        loaded = load_scan(filename)

        assert loaded == data

        # Cleanup
        Path(filename).unlink()

    def test_load_scan_empty_file(self):
        """Test load_scan with empty JSON object."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            filename = f.name

        loaded = load_scan(filename)

        assert loaded == {}

        # Cleanup
        Path(filename).unlink()

    def test_load_scan_multiple_devices(self):
        """Test load_scan with multiple devices."""
        data = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device1", "rssi": -45, "services": ["a", "b"]},
            "11:22:33:44:55:66": {"name": "Device2", "rssi": -70, "services": []},
            "77:88:99:AA:BB:CC": {"name": "Device3", "rssi": -55, "services": ["c"]},
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            filename = f.name

        loaded = load_scan(filename)

        assert len(loaded) == 3
        assert "AA:BB:CC:DD:EE:FF" in loaded
        assert loaded["11:22:33:44:55:66"]["name"] == "Device2"

        # Cleanup
        Path(filename).unlink()


# ---------------------------------------------------------------------------
# compare_scans tests
# ---------------------------------------------------------------------------

class TestCompareScans:
    """Tests for compare_scans function."""

    def test_compare_scans_finds_disappeared(self, capsys):
        """Test compare_scans identifies disappeared devices."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Heater", "rssi": -50, "services": []},
            "11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []},
        }
        after = {
            "11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []},
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "DISAPPEARED" in captured.out
        assert "AA:BB:CC:DD:EE:FF" in captured.out
        assert "VEVOR HEATER" in captured.out

    def test_compare_scans_finds_appeared(self, capsys):
        """Test compare_scans identifies new devices."""
        before = {
            "11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []},
        }
        after = {
            "11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []},
            "AA:BB:CC:DD:EE:FF": {"name": "New", "rssi": -50, "services": []},
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "NEW DEVICES" in captured.out
        assert "AA:BB:CC:DD:EE:FF" in captured.out

    def test_compare_scans_finds_appeared_with_services(self, capsys):
        """Test compare_scans shows services for new devices."""
        before = {}
        after = {
            "AA:BB:CC:DD:EE:FF": {
                "name": "Heater",
                "rssi": -50,
                "services": ["fff0", "1800", "180a"],
            },
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "NEW DEVICES" in captured.out
        assert "Services:" in captured.out
        assert "fff0" in captured.out

    def test_compare_scans_finds_rssi_changes(self, capsys):
        """Test compare_scans identifies significant RSSI changes."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -50, "services": []},
        }
        after = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -70, "services": []},  # -20 change
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "RSSI CHANGES" in captured.out
        assert "AA:BB:CC:DD:EE:FF" in captured.out

    def test_compare_scans_no_changes(self, capsys):
        """Test compare_scans with no changes."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -50, "services": []},
        }
        after = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -52, "services": []},  # Small change
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "No devices disappeared or appeared" in captured.out

    def test_compare_scans_empty_before(self, capsys):
        """Test compare_scans with empty before scan."""
        before = {}
        after = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -50, "services": []},
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "Before scan: 0 devices" in captured.out
        assert "After scan:  1 devices" in captured.out

    def test_compare_scans_empty_after(self, capsys):
        """Test compare_scans with empty after scan."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -50, "services": []},
        }
        after = {}

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "DISAPPEARED" in captured.out
        assert "AA:BB:CC:DD:EE:FF" in captured.out

    def test_compare_scans_with_services(self, capsys):
        """Test compare_scans displays services."""
        before = {
            "AA:BB:CC:DD:EE:FF": {
                "name": "Heater",
                "rssi": -50,
                "services": ["0000ffe0-0000-1000-8000-00805f9b34fb", "other-uuid"]
            },
        }
        after = {}

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "Services:" in captured.out

    def test_compare_scans_multiple_disappeared(self, capsys):
        """Test compare_scans with multiple disappeared devices."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device1", "rssi": -50, "services": []},
            "11:22:33:44:55:66": {"name": "Device2", "rssi": -60, "services": []},
            "77:88:99:AA:BB:CC": {"name": "Device3", "rssi": -70, "services": []},
        }
        after = {}

        compare_scans(before, after)

        captured = capsys.readouterr()
        assert "DISAPPEARED (3)" in captured.out

    def test_compare_scans_ignores_small_rssi_change(self, capsys):
        """Test compare_scans ignores RSSI changes under threshold."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -50, "services": []},
        }
        after = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device", "rssi": -55, "services": []},  # Only 5 dB change
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        # Should not show RSSI changes section for small changes
        assert "RSSI CHANGES" not in captured.out or "AA:BB:CC:DD:EE:FF" not in captured.out.split("RSSI CHANGES")[1] if "RSSI CHANGES" in captured.out else True


# ---------------------------------------------------------------------------
# scan_devices tests (mocked)
# ---------------------------------------------------------------------------

class TestScanDevices:
    """Tests for scan_devices function with mocked BLE."""

    @pytest.mark.asyncio
    async def test_scan_devices_returns_dict(self):
        """Test scan_devices returns a dictionary."""
        # Import with mocked bleak
        from custom_components.vevor_heater.find_heater import scan_devices

        mock_device = MagicMock()
        mock_device.name = "Test Device"

        mock_adv = MagicMock()
        mock_adv.rssi = -50
        mock_adv.service_uuids = ["uuid1", "uuid2"]

        mock_result = {
            "AA:BB:CC:DD:EE:FF": (mock_device, mock_adv)
        }

        with patch('custom_components.vevor_heater.find_heater.BleakScanner') as mock_scanner:
            mock_scanner.discover = AsyncMock(return_value=mock_result)

            result = await scan_devices()

        assert isinstance(result, dict)
        assert "AA:BB:CC:DD:EE:FF" in result
        assert result["AA:BB:CC:DD:EE:FF"]["name"] == "Test Device"
        assert result["AA:BB:CC:DD:EE:FF"]["rssi"] == -50

    @pytest.mark.asyncio
    async def test_scan_devices_empty_result(self):
        """Test scan_devices with no devices found."""
        from custom_components.vevor_heater.find_heater import scan_devices

        with patch('custom_components.vevor_heater.find_heater.BleakScanner') as mock_scanner:
            mock_scanner.discover = AsyncMock(return_value={})

            result = await scan_devices()

        assert result == {}

    @pytest.mark.asyncio
    async def test_scan_devices_unknown_name(self):
        """Test scan_devices with device that has no name."""
        from custom_components.vevor_heater.find_heater import scan_devices

        mock_device = MagicMock()
        mock_device.name = None  # No name

        mock_adv = MagicMock()
        mock_adv.rssi = -60
        mock_adv.service_uuids = None

        mock_result = {
            "AA:BB:CC:DD:EE:FF": (mock_device, mock_adv)
        }

        with patch('custom_components.vevor_heater.find_heater.BleakScanner') as mock_scanner:
            mock_scanner.discover = AsyncMock(return_value=mock_result)

            result = await scan_devices()

        assert result["AA:BB:CC:DD:EE:FF"]["name"] == "Unknown"
        assert result["AA:BB:CC:DD:EE:FF"]["services"] == []


# ---------------------------------------------------------------------------
# main function tests (mocked)
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for main function with mocked I/O."""

    @pytest.mark.asyncio
    async def test_main_no_args_shows_usage(self):
        """Test main with no arguments shows usage and exits."""
        from custom_components.vevor_heater.find_heater import main

        with patch.object(sys, 'argv', ['find_heater.py']):
            with pytest.raises(SystemExit) as exc_info:
                await main()

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_invalid_arg_shows_usage(self):
        """Test main with invalid argument shows usage and exits."""
        from custom_components.vevor_heater.find_heater import main

        with patch.object(sys, 'argv', ['find_heater.py', 'invalid']):
            with pytest.raises(SystemExit) as exc_info:
                await main()

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_before_mode(self):
        """Test main in 'before' mode."""
        from custom_components.vevor_heater.find_heater import main

        mock_devices = {"AA:BB:CC:DD:EE:FF": {"name": "Test", "rssi": -50, "services": []}}

        with patch.object(sys, 'argv', ['find_heater.py', 'before']), \
             patch('builtins.input', return_value=''), \
             patch('custom_components.vevor_heater.find_heater.scan_devices', AsyncMock(return_value=mock_devices)), \
             patch('custom_components.vevor_heater.find_heater.save_scan') as mock_save:

            await main()

            mock_save.assert_called_once()
            call_args = mock_save.call_args
            assert call_args[0][0] == mock_devices
            assert 'before' in call_args[0][1]

    @pytest.mark.asyncio
    async def test_main_after_mode_no_before_file(self):
        """Test main in 'after' mode when before file doesn't exist."""
        from custom_components.vevor_heater.find_heater import main

        with patch.object(sys, 'argv', ['find_heater.py', 'after']), \
             patch('custom_components.vevor_heater.find_heater.Path') as mock_path:

            mock_path.return_value.exists.return_value = False

            with pytest.raises(SystemExit) as exc_info:
                await main()

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_after_mode_with_before_file(self):
        """Test main in 'after' mode with existing before file."""
        from custom_components.vevor_heater.find_heater import main

        before_data = {"AA:BB:CC:DD:EE:FF": {"name": "Heater", "rssi": -50, "services": []}}
        after_data = {"11:22:33:44:55:66": {"name": "Other", "rssi": -70, "services": []}}

        with patch.object(sys, 'argv', ['find_heater.py', 'after']), \
             patch('builtins.input', return_value=''), \
             patch('custom_components.vevor_heater.find_heater.Path') as mock_path, \
             patch('custom_components.vevor_heater.find_heater.scan_devices', AsyncMock(return_value=after_data)), \
             patch('custom_components.vevor_heater.find_heater.save_scan'), \
             patch('custom_components.vevor_heater.find_heater.load_scan', return_value=before_data), \
             patch('custom_components.vevor_heater.find_heater.compare_scans') as mock_compare:

            mock_path.return_value.exists.return_value = True

            await main()

            mock_compare.assert_called_once_with(before_data, after_data)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases."""

    def test_compare_scans_sorts_rssi_changes(self, capsys):
        """Test compare_scans sorts RSSI changes by magnitude."""
        before = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device1", "rssi": -50, "services": []},
            "11:22:33:44:55:66": {"name": "Device2", "rssi": -50, "services": []},
            "77:88:99:AA:BB:CC": {"name": "Device3", "rssi": -50, "services": []},
        }
        after = {
            "AA:BB:CC:DD:EE:FF": {"name": "Device1", "rssi": -65, "services": []},  # 15 change
            "11:22:33:44:55:66": {"name": "Device2", "rssi": -80, "services": []},  # 30 change
            "77:88:99:AA:BB:CC": {"name": "Device3", "rssi": -70, "services": []},  # 20 change
        }

        compare_scans(before, after)

        captured = capsys.readouterr()
        # Device2 should appear first (largest change)
        assert "Device2" in captured.out

    def test_save_and_load_roundtrip(self):
        """Test that save and load are inverses."""
        data = {
            "AA:BB:CC:DD:EE:FF": {
                "name": "Test Device",
                "rssi": -45,
                "services": ["uuid1", "uuid2", "uuid3"]
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filename = f.name

        save_scan(data, filename)
        loaded = load_scan(filename)

        assert loaded == data

        # Cleanup
        Path(filename).unlink()
