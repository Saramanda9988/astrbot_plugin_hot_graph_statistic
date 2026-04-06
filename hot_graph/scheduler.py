from __future__ import annotations

import asyncio
import contextlib
from typing import Any


class SyncScheduler:
    def __init__(self, service: Any, interval_seconds: int, logger: Any) -> None:
        self.service = service
        self.interval_seconds = interval_seconds
        self.logger = logger
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stopped.clear()
            self._task = asyncio.create_task(self._run(), name="hot-graph-sync")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.service.sync_all_registered_users()
            except Exception as exc:  # pragma: no cover
                self.logger.error("hot graph sync failed: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue
