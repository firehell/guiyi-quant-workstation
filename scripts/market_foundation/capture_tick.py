"""Bounded, read-only capture of RQData Tick and 1m for one rank1 contract."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event
from time import monotonic, sleep
import warnings

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.market_data_service import MarketDataService
from app.market_data.operational_universe import load_operational_products
from app.market_data.rqdata_adapter import RQDataClient
from app.market_data.tick_rqdata_client import create_tick_client
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import load_private_readonly_settings

_TICK_FIELDS = frozenset({
    "action", "channel", "order_book_id", "datetime", "trading_date", "open", "high", "low", "close",
    "last", "volume", "total_turnover", "turnover", "open_interest", "ask", "ask_vol", "bid", "bid_vol",
})


def capture(args: argparse.Namespace) -> dict:
    if args.symbol not in load_operational_products() or not 1 <= args.seconds <= 3600:
        raise ValueError("CAPTURE_SCOPE_INVALID")
    path = args.output
    if path.suffix != ".jsonl" or path.parent.resolve() != path.parent or not path.is_absolute():
        raise ValueError("CAPTURE_PATH_INVALID")
    if not path.is_relative_to(Path("/private/tmp")):
        raise ValueError("CAPTURE_PATH_INVALID")
    settings, _ = load_private_readonly_settings(args.settings)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(settings["DATABASE_URL"], hide_parameters=True,
                           connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session, readonly_transaction(session, timeout_seconds=10):
            mds = MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))
            contract = mds.dominant_segment_for_day(args.symbol, args.day).contract
            windows = mds.session_windows(symbol=args.symbol, trading_day=args.day)
    finally:
        engine.dispose()

    now = datetime.now(UTC)
    if args.start_at is not None:
        target = args.start_at
        if (
            target.utcoffset() is None
            or not 0 <= (target - now).total_seconds() <= args.wait_seconds
            or not any(window.start - timedelta(minutes=2) <= target <= window.end for window in windows)
        ):
            raise ValueError("CAPTURE_START_TIME_INVALID")
        sleep((target - now).total_seconds())
        now = datetime.now(UTC)
    if not any(window.start - timedelta(minutes=2) <= now <= window.end for window in windows):
        next_open = next((window.start for window in windows if window.start > now), None)
        if next_open is None or (next_open - now).total_seconds() > args.wait_seconds:
            raise ValueError("CAPTURE_OUTSIDE_READY_WINDOW")
        sleep(max(0, (next_open - now).total_seconds() - 15))
    client = create_tick_client(RQDataClient(settings=settings))
    queue: Queue = Queue(maxsize=4096)
    overflow = Event()
    channels = (f"tick_{contract}", f"bar_{contract}")
    counts = dict.fromkeys(channels, 0)

    def enqueue(item):
        if not isinstance(item, dict) or item.get("channel") not in channels or overflow.is_set():
            return
        try:
            queue.put_nowait((datetime.now(UTC), client._client, item))
        except Full:
            overflow.set()

    listener = None
    try:
        client.subscribe(list(channels))
        listener = client.listen(handler=enqueue)
        deadline = monotonic() + args.seconds
        generations = {}
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            output.write(json.dumps({
                "symbol": args.symbol, "contract": contract, "trading_day": args.day.isoformat(),
                "sessions": [[window.start.isoformat(), window.end.isoformat()] for window in windows],
                "started_at": datetime.now(UTC).isoformat(), "tls_certificate_verification": "required",
            }) + "\n")
            while not overflow.is_set() and monotonic() < deadline and sum(counts.values()) < 100_000:
                try:
                    received, connection, item = queue.get(timeout=0.2)
                except Empty:
                    if not listener.is_alive():
                        break
                    continue
                counts[item["channel"]] += 1
                generation = generations.setdefault(connection, len(generations) + 1)
                output.write(json.dumps({
                    "received_at": received.isoformat(), "connection": generation,
                    "payload": {key: item[key] for key in sorted(item.keys() & _TICK_FIELDS)},
                }) + "\n")
    finally:
        client.close()
        if listener is not None:
            listener.join(timeout=5)
    return {"contract": contract, "counts": counts, "overflow": overflow.is_set(),
            "listener_stopped": not listener.is_alive(),
            "status": ("captured" if all(counts.values()) and not overflow.is_set()
                       and not listener.is_alive() else "insufficient")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--seconds", required=True, type=int)
    parser.add_argument("--start-at", type=datetime.fromisoformat)
    parser.add_argument("--wait-seconds", type=int, default=0, choices=range(0, 7201), metavar="0..7200")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        result = capture(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result))
    return 0 if result["status"] == "captured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
