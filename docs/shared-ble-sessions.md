# Short BLE sessions

Each heater acquires a shared BLE lease for a status read or complete control transaction, then disconnects before releasing it. The existing poll intervals remain unchanged, including Hcalory's faster interval. Cached readings survive normal disconnects; failed scheduled polls retain the existing bounded stale-data window. Raw notification payloads are logged at DEBUG.

Controls precede queued routine polls, with a waiting poll served after three controls. Nested commands reuse only the current task's lease. Coordinator refreshes are coalesced and scheduled after release, preventing cross-task refresh deadlocks. Burnoff acquires its own lock before BLE and keeps restore/power-off sequences atomic. Timer start/duration updates share one transaction. Adapter recovery and unload cleanup also wait for the lease, without opening a connection first.

Protocol-specific startup/authentication remains intact, including CBFF fresh-session recovery, delayed V2.1 handshakes and Warm Drive configuration reads. ABBA power-toggle guards read fresh status before deciding whether to toggle. Automatic clock synchronization is limited to once per day rather than every short reconnect; explicit synchronization remains available.

## Optional coordination contract, version 1

The integration works by itself. Other integrations can opt into the same per-Home-Assistant connection budget without importing another integration by using the compatible broker API under `hass.data["shared_ble_session_broker_v1"]`. The first integration constructs the broker; all subsequent integrations reuse it with `setdefault`.

A participant implements `_ensure_connected()`, `_cleanup_connection()`, `_finish_ble_session()` and `_logger`. Its stable participant object is passed to `broker.session(participant, poll=True|False)`. Session ownership is identified by the current asyncio task, so only nested calls in that same task/participant are reentrant. Callback tasks acquire independently. `broker.owned_by(participant)` tests ownership. Queue wait is outside the acquired-session timeout: 15 seconds for routine polls and 45 for controls. A participant may expose `_ble_poll_timeout` for a multi-record protocol, capped at 90 seconds; connection setup remains bounded by the default 15-second poll deadline. The budget is re-evaluated after protocol detection and includes time already spent connecting. Diesel Heater uses 90 seconds for Cronus record snapshots; the default and MicroAir remain 15. Participants must bound cleanup themselves; Diesel Heater allows five seconds and retains an unconfirmed connected client so the broker blocks new connections until cleanup succeeds.

The contract governs only participants that opt in, not all Bluetooth integrations. A copied broker implementation must retain this API, ordering, cleanup and ownership behavior. A breaking change requires another versioned key; do not silently reuse the v1 key with incompatible behavior.

Run `pytest tests/test_ble_sessions.py -v` for broker and complete production coordinator regressions with fake BLE transport. Existing protocol/control tests continue to exercise their isolated operation bodies. No real heater commands are issued by the tests.
