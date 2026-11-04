# Per-device BLE operation locking

Each heater coordinator owns a reentrant asyncio lock. A poll, control sequence or maintenance operation holds that device's lock; different heaters can operate concurrently. Home Assistant and its Bluetooth/Bleak stack continue to manage adapters, connection slots and retries. There is no global queue, priority policy or cross-integration connection broker.

Persistent connections remain the default. Successful polls and controls retain persistent GATT clients, authentication and cached configuration unless the narrowly restricted experimental policy below is explicitly selected. HeatGenie passive F2 reports, Hcalory polling/authentication, Warm Drive startup/configuration reads and native clock behavior remain unchanged. CBFF retains separate 20-second connection and 15-second query recovery budgets, using same-task timeout contexts so nested operations do not deadlock. No global transaction deadline is added.

Ownership uses the current asyncio task. Nested calls in the owning task reuse the lock; callbacks scheduled as separate tasks must acquire it. Cancellation releases the lock or removes a waiting acquisition. No context-variable ownership is inherited by callback tasks.

Coordinator refreshes are coalesced after the outer operation releases, because Home Assistant can refresh from another task. Burnoff takes its own lock before the device operation lock and groups restore/power-off writes. Timer start/duration updates share one operation. Tank-volume and pump-type select configuration writes also use the device lock. Recovery/unload serialize with their own device's operations without opening a new connection.

## Experimental AA66 Encrypted release policy

In the device's configuration options, **Bluetooth connection policy** defaults to **Persistent**. **Release between polls** is an explicit experimental choice, enforced at runtime only after status identifies **AA66 Encrypted (protocol mode 4)**. Unknown controllers and every other protocol retain persistent connections, even if that option is stored. This is not a general APK-family capability claim.

The eligible controller polls at least 60 seconds apart and releases its GATT connection after the outer poll/control sequence finishes. Controls reconnect immediately and require a fresh status read before evaluating guards or sending settings. Nested timer/burnoff writes remain one operation. Intentional release retains validated values and the native clock-sync marker; real poll/transport failures retain upstream stale-data/error handling and reset the marker. Explicit clock sync remains available. Persistent protocol initialization, notification lifetimes and timeout budgets remain unchanged.

Cleanup is bounded and shielded through repeated cancellation. A disconnect error, timeout or still-connected client retains its handle; another connection cannot replace it until cleanup confirms release. Unload cancels its owned writers before waiting for the operation lock.

A confirmed disconnect frees the occupied connection slot for other devices; it does not reserve a slot or increase simultaneous proxy capacity. Home Assistant/Bleak still selects adapters. Historical AA66 hardware observations cover status polling and idle slot release only: active controls, burnoff and long-term behavior need hardware validation for each controller. The new option itself has mocked regression coverage and has not been enabled or deployed to a live installation. Keep persistent mode for unvalidated hardware; no other protocol is eligible.

Run `pytest tests/test_ble_operations.py -v` for complete production-class regressions with fake transport, including repeated protocol polls, valid passive F2 delivery, CBFF recovery, same-device exclusion, different-device concurrency, cancellation, callback ownership, cross-task refresh, direct select writes and burnoff/maintenance ordering. No real heater commands are issued by tests.
