"""Diesel hardware transactions with refresh deferred until BLE release."""

from contextlib import asynccontextmanager
from functools import wraps


@asynccontextmanager
async def transaction_context(coordinator):
    """Release before scheduling a coalesced coordinator refresh."""
    outer = not coordinator._ble_broker.owned_by(coordinator)
    try:
        async with coordinator._ble_broker.session(coordinator):
            yield
    finally:
        if outer and coordinator._ble_refresh_pending:
            coordinator._ble_refresh_pending = False
            # Never await here: the caller may still own the burnoff lock.
            coordinator.hass.async_create_task(coordinator.async_request_refresh())


def ble_transaction(method):
    """Wrap a complete hardware operation; nested same-task calls reuse it."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with transaction_context(self):
            return await method(self, *args, **kwargs)

    return wrapped
