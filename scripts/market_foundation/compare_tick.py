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
    return {"different_endpoints": [
                {"end": at.isoformat(),
                 "fields": [field for field in _FIELDS if getattr(left[at], field) != getattr(right[at], field)]}
                for at in shared if left[at] != right[at]
            ],
            "overlap": len(shared), "exact": sum(left[at] == right[at] for at in shared),
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


def _read_capture(path, *, provider_history):
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
        sessions = tuple(SessionWindow(datetime.fromisoformat(start), datetime.fromisoformat(end))
                         for start, end in metadata["sessions"])
        builder = TickMinuteBuilder(sessions)
        tick_bars, direct_bars = {}, {}
        diagnostics: Counter[str] = Counter()
        conflicts = {"tick": set(), "bar": set()}
        footer = None
        for line in source:
            item = json.loads(line)
            if footer is not None:
                raise ValueError("CAPTURE_TRAILING_AFTER_END")
            if "capture_end" in item:
                footer = item["capture_end"]
                if not isinstance(footer, dict):
                    raise ValueError("CAPTURE_END_INVALID")
                continue
            payload = item["payload"]
            if payload.get("order_book_id") != contract:
                raise ValueError("CAPTURE_OWNER_MISMATCH")
            if payload["channel"] == f"bar_{contract}":
                result = _canonical_bar_from_raw_feed(payload)
                if result is None:
                    diagnostics["bar_invalid"] += 1
                    continue
                _, bar = result
                if bar.trading_day != day:
                    raise ValueError("CAPTURE_TRADING_DAY_MISMATCH")
                prior = direct_bars.setdefault(bar.bar_end, bar)
                if prior != bar:
                    diagnostics["bar_conflict"] += 1
                    conflicts["bar"].add(bar.bar_end)
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
                    conflicts["tick"].add(bar.bar_end)
    return (symbol, contract, day, sessions), identity, tick_bars, direct_bars, diagnostics, conflicts, footer


def _coverage(expected, bars):
    actual = set(bars)
    return {
        "covered": len(expected & actual),
        "missing": [end.isoformat() for end in sorted(expected - actual)],
        "unexpected": [end.isoformat() for end in sorted(actual - expected)],
    }


def replay(path, settings_path=None, *, provider_history=False, additional_captures=()):
    tick_bars, direct_bars = {}, {}
    diagnostics: Counter[str] = Counter()
    captures = []
    scope = None
    seen = set()
    conflicts = {"tick": set(), "bar": set()}
    for shard in (path, *additional_captures):
        shard_scope, identity, ticks, live, counters, shard_conflicts, footer = _read_capture(
            shard, provider_history=provider_history,
        )
        if scope is not None and scope != shard_scope:
            raise ValueError("CAPTURE_SCOPE_MISMATCH")
        scope = shard_scope
        if identity in seen:
            raise ValueError("CAPTURE_DUPLICATE_SHARD")
        seen.add(identity)
        captures.append({"sha256": identity, "end": footer,
                         "first_proved": min(ticks).isoformat() if ticks else None,
                         "last_proved": max(ticks).isoformat() if ticks else None})
        diagnostics.update(counters)
        for label, target, rows in (("tick", tick_bars, ticks), ("bar", direct_bars, live)):
            conflicts[label].update(shard_conflicts[label])
            for end, bar in rows.items():
                if target.setdefault(end, bar) != bar:
                    diagnostics[f"{label}_shard_conflict"] += 1
    for label, target in (("tick", tick_bars), ("bar", direct_bars)):
        for end in conflicts[label]:
            target.pop(end, None)
    assert scope is not None
    symbol, contract, day, sessions = scope
    expected = set(expected_intraday_ends(sessions, BarFrequency.M1))
    tick_coverage = _coverage(expected, tick_bars)
    live_coverage = _coverage(expected, direct_bars)
    result = {
        "capture_sha256": captures[0]["sha256"],
        "captures": captures,
        "contract": contract, "trading_day": str(day),
        "tick_completed": len(tick_bars), "live_1m": len(direct_bars),
        "diagnostics": dict(sorted(diagnostics.items())),
        "conflicting_endpoints": {label: [end.isoformat() for end in sorted(ends)]
                                  for label, ends in conflicts.items()},
        "tick_to_live": compare(tick_bars, direct_bars),
        "endpoint_coverage": {"expected": len(expected), "tick": tick_coverage, "live": live_coverage},
    }
    if settings_path is not None:
        try:
            history = history_rows(settings_path, symbol=symbol, contract=contract, day=day,
                                   provider_history=provider_history)
        except MarketDataError as exc:
            result["authority_readback"] = exc.code
        else:
            result["endpoint_coverage"]["historical"] = _coverage(expected, history)
            result["authority"] = "rqdata_ready_history" if provider_history else "canonical"
            result["authority_day_rows"] = len(history)
            result["authority_input_sha256"] = sha256(repr(tuple(sorted(history.items()))).encode()).hexdigest()
            result["tick_to_authority"] = compare(tick_bars, history)
            result["live_to_authority"] = compare(direct_bars, history)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--capture-shard", type=Path, action="append", default=[],
                        help="another capture of the same contract, day and Sessions; repeat as needed")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--provider-history", action="store_true",
                        help="make one bounded read-only RQData request after current day is ready")
    args = parser.parse_args()
    if args.provider_history and args.settings is None:
        parser.error("--provider-history requires private provider settings")
    if len(args.capture_shard) > 48:
        parser.error("at most 48 additional shards")
    try:
        result = replay(args.capture, args.settings, provider_history=args.provider_history,
                        additional_captures=args.capture_shard)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 2 if any(result["conflicting_endpoints"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
