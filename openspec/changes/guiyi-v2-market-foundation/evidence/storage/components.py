#!/usr/bin/env python3
"""Headless VeighNa component and bounded RQData history comparison."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import importlib.metadata
from pathlib import Path
import re
import sys
from threading import Event as Latch
from unittest.mock import patch

import pandas as pd
from sqlalchemy.orm import Session

from app.market_data.historical_data_manager import BarFetchRequest
from app.market_data.rqdata_adapter import RQDataClient, RQDataMarketAdapter
from app.private_settings import load_private_execution_settings

from benchmark import DAY_ZONE, NUMERIC_FIELDS, dump, load_frozen


CONTRACT = "RB2701"
TRADING_DAY = date(2026, 11, 25)


def headless():
    from vnpy.event import Event, EventEngine
    from vnpy.trader.constant import Exchange
    from vnpy.trader.database import BaseDatabase
    from vnpy.trader.datafeed import BaseDatafeed
    from vnpy.trader.object import TickData
    from vnpy.trader.utility import BarGenerator
    from vnpy_datamanager.engine import ManagerEngine
    from vnpy_datarecorder.engine import RecorderEngine
    from vnpy_postgresql.postgresql_database import PostgresqlDatabase
    from vnpy_rqdata.rqdata_datafeed import RqdataDatafeed

    received: list[int] = []
    complete = Latch()
    engine = EventEngine()

    def receive(event: Event) -> None:
        received.append(event.data)
        if event.data == 63:
            complete.set()

    engine.register("market.component.fixture", receive)
    engine.start()
    try:
        for value in range(64):
            engine.put(Event("market.component.fixture", value))
        if not complete.wait(3) or received != list(range(64)):
            raise ValueError("EVENT_ORDER_INVALID")
    finally:
        engine.stop()

    bars = []
    generator = BarGenerator(bars.append)

    def tick(day, hour, minute, second, volume, turnover):
        return TickData(
            symbol=CONTRACT, exchange=Exchange.SHFE,
            datetime=datetime(2026, 11, day, hour, minute, second, tzinfo=DAY_ZONE),
            last_price=3000, volume=volume, turnover=turnover, open_interest=3500,
            gateway_name="MARKET_COMPONENT_FIXTURE",
        )

    generator.update_tick(tick(24, 23, 59, 5, 20, 60000))
    generator.update_tick(tick(24, 23, 59, 10, 23, 69000))
    generator.update_tick(tick(25, 0, 0, 9, 2, 6000))
    if len(bars) != 1 or bars[0].volume != 3 or bars[0].datetime.minute != 59:
        raise ValueError("BAR_GENERATOR_FIXTURE_UNEXPECTED")
    terminal = generator.generate()
    if terminal is None or not len(bars) == 2 or terminal.volume != 0:
        raise ValueError("BAR_GENERATOR_TAIL_FIXTURE_UNEXPECTED")
    if any(name.startswith(("PySide6", "pyqtgraph")) for name in sys.modules):
        raise ValueError("UNEXPECTED_GUI_IMPORT")
    return {
        "datafeed_subclass": issubclass(RqdataDatafeed, BaseDatafeed),
        "native_database_subclass": issubclass(PostgresqlDatabase, BaseDatabase),
        "headless_imports": [ManagerEngine.__name__, RecorderEngine.__name__],
        "event_ordered_fixture_events": len(received), "event_queue_capacity": engine._queue.maxsize,
        "bar_generator_fixture": {
            "start_label": bars[0].datetime.isoformat(), "first_tick_baseline_not_emitted": True,
            "negative_delta_silently_clamped": terminal.volume == terminal.turnover == 0,
            "explicit_flush_requires_external_completion_proof": True,
        },
        "gui_loaded": False,
        "versions": {name: importlib.metadata.version(name) for name in (
            "vnpy", "vnpy_rqdata", "vnpy_datamanager", "vnpy_datarecorder",
            "vnpy_postgresql", "vnpy_spreadtrading", "rqdatac",
        )},
    }


def compare_history(work: Path, config: Path) -> dict:
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import HistoryRequest
    from vnpy_rqdata import rqdata_datafeed as upstream

    physical, = [sample for sample in load_frozen(work) if sample.native_symbol == CONTRACT]
    expected = tuple(bar for bar in physical.bars if bar.trading_day == TRADING_DAY)
    ends = tuple(bar.bar_end for bar in expected)
    if not ends or ends[-1].astimezone(DAY_ZONE).hour != 15:
        raise ValueError("FROZEN_TRADING_DAY_INVALID")
    settings, _ = load_private_execution_settings(config)
    client = RQDataClient(settings=settings)
    source = client.price(CONTRACT, TRADING_DAY, TRADING_DAY, "1m")
    fields = ("open", "high", "low", "close", "volume", "total_turnover", "open_interest")
    if not isinstance(source, pd.DataFrame) or not set(fields).issubset(source.columns):
        raise ValueError("SOURCE_FRAME_SCHEMA_INVALID")
    if len(source) != len(expected) or not source.index.is_unique:
        raise ValueError("SOURCE_FRAME_COVERAGE_INVALID")

    class FrozenClient:
        def price(self, contract, start, end, frequency):
            if (contract, start, end, frequency) != (CONTRACT, TRADING_DAY, TRADING_DAY, "1m"):
                raise ValueError("SOURCE_CAPTURE_SCOPE_INVALID")
            return source.copy(deep=True)

    with Session() as session:
        adapter = RQDataMarketAdapter(session=session, client=FrozenClient())
        normalized, = adapter.fetch_many((BarFetchRequest(physical.key, ends, (TRADING_DAY,) * len(ends)),))
    canonical_mismatches = Counter(
        name for native, frozen in zip(normalized.bars, expected, strict=True)
        for name in (*NUMERIC_FIELDS, "bar_end", "trading_day") if getattr(native, name) != getattr(frozen, name)
    )
    feed = upstream.RqdataDatafeed()
    feed.inited = True
    feed.symbols = {CONTRACT}
    request = HistoryRequest(
        symbol=CONTRACT, exchange=Exchange.SHFE, interval=Interval.MINUTE,
        start=ends[0] - timedelta(minutes=1), end=ends[-1],
    )

    def convert(frame):
        # Supply the already captured single-day response. Replacing the two
        # provider functions prevents upstream from broadening the real request.
        with (patch.object(upstream, "get_price", return_value=frame.copy(deep=True)),
              patch.object(upstream, "get_next_trading_date", return_value=TRADING_DAY)):
            return feed.query_bar_history(request, output=lambda _: None)

    upstream_bars = convert(source)
    mismatch = Counter()
    for ours, theirs in zip(normalized.bars, upstream_bars, strict=True):
        if ours.bar_end != theirs.datetime + timedelta(minutes=1):
            mismatch["bar_end_after_adapter"] += 1
        for name, remote in NUMERIC_FIELDS.items():
            if getattr(ours, name) != Decimal(str(getattr(theirs, remote))):
                mismatch[name] += 1
    fixture = source.copy(deep=True)
    fixture.loc[fixture.index[0], "total_turnover"] = float("nan")
    fixture_upstream = convert(fixture)
    if fixture_upstream[0].turnover != 0:
        raise ValueError("NULLABILITY_PROBE_UNEXPECTED")
    return {
        "contract": CONTRACT, "trading_day": TRADING_DAY.isoformat(), "provider_history_requests": 1,
        "raw_response_sha256": sha256(source.to_csv().encode()).hexdigest(),
        "rows": len(source), "first_bar_end": ends[0].isoformat(), "last_bar_end": ends[-1].isoformat(),
        "raw_start_label_shift_minutes": 1,
        "canonical_vs_frozen_mismatches": dict(canonical_mismatches),
        "vnpy_vs_canonical_mismatches_after_label_alignment": dict(mismatch),
        "raw_nullable_count": {name: int(source[name].isna().sum()) for name in fields},
        "synthetic_null_fixture_replaced_by_zero": True,
        "trading_day_preserved_by_vnpy": hasattr(upstream_bars[0], "trading_day"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    current = Path.cwd()
    try:
        if (current.parent != Path("/private/tmp")
            or not current.name.startswith("guiyi-v2-market-storage.")
            or not (current / ".vntrader").is_dir()):
            raise ValueError("ISOLATED_VNTRADER_REQUIRED")
        result = {"headless": headless()}
        if args.config:
            result["real_rqdata_history"] = compare_history(current, args.config)
        dump(current / "components.json", result)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code is None and type(exc) is ValueError:
            code = str(exc)
        if not isinstance(code, str) or re.fullmatch(r"[-_0-9A-Za-z]{1,100}", code) is None:
            code = type(exc).__name__
        print(code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
