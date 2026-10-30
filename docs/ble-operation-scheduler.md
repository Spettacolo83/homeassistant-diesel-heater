# BLE operation scheduler

The integration orders heater polls and control operations through a per-Home-Assistant scheduler. It serializes operations, not connection lifetimes: successful polls and controls leave established GATT connections open. This does not free Bluetooth proxy slots or enable more simultaneous persistent connections than the adapter supports.

The scheduler uses `hass.data["diesel_heater_operation_scheduler_v1"]`. It is independent of other integrations and has no MicroAir connection-broker contract. Its `operation(participant, poll=False)` context only queues work. It never connects, disconnects, resets authentication, clears cached configuration or applies a transaction deadline.

Controls precede queued routine polls; after three control operations a waiting poll gets a turn. Ownership uses the current asyncio task and participant identity. Same-task nested operations reuse ownership; independently scheduled callbacks queue normally. Cancellation removes pending work or releases the operation slot. Protocol methods continue to own their connection, authentication, recovery and timeout behavior.

HeatGenie keeps its subscribed passive F2 reports after initial setup. Hcalory keeps its authenticated connection and existing faster poll interval. Warm Drive keeps startup/configuration reads and cached board configuration until an actual reconnect. Automatic clock synchronization retains upstream per-connection/session behavior. CBFF recovery retains separate 20-second connection and 15-second query deadlines; same-task timeout contexts avoid deadlocks when nested commands reuse the scheduler. There is no encompassing 15-second transaction cap.

Coordinator refreshes are coalesced and scheduled after the outer operation releases, because Home Assistant can refresh from another task. Burnoff takes its own lock before the operation slot and groups restore/power-off writes. Timer start/duration updates share one operation. Adapter recovery and unload cleanup wait for existing operations and do not open a new connection themselves.

Run `pytest tests/test_ble_operations.py -v` for complete production-class regressions with fake transport. These include repeated protocol polls, authentication/configuration preservation, CBFF recovery deadlines, FIFO/priority fairness, cancellation, independent callback ownership, cross-task refresh, burnoff and maintenance ordering. No real heater commands are issued by the tests.
