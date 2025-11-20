#!/usr/bin/env python3
"""
Find your Vevor Diesel Heater's MAC address

This script helps you discover your heater's Bluetooth MAC address by comparing
BLE scans before and after connecting with the Vevor app. The device that
disappears when the app connects is your heater!

Usage:
  1. python3 find_heater.py before    # Scan with app CLOSED
  2. Open Vevor app and connect to heater
  3. python3 find_heater.py after     # Scan with app CONNECTED

Requirements:
  pip install bleak
"""
import asyncio
import sys
import json
from pathlib import Path

try:
    from bleak import BleakScanner
except ImportError:
    print("ERROR: bleak not installed")
    sys.exit(1)


async def scan_devices():
    """Scan for all BLE devices."""
    print("🔍 Scanning for 20 seconds...\n")
    devices = await BleakScanner.discover(timeout=20.0, return_adv=True)

    result = {}
    for address, (device, adv_data) in devices.items():
        result[address] = {
            "name": device.name or "Unknown",
            "rssi": adv_data.rssi,
            "services": list(adv_data.service_uuids) if adv_data.service_uuids else [],
        }

    return result


def save_scan(data: dict, filename: str):
    """Save scan results to file."""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"✓ Saved to {filename}")


def load_scan(filename: str):
    """Load scan results from file."""
    with open(filename, 'r') as f:
        return json.load(f)


def compare_scans(before: dict, after: dict):
    """Compare two scans and find differences."""
    print("\n" + "="*70)
    print("  SCAN COMPARISON")
    print("="*70)

    before_addrs = set(before.keys())
    after_addrs = set(after.keys())

    # Devices that disappeared (likely connected)
    disappeared = before_addrs - after_addrs

    # Devices that appeared
    appeared = after_addrs - before_addrs

    # Devices with changed RSSI (activity change)
    changed = {}
    for addr in before_addrs & after_addrs:
        rssi_before = before[addr]["rssi"]
        rssi_after = after[addr]["rssi"]
        rssi_diff = abs(rssi_after - rssi_before)

        if rssi_diff > 10:  # Significant change
            changed[addr] = {
                "name": after[addr]["name"],
                "rssi_before": rssi_before,
                "rssi_after": rssi_after,
                "diff": rssi_diff
            }

    print(f"\n📊 Before scan: {len(before)} devices")
    print(f"📊 After scan:  {len(after)} devices")

    if disappeared:
        print(f"\n🎯 DEVICES THAT DISAPPEARED ({len(disappeared)}):")
        print("(These are likely CONNECTED to something)")
        for addr in disappeared:
            info = before[addr]
            print(f"\n  {addr}")
            print(f"    Name: {info['name']}")
            print(f"    RSSI: {info['rssi']}")
            if info['services']:
                print(f"    Services: {', '.join(info['services'][:3])}")
            print(f"    ⭐ THIS COULD BE YOUR VEVOR HEATER!")

    if appeared:
        print(f"\n📱 NEW DEVICES ({len(appeared)}):")
        for addr in appeared:
            info = after[addr]
            print(f"\n  {addr}")
            print(f"    Name: {info['name']}")
            print(f"    RSSI: {info['rssi']}")
            if info['services']:
                print(f"    Services: {', '.join(info['services'][:3])}")

    if changed:
        print(f"\n📶 DEVICES WITH RSSI CHANGES ({len(changed)}):")
        sorted_changed = sorted(changed.items(), key=lambda x: x[1]['diff'], reverse=True)
        for addr, info in sorted_changed[:5]:
            print(f"\n  {addr}")
            print(f"    Name: {info['name']}")
            print(f"    RSSI: {info['rssi_before']} → {info['rssi_after']} (Δ{info['diff']})")

    if not disappeared and not appeared:
        print("\n⚠️  No devices disappeared or appeared!")
        print("\nPossible reasons:")
        print("  • Heater was already connected before 'before' scan")
        print("  • App didn't actually connect")
        print("  • Heater uses same MAC for advertising and connection")

    print("\n" + "="*70)


async def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ['before', 'after']:
        print("Usage:")
        print("  Step 1: python3 find_heater.py before")
        print("  Step 2: Start Vevor app and CONNECT to heater")
        print("  Step 3: python3 find_heater.py after")
        sys.exit(1)

    mode = sys.argv[1]
    before_file = "/tmp/ble_scan_before.json"
    after_file = "/tmp/ble_scan_after.json"

    if mode == "before":
        print("="*70)
        print("  STEP 1: BEFORE SCAN")
        print("="*70)
        print("\n⚠️  Make sure Vevor app is CLOSED!")
        print("⚠️  Make sure heater is ON but NOT connected\n")

        input("Press Enter to start scan...")

        devices = await scan_devices()
        save_scan(devices, before_file)

        print(f"\n✓ Found {len(devices)} devices")
        print("\nNext steps:")
        print("  1. Open Vevor app")
        print("  2. Connect to heater")
        print("  3. Run: python3 find_heater.py after")

    elif mode == "after":
        print("="*70)
        print("  STEP 2: AFTER SCAN")
        print("="*70)
        print("\n⚠️  Make sure Vevor app is CONNECTED to heater!\n")

        if not Path(before_file).exists():
            print("❌ ERROR: No 'before' scan found!")
            print("Run 'python3 find_heater.py before' first!")
            sys.exit(1)

        input("Press Enter to start scan...")

        devices = await scan_devices()
        save_scan(devices, after_file)

        print(f"\n✓ Found {len(devices)} devices")

        # Compare
        before = load_scan(before_file)
        after = devices

        compare_scans(before, after)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Stopped\n")
        sys.exit(0)
