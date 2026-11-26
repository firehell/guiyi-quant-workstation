"""Reconcile one captured physical contract against RQData live 1m and Canonical."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, date, datetime
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import stat

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.market_data.aggregation import SessionWindow, expected_intraday_ends
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, DatasetKey
from app.market_data.historical_data_manager import BarFetchRequest
from app.market_data.live_market import _canonical_bar_from_raw_feed
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.rqdata_adapter import RQDataClient, RQDataMarketAdapter
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.tick_market import TickMinuteBuilder, decode_rqdata_tick
from app.private_settings import load_private_readonly_settings

_FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")


def compare(left, right):
    shared = sorted(left.keys() & right.keys())
    different = Counter(field for at in shared for field in _FIELDS
                        if getattr(left[at], field) != getattr(right[at], field))
    return {"overlap": len(shared), "exact": sum(left[at] == right[at] for at in shared),
            "left_only": len(left.keys() - right.keys()), "right_only": len(right.keys() - left.keys()),
            "different_fields": dict(sorted(different.items())),
            "first": shared[0].isoformat() if shared else None,
            "last": shared[-1].isoformat() if shared else None}


def history_rows(settings_path, *, symbol, contract, day, provider_history=False):
    settings, _ = load_private_readonly_settings(settings_path)
    engine = create_engine(settings["DATABASE_URL"], hide_parameters=True,
                           connect_args={"connect_timeout": 5})
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    try:
        with Session(engine) as session, readonly_transaction(session, timeout_seconds=20):
            mds = MarketDataService(MarketCatalog(session, root), CanonicalMonthlyStore(root))
            if not provider_history:
                data = mds.query_contract_trading_days(ContractTradingDayQuery(
                    symbol, contract, BarFrequency.M1, day, day,
                ))
                return {bar.bar_end: bar for bar in data.bars}
            if mds.dominant_segment_for_day(symbol, day).contract != contract:
                raise ValueError("CAPTURE_RANK1_CHANGED")
            sessions = mds.session_windows(symbol=symbol, trading_day=day)
            if datetime.now(UTC) <= sessions[-1].end:
                raise MarketDataError("CAPTURE_SESSION_STILL_OPEN")
            client = RQDataClient(settings=settings)
            if not client.is_future_data_ready(day):
                raise MarketDataError("CAPTURE_AUTHORITY_NOT_READY")
            expected = expected_intraday_ends(sessions, BarFrequency.M1)
            request = BarFetchRequest(
                DatasetKey("contract", symbol, contract, BarFrequency.M1),
                expected, (day,) * len(expected),
            )
            batch, = RQDataMarketAdapter(session=session, client=client).fetch_many((request,))
            if tuple(bar.bar_end for bar in batch.bars) != expected:
                raise MarketDataError("CAPTURE_AUTHORITY_ENDPOINTS_INCOMPLETE")
            return {bar.bar_end: bar for bar in batch.bars}
    finally:
        engine.dispose()


def replay(path, settings_path=None, *, provider_history=False):
    if provider_history and (not path.is_absolute() or not path.is_relative_to("/private/tmp")):
        raise ValueError("CAPTURE_PATH_INVALID")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64 * 1024 * 1024
            or provider_history and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        ):
            raise ValueError("CAPTURE_PATH_INVALID")
        identity = file_digest(source, "sha256").hexdigest()
        source.seek(0)
        metadata = json.loads(next(source))
        day = date.fromisoformat(metadata["trading_day"])
        symbol, contract = metadata["symbol"], metadata["contract"]
        builder = TickMinuteBuilder(tuple(
            SessionWindow(datetime.fromisoformat(start), datetime.fromisoformat(end))
            for start, end in metadata["sessions"]
        ))
        tick_bars, direct_bars = {}, {}
        diagnostics: Counter[str] = Counter()
        for line in source:
            item = json.loads(line)
            payload = item["payload"]
            if payload.get("order_book_id") != contract:
                raise ValueError("CAPTURE_OWNER_MISMATCH")
            if payload["channel"] == f"bar_{contract}":
                result = _canonical_bar_from_raw_feed(payload)
                if result is None:
                    diagnostics["bar_invalid"] += 1
                    continue
                _, bar = result
                prior = direct_bars.setdefault(bar.bar_end, bar)
                if prior != bar:
                    diagnostics["bar_conflict"] += 1
                continue
            diagnostics["tick_input"] += 1
            tick = decode_rqdata_tick(payload, trading_day=day,
                                      received_at=datetime.fromisoformat(item["received_at"]),
                                      connection=item["connection"])
            if tick is None:
                diagnostics["tick_invalid"] += 1
                builder.gap()
                continue
            update = builder.ingest(tick)
            if update.issue is not None:
                diagnostics[update.issue] += 1
            if update.completed is not None:
                bar = update.completed
                prior = tick_bars.setdefault(bar.bar_end, bar)
                if prior != bar:
                    diagnostics["tick_conflict"] += 1
    result = {"capture_sha256": identity, "contract": contract, "trading_day": str(day),
              "tick_completed": len(tick_bars), "live_1m": len(direct_bars),
              "diagnostics": dict(sorted(diagnostics.items())),
              "tick_to_live": compare(tick_bars, direct_bars)}
    if settings_path is not None:
        try:
            history = history_rows(settings_path, symbol=symbol, contract=contract, day=day,
                                   provider_history=provider_history)
        except MarketDataError as exc:
            result["authority_readback"] = exc.code
        else:
            relevant = tick_bars.keys() | direct_bars.keys()
            scope = {end: bar for end, bar in history.items() if end in relevant}
            result["authority"] = "rqdata_ready_history" if provider_history else "canonical"
            result["authority_day_rows"] = len(history)
            result["authority_input_sha256"] = sha256(repr(tuple(sorted(history.items()))).encode()).hexdigest()
            result["tick_to_authority"] = compare(tick_bars, scope)
            result["live_to_authority"] = compare(direct_bars, scope)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--provider-history", action="store_true",
                        help="make one bounded read-only RQData request after current day is ready")
    args = parser.parse_args()
    if args.provider_history and args.settings is None:
        parser.error("--provider-history requires private provider settings")
    try:
        result = replay(args.capture, args.settings, provider_history=args.provider_history)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
