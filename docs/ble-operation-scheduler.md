# Per-device BLE operation locking

Each heater coordinator owns a reentrant asyncio lock. A poll, control sequence or maintenance operation holds that device's lock; different heaters can operate concurrently. Home Assistant and its Bluetooth/Bleak stack continue to manage adapters, connection slots and retries. There is no global queue, priority policy or cross-integration connection broker.

The lock does not manage connection lifetimes. Successful polls and controls retain persistent GATT clients, authentication and cached configuration. HeatGenie passive F2 reports, Hcalory polling/authentication, Warm Drive startup/configuration reads and native clock behavior remain unchanged. CBFF retains separate 20-second connection and 15-second query recovery budgets, using same-task timeout contexts so nested operations do not deadlock. No global transaction deadline is added.

Ownership uses the current asyncio task. Nested calls in the owning task reuse the lock; callbacks scheduled as separate tasks must acquire it. Cancellation releases the lock or removes a waiting acquisition. No context-variable ownership is inherited by callback tasks.

Coordinator refreshes are coalesced after the outer operation releases, because Home Assistant can refresh from another task. Burnoff takes its own lock before the device operation lock and groups restore/power-off writes. Timer start/duration updates share one operation. Tank-volume and pump-type select configuration writes also use the device lock. Recovery/unload serialize with their own device's operations without opening a new connection.

This does not free persistent GATT slots or make more simultaneous connections possible. Any future short-session policy requires exact protocol/model evidence and separate hardware validation; it is not enabled by this change.

Run `pytest tests/test_ble_operations.py -v` for complete production-class regressions with fake transport, including repeated protocol polls, valid passive F2 delivery, CBFF recovery, same-device exclusion, different-device concurrency, cancellation, callback ownership, cross-task refresh, direct select writes and burnoff/maintenance ordering. No real heater commands are issued by tests.
