"""Task-owned, fair BLE transactions shared by opt-in integrations on one HA."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager

BROKER_KEY = "shared_ble_session_broker_v1"
POLL_TIMEOUT = 15
COMMAND_TIMEOUT = 45
MAX_POLL_TIMEOUT = 90


class BleSessionBroker:
    """Prioritize controls, FIFO within priority; allow polls after three controls."""

    def __init__(self):
        self.owner = None
        self.participant = None
        self._pending = []
        self._sequence = itertools.count()
        self._commands = 0
        self._blocked = None

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

    async def _acquire(self, participant, priority):
        task = asyncio.current_task()
        if self.owner is task:
            if self.participant is not participant:
                raise RuntimeError(
                    "A BLE transaction cannot nest a different participant"
                )
            return False
        future = asyncio.get_running_loop().create_future()
        item = (priority, next(self._sequence), future, task, participant)
        heapq.heappush(self._pending, item)
        self._dispatch()
        try:
            await future
        except BaseException:
            future.cancel()
            if self.owner is task:
                self.owner = self.participant = None
            self._pending[:] = [i for i in self._pending if i is not item]
            heapq.heapify(self._pending)
            self._dispatch()
            raise
        return True

    async def _cleanup(self, participant):
        # Independent task is intentional: cancellation of the caller must not
        # release its lease while the proxy still owns a connection.
        cleanup = asyncio.create_task(participant._cleanup_connection())
        while True:
            try:
                await asyncio.shield(cleanup)
                return
            except asyncio.CancelledError:
                if cleanup.done():
                    return cleanup.result()
                continue

    @asynccontextmanager
    async def session(self, participant, *, poll=False):
        outer = await self._acquire(participant, 1 if poll else 0)
        if not outer:
            yield
            return
        try:
            # A timed-out disconnect quarantines the old client. No new client
            # is opened until a later cleanup positively releases that slot.
            if self._blocked is not None:
                await self._cleanup(self._blocked)
                self._blocked = None
            started = asyncio.get_running_loop().time()
            async with asyncio.timeout(
                POLL_TIMEOUT if poll else COMMAND_TIMEOUT
            ) as deadline:
                await participant._ensure_connected()
                if poll:
                    # Connection is always bounded by the default poll budget.
                    # A detected multi-record protocol may need longer to read.
                    budget = min(
                        MAX_POLL_TIMEOUT,
                        max(
                            0.001,
                            getattr(participant, "_ble_poll_timeout", POLL_TIMEOUT),
                        ),
                    )
                    deadline.reschedule(started + budget)
                yield
                await participant._finish_ble_session()
        finally:
            try:
                await self._cleanup(participant)
            except BaseException:
                self._blocked = participant
                participant._logger.exception(
                    "BLE disconnect incomplete; blocking new sessions until cleanup succeeds"
                )
            finally:
                self.owner = self.participant = None
                self._dispatch()
