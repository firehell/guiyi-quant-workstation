"""Read-only period coverage and disclosed day extrema; never infer author bars."""

import argparse
import hashlib
import json
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def daytime_extrema(bars, day):
    """Explicit day-session comparison only, not full trading-day or K parity."""
    selected = [
        b
        for b in bars
        if b.bar_end.astimezone(SHANGHAI).date() == day
        and time(9) < b.bar_end.astimezone(SHANGHAI).time() <= time(15)
    ]
    return {
        "bar_count": len(selected),
        "high": str(max(b.high for b in selected)) if selected else None,
        "low": str(min(b.low for b in selected)) if selected else None,
    }


def compare_extrema(observed, author_low, author_high):
    """Price deltas only; equality cannot certify bar/vendor/signal parity."""
    return {
        "low_price_delta": str(Decimal(observed["low"]) - author_low)
        if observed["low"] is not None
        else None,
        "high_price_delta": str(Decimal(observed["high"]) - author_high)
        if observed["high"] is not None
        else None,
        "bar_ohlc_parity": "UNKNOWN",
        "author_time_basis_verified": False,
        "signal_eligible": False,
    }


def audit_request(
    session_factory,
    transaction,
    market_factory,
    reader,
    symbol,
    contract,
    frequency,
    start,
    end,
    error_class,
):
    row = dict(
        contract=contract,
        frequency=frequency,
        window=[start.isoformat(), end.isoformat()],
        status="BLOCKED",
        author_period_verified=False,
        signal_eligible=False,
    )
    try:
        with session_factory() as session, transaction(session, timeout_seconds=120):
            result = reader(
                market_factory(session), symbol, contract, frequency, start, end
            )
            bars = result.bars
            encoded = json.dumps(
                [
                    [
                        b.bar_end.isoformat(),
                        str(b.open),
                        str(b.high),
                        str(b.low),
                        str(b.close),
                    ]
                    for b in bars
                ],
                separators=(",", ":"),
            ).encode()
            success = dict(
                bar_count=len(bars),
                request_identity=dict(result.request_identity),
                input_snapshot_hash=hashlib.sha256(encoded).hexdigest(),
                coverage=[x.isoformat() for x in result.coverage]
                if result.coverage
                else None,
            )
            if contract == "JM2701" and frequency == "1m":
                extrema = daytime_extrema(bars, date(2026, 9, 21))
                success["E51"] = dict(
                    basis="Shanghai calendar-day 09:00 < bar_end <= 15:00; night excluded",
                    source="E51",
                    author_low="1487",
                    author_high="1533.5",
                    **extrema,
                    **compare_extrema(extrema, Decimal("1487"), Decimal("1533.5")),
                )
                full_day = reader(
                    market_factory(session),
                    symbol,
                    contract,
                    frequency,
                    date(2026, 9, 21),
                    date(2026, 9, 21),
                )
                whole = {
                    "bar_count": len(full_day.bars),
                    "low": str(min(b.low for b in full_day.bars))
                    if full_day.bars
                    else None,
                    "high": str(max(b.high for b in full_day.bars))
                    if full_day.bars
                    else None,
                }
                success["E51_trading_day"] = dict(
                    basis="MarketDataService trading day 2026-09-21, including preceding night",
                    request_identity=dict(full_day.request_identity),
                    source="E51",
                    author_low="1487",
                    author_high="1533.5",
                    **whole,
                    **compare_extrema(whole, Decimal("1487"), Decimal("1533.5")),
                )
        # Failed transaction exit must not publish readable evidence.
        row.update(status="WINDOW_READABLE", **success)
    except error_class as exc:
        row["reason"] = exc.code
    except Exception as exc:
        row.update(reason="LOCAL_READ_UNVERIFIED", error_type=type(exc).__name__)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv

    if not args.env_file.is_file():
        parser.error("ENV_FILE_MISSING")
    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from lms405_replay import read_local

    args.output.mkdir(parents=True, exist_ok=False)
    rows = [
        audit_request(
            SessionLocal,
            readonly_transaction,
            build_market_data_service,
            read_local,
            symbol,
            contract,
            frequency,
            date(2026, 9, 21),
            date(2026, 10, 9),
            MarketDataError,
        )
        for symbol, contract in [("fg", "FG2701"), ("jm", "JM2701")]
        for frequency in ["1m", "5m", "15m"]
    ]
    report = dict(
        identity="lms405-alignment-audit-v0.1",
        results=rows,
        no_download=True,
        no_production_write=True,
        author_bar_samples=0,
        signal_matches=None,
        action_matches=None,
        performance=None,
    )
    (args.output / "alignment-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
