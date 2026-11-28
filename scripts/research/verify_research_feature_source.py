"""Read-only OHLC and trading-day comparison for a frozen research export."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import gzip
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import load_private_readonly_settings


def compare(market, export, query):
    frozen = {}
    with gzip.open(export, "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if (row["symbol"], row["contract"], row["frequency"]) != (
                query.symbol, query.contract, query.frequency.value
            ) or not row["owned"]:
                continue
            day = date.fromisoformat(row["day"])
            if query.since <= day <= query.through:
                clock = datetime.fromisoformat(row["time"])
                if clock in frozen:
                    raise ValueError("FEATURE_SOURCE_DUPLICATE_BAR")
                frozen[clock] = (day, *(Decimal(str(row[key])) for key in ("open", "high", "low", "close")))
    actual = {
        bar.bar_end: (bar.trading_day, bar.open, bar.high, bar.low, bar.close)
        for bar in market.query_contract_trading_days(query).bars
    }
    if not frozen or actual != frozen:
        raise ValueError("FEATURE_SOURCE_SCOPE_OR_VALUE_MISMATCH")
    return len(frozen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("product")
    parser.add_argument("contract")
    parser.add_argument("since", type=date.fromisoformat)
    parser.add_argument("through", type=date.fromisoformat)
    parser.add_argument("--settings", type=Path, default=Path.home() / "Library/Application Support/GuiyiQuant/project.env")
    args = parser.parse_args()
    engine = None
    try:
        query = ContractTradingDayQuery(args.product, args.contract, BarFrequency("60m"), args.since, args.through)
        settings, _ = load_private_readonly_settings(args.settings)
        root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
        engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), hide_parameters=True,
                               connect_args={"connect_timeout": 5})
        with Session(engine) as session, readonly_transaction(session, timeout_seconds=25):
            market = MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))
            matched = compare(market, args.export, query)
        print(json.dumps({"contract": query.contract, "matched_ohlc_and_trading_day_rows": matched}))
    except MarketDataError as exc:
        parser.exit(1, f"{exc.code}\n")
    except Exception as exc:
        code = str(exc)
        if code not in ("FEATURE_SOURCE_DUPLICATE_BAR", "FEATURE_SOURCE_SCOPE_OR_VALUE_MISMATCH"):
            code = type(exc).__name__
        parser.exit(1, f"{code}\n")
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
