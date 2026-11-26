"""Freeze one bounded matrix via the standard Market reader, without a provider or writer."""

import argparse
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, SeriesKind, SeriesQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import load_private_readonly_settings


# Each window targets at least the 60 completed Bars needed by EMA60 when coverage and owner permit.
DAYS_BY_FREQUENCY = {"1m": 1, "5m": 4, "15m": 9, "30m": 16, "60m": 32, "1d": 100, "1w": 470}


def freeze(universe: Path, config: Path, through: date, output: Path):
    products = tuple(line.strip() for line in universe.read_text().splitlines() if line.strip())
    if len(products) != 60 or len(set(products)) != 60:
        raise ValueError("BENCHMARK_SCOPE_MISMATCH")
    settings, _ = load_private_readonly_settings(config)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(
        normalize_database_url(settings["DATABASE_URL"]), hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c default_transaction_read_only=on"},
    )
    zone = ZoneInfo("Asia/Shanghai")
    end = datetime.combine(through, time(16), zone)
    captured = []
    missing = []
    try:
        store = CanonicalMonthlyStore(root)
        # One bounded read transaction per frequency, one query at a time.
        for frequency_name, days in DAYS_BY_FREQUENCY.items():
            frequency = BarFrequency(frequency_name)
            with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=15):
                market = MarketDataService(MarketCatalog(session, root), store)
                for product in products:
                    query = SeriesQuery(SeriesKind.ACTUAL_DOMINANT, product, frequency, end - timedelta(days=days), end)
                    try:
                        result = market.query(query)
                    except MarketDataError as exc:
                        missing.append([product, frequency_name, exc.code])
                        continue
                    if not result.bars:
                        missing.append([product, frequency_name, "EMPTY"])
                        continue
                    owners = {
                        day: (segment.contract, segment.start_trading_day)
                        for segment in result.resolved_contract_segments
                        for day in {bar.trading_day for bar in result.bars}
                        if segment.start_trading_day <= day <= segment.end_trading_day
                    }
                    if any(bar.trading_day not in owners for bar in result.bars):
                        missing.append([product, frequency_name, "OWNER_UNPROVEN"])
                        continue
                    for (physical, segment_start), group in groupby(result.bars, key=lambda bar: owners[bar.trading_day]):
                        rows = [bar.as_record() for bar in group]
                        rows_json = json.dumps(rows, default=str, sort_keys=True, separators=(",", ":"))
                        captured.append({
                            "product": product, "frequency": frequency_name, "physical": physical,
                            "segment_start": segment_start.isoformat(), "rows": rows,
                            "revision": sha256(rows_json.encode()).hexdigest(),
                        })
            print(f"{frequency_name} checked {len(products)}", flush=True)
    finally:
        engine.dispose()
    with output.open("x", encoding="utf-8") as file:
        json.dump({"through": through.isoformat(), "series": captured, "missing": missing}, file,
                  default=str, sort_keys=True, separators=(",", ":"))
    print(f"Frozen {len(captured)} owner segments, {len(missing)} missing product-frequency slots", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    try:
        freeze(options.universe, options.config, options.through, options.output)
    except (ValueError, OSError) as exc:
        # Private configuration or paths never appear in diagnostics.
        parser.exit(1, f"Freeze failed ({type(exc).__name__})\n")
