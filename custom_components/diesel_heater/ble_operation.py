"""Serialize one heater's operations without changing BLE connection lifetime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import wraps


class BleOperationLock:
    """A per-coordinator lock reentrant only in its owning asyncio task."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.owner = None

    def owned_by_current_task(self):
        return self.owner is asyncio.current_task()

    @asynccontextmanager
    async def operation(self):
        if self.owned_by_current_task():
            yield
            return
        async with self._lock:
            self.owner = asyncio.current_task()
            try:
                yield
            finally:
                self.owner = None


@asynccontextmanager
async def transaction_context(coordinator):
    """Schedule a refresh only after the outer operation has released."""
    lock = coordinator._ble_operation_lock
    outer = not lock.owned_by_current_task()
    entered = False
    try:
        async with lock.operation():
            entered = True
            yield
    finally:
        if outer and entered and coordinator._ble_refresh_pending:
            coordinator._ble_refresh_pending = False
            coordinator.hass.async_create_task(coordinator.async_request_refresh())


def ble_transaction(method):
    """Order hardware operations; leave connection policy to protocol methods."""

    def decorate(function):
        @wraps(function)
        async def wrapped(self, *args, **kwargs):
            async with transaction_context(self):
                return await function(self, *args, **kwargs)

        return wrapped

    return decorate(method)
