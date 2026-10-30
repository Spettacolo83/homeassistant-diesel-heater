# Per-device BLE operation locking

Each heater coordinator serializes polls, control writes and recovery for that heater. Other heaters can operate concurrently, and Home Assistant's Bluetooth stack still manages connection capacity.

The integration keeps successful GATT sessions and notification subscriptions open between polls. AirHeaterBLE establishes the AA66 Encrypted connection, enables notifications, reads status, synchronizes the clock and continues polling on the same session. Its native write path uses the existing GATT connection. Connection teardown is a separate operation. The lock also preserves HeatGenie's passive F2 reports, Hcalory authentication, Warm Drive and Sunster Neo initialization, Sunster CBFF recovery, and Cronus record polling.

Nested calls in the same asyncio task share ownership. The coordinator's connect and query deadlines run in that task. Deferred refreshes run after release, and cancelling a waiter leaves the active operation's refresh intact.

Hardware paths take the device lock before the burn-off state lock. This keeps restoration and the subsequent shutdown attempt together, including the retry path for an unconfirmed shutdown. Timer start and duration writes also share a device operation. Recovery and unload use the same device lock.

Credit to @wlatic for the scheduler in [PR #155](https://github.com/Spettacolo83/homeassistant-diesel-heater/pull/155).
