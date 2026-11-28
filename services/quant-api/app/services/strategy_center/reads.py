"""At most one in-flight source read per domain and per API process."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from fastapi import HTTPException

from .catalog import DOMAINS


def projection(source, status, *, source_as_of=None, diagnostic=None, **facts):
    return {
        "source": source,
        "status": status,
        "source_as_of": source_as_of,
        "diagnostic": diagnostic,
        **facts,
    }


def version(kind, value, source):
    return {"kind": kind, "value": value, "source": source}


def _call(source, read, args):
    try:
        return read(*args)
    except HTTPException as error:
        detail = error.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        if code in {"SIMULATION_SOURCE_UNAVAILABLE", "PORTFOLIO_STATUS_UNAVAILABLE"}:
            return projection(source, "UNAVAILABLE", diagnostic=code)
        return projection(source, "UNAVAILABLE", diagnostic="SOURCE_READ_FAILED")
    except Exception:
        # The source boundary can contain filesystem paths, URLs and SQL errors.
        return projection(source, "UNAVAILABLE", diagnostic="SOURCE_READ_FAILED")


class DomainReads:
    def __init__(self, timeout=2.0):
        self.timeout = timeout
        self._slots = {domain: BoundedSemaphore(1) for domain in DOMAINS}
        self._executor = ThreadPoolExecutor(max_workers=len(DOMAINS), thread_name_prefix="strategy-read")

    async def run(self, domain, source, read, *args):
        slot = self._slots[domain]
        if not slot.acquire(blocking=False):
            return projection(source, "UNAVAILABLE", diagnostic="SOURCE_BUSY")
        try:
            pending = self._executor.submit(_call, source, read, args)
        except RuntimeError:
            slot.release()
            return projection(source, "UNAVAILABLE", diagnostic="SOURCE_READ_FAILED")
        # The callback runs even when the HTTP client disconnects. Keep the
        # slot until the source actually exits, including after a deadline.
        pending.add_done_callback(lambda _: slot.release())
        try:
            return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(pending)), self.timeout)
        except TimeoutError:
            return projection(source, "UNAVAILABLE", diagnostic="SOURCE_TIMEOUT")
