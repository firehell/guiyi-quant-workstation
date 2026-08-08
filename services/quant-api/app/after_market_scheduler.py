"""Retired after-market scheduler entrypoint.

Production Profile/Binding archive automation is permanently fail-closed.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

PRODUCT = "jm"
LOCK_KEY = "guiyi:eod:jm:scheduler:singleton"
HEARTBEAT_KEY = "guiyi:eod:jm:scheduler:heartbeat"
LOCK_LEASE_SECONDS = 180
HEARTBEAT_TTL_SECONDS = 180


class AfterMarketRetiredError(RuntimeError):
    """Raised when retired after-market automation is invoked."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guiyi after-market scheduler (retired)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run-once", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--retry-failed-day", type=str)
    mode.add_argument("--supervised-smoke", action="store_true")
    parser.add_argument("--product", default=PRODUCT, choices=(PRODUCT,))
    parser.add_argument("--approval-packet", type=str)
    parser.add_argument("--approval-hash")
    parser.add_argument("--confirm-after-market-automation", action="store_true")
    parser.add_argument("--confirm-retry", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: Callable[[], Any] | None = None,
    client_factory: Callable[[], Any] | None = None,
    redis_factory: Callable[[], Any] | None = None,
) -> int:
    del environ, session_factory, client_factory, redis_factory
    args = parse_args(argv)
    payload = {
        "mode": "retired",
        "product": args.product,
        "enabled": False,
        "retired": True,
        "status": "retired",
        "error_type": "AFTER_MARKET_ARCHIVE_RETIRED",
        "would_construct_rqdata_client": False,
        "would_connect_redis": False,
        "would_write_database": False,
        "would_write_parquet": False,
    }
    print(payload)
    if args.dry_run:
        return 0
    raise AfterMarketRetiredError("after-market archive production path is retired")


if __name__ == "__main__":
    raise SystemExit(main())
