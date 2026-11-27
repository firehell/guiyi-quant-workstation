"""Run the isolated Tick feed and its loopback-only Market display for a bounded interval."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
import warnings

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from uvicorn import Config, Server

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.rqdata_adapter import RQDataClient
from app.market_data.tick_rqdata_client import create_tick_client
from app.market_data.tick_runtime import build_isolated_tick_display, open_isolated_tick_market
from app.private_settings import load_private_readonly_settings


def natural_window_seconds(windows, *, now: datetime) -> float:
    first = min(window.start for window in windows)
    close = max(window.end for window in windows)
    stop = close + timedelta(minutes=2)
    if not first - timedelta(minutes=2) <= now < first or not timedelta(0) < stop - now <= timedelta(hours=24):
        raise ValueError("MARKET_FOUNDATION_DISPLAY_NATURAL_WINDOW_INVALID")
    return (stop - now).total_seconds()


def run(args) -> dict:
    if not 1024 <= args.port <= 65_535 or args.port == 8000 or (
        args.seconds is not None and not 1 <= args.seconds <= 14_400
    ):
        raise ValueError("MARKET_FOUNDATION_DISPLAY_SCOPE_INVALID")
    database = make_url(normalize_database_url(os.environ["DATABASE_URL"]))
    redis_url = os.environ["REDIS_URL"]
    sandbox = Path(os.environ["GUIYI_MARKET_FOUNDATION_SANDBOX"])
    canonical = Path(os.environ["GUIYI_CANONICAL_DATA_ROOT"])
    provider_settings, _ = load_private_readonly_settings(args.provider_settings)
    engine = create_engine(database, hide_parameters=True, connect_args={"connect_timeout": 5})
    failures: Counter[str] = Counter()
    try:
        with Session(engine) as session, open_isolated_tick_market(
            session=session, database_url=database, redis_url=redis_url,
            canonical_root=canonical, products=tuple(args.product),
            client_factory=lambda: create_tick_client(RQDataClient(settings=provider_settings)),
        ) as market:
            seconds = args.seconds
            if seconds is None:
                with readonly_transaction(session, timeout_seconds=15):
                    data = MarketDataService(MarketCatalog(session, canonical), CanonicalMonthlyStore(canonical))
                    windows = tuple(window for product in args.product for window in data.session_windows(
                        symbol=product, trading_day=args.trading_day,
                    ))
                seconds = natural_window_seconds(windows, now=datetime.now(UTC))
            deadline = monotonic() + seconds
            market.bind_day(args.trading_day)
            app = build_isolated_tick_display(
                market, redis_url=redis_url, canonical_root=canonical,
                after_market_status_path=sandbox / "after-market-status.json",
            )
            server = Server(Config(app, host="127.0.0.1", port=args.port, access_log=False, log_level="critical"))
            worker = Thread(target=server.run, name="market-foundation-display")
            worker.start()
            try:
                start_timeout = min(deadline, monotonic() + 5)
                while worker.is_alive() and not server.started and monotonic() < start_timeout:
                    sleep(0.05)
                if not server.started:
                    raise RuntimeError("MARKET_FOUNDATION_DISPLAY_START_FAILED")
                while worker.is_alive() and monotonic() < deadline:
                    feed, compute = market.poll(datetime.now(UTC))
                    if feed:
                        failures["feed"] += 1
                    if compute:
                        failures["completed"] += 1
                    sleep(0.2)
                if not worker.is_alive() and monotonic() < deadline:
                    raise RuntimeError("MARKET_FOUNDATION_DISPLAY_EXITED")
            finally:
                server.should_exit = True
                worker.join(timeout=10)
                if worker.is_alive():
                    raise RuntimeError("MARKET_FOUNDATION_DISPLAY_STOP_PENDING")
    finally:
        engine.dispose()
    return {"status": "isolated_display_stopped", "poll_failures": dict(failures)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-settings", required=True, type=Path)
    parser.add_argument("--trading-day", required=True, type=date.fromisoformat)
    parser.add_argument("--product", action="append", required=True)
    parser.add_argument("--port", type=int, default=8011)
    bounds = parser.add_mutually_exclusive_group(required=True)
    bounds.add_argument("--seconds", type=int)
    bounds.add_argument("--complete-trading-day", action="store_true",
                        help="from two minutes before the first Session to two minutes after the last; max 24h")
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    try:
        summary = run(parser.parse_args())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(summary))
    return 0 if not summary["poll_failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
