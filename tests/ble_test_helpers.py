"""Lease fixture for existing protocol tests that isolate transport/session work."""

from contextlib import asynccontextmanager


class AlreadyLeasedBroker:
    """Existing protocol tests exercise bodies as an already connected operation.

    Real broker ownership/connect/disconnect behavior is covered separately by
    test_ble_sessions.py, using the production broker and full coordinator class.
    """

    def owned_by(self, participant):
        return True

    @asynccontextmanager
    async def session(self, participant, *, poll=False):
        yield


def initialize_leased_fixture(coordinator):
    coordinator._ble_broker = AlreadyLeasedBroker()
    coordinator._ble_refresh_pending = False
    coordinator._v21_handshake_task = None
    coordinator._last_successful_read = None
    coordinator._last_auto_time_sync_date = None
