"""Retired thin after-market archive wrapper."""

from __future__ import annotations

from typing import Any


class AfterMarketArchiveService:
    def archive_once(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise RuntimeError("after-market archive service is retired")
