"""Serialize Diesel Heater operations without changing BLE connection lifetime."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager
from functools import wraps

SCHEDULER_KEY = "diesel_heater_operation_scheduler_v1"


class BleOperationScheduler:
    """Task-owned FIFO operations, with controls ahead of pending polls."""

    def __init__(self):
        self.owner = None
        self.participant = None
        self._pending = []
        self._sequence = itertools.count()
        self._commands = 0

    def owned_by(self, participant):
        return self.owner is asyncio.current_task() and self.participant is participant

    def _dispatch(self):
        if self.owner is not None:
            return
        self._pending[:] = [item for item in self._pending if not item[2].done()]
        heapq.heapify(self._pending)
        if not self._pending:
            return
        if self._commands >= 3 and any(item[0] == 1 for item in self._pending):
            item = min((i for i in self._pending if i[0] == 1), key=lambda i: i[1])
            self._pending.remove(item)
            heapq.heapify(self._pending)
        else:
            item = heapq.heappop(self._pending)
        priority, _, future, task, participant = item
        self.owner, self.participant = task, participant
        self._commands = self._commands + 1 if priority == 0 else 0
        future.set_result(None)

    @asynccontextmanager
    async def operation(self, participant, *, poll=False):
        task = asyncio.current_task()
        if self.owner is task:
            if self.participant is not participant:
                raise RuntimeError("Cannot nest another heater's operation")
            yield
            return
        future = asyncio.get_running_loop().create_future()
        item = (1 if poll else 0, next(self._sequence), future, task, participant)
        heapq.heappush(self._pending, item)
        self._dispatch()
        try:
            await future
            yield
        finally:
            future.cancel()
            if self.owner is task:
                self.owner = self.participant = None
            self._pending[:] = [i for i in self._pending if i is not item]
            heapq.heapify(self._pending)
            self._dispatch()


@asynccontextmanager
async def transaction_context(coordinator, *, poll=False):
    """Schedule a refresh only after the outer operation has released."""
    scheduler = coordinator._ble_scheduler
    outer = not scheduler.owned_by(coordinator)
    try:
        async with scheduler.operation(coordinator, poll=poll):
            yield
    finally:
        if outer and coordinator._ble_refresh_pending:
            coordinator._ble_refresh_pending = False
            coordinator.hass.async_create_task(coordinator.async_request_refresh())


def ble_transaction(method=None, *, poll=False):
    """Order hardware operations; leave connection policy to protocol methods."""

    def decorate(function):
        @wraps(function)
        async def wrapped(self, *args, **kwargs):
            async with transaction_context(self, poll=poll):
                return await function(self, *args, **kwargs)

        return wrapped

    return decorate(method) if method is not None else decorate
