"""Same-day geometry only; visible publication is an unverified historical proxy."""

import argparse
import hashlib
import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from pathlib import Path

CASES = [
    (
        "E46",
        "fg",
        "FG2701",
        "2026-09-28T10:25:00+08:00",
        [("watershed", "899", "918"), ("conditional-extension", "878", "878")],
    ),
    (
        "E47",
        "jm",
        "JM2701",
        "2026-09-28T10:19:00+08:00",
        [("conditional-extension", "1428", "1431.5")],
    ),
    (
        "E48",
        "jm",
        "JM2701",
        "2026-10-09T10:14:00+08:00",
        [
            ("short-target", "1531.5", "1542.5"),
            ("conditional-trend-target", "1554", "1571"),
            ("weak-start", "1517.5", "1517.5"),
            ("M-defense", "1507.5", "1512.5"),
        ],
    ),
]


def geometry(bars, published, lower, upper):
    """Require publication strictly before start of each completed 1m bar."""
    eligible = [b for b in bars if published < b.bar_end - timedelta(minutes=1)]

    def first(predicate):
        return next((b.bar_end.isoformat() for b in eligible if predicate(b)), None)

    return {
        "eligible_bars": len(eligible),
        "first_lower_touch": first(lambda b: b.low <= lower <= b.high),
        "first_upper_touch": first(lambda b: b.low <= upper <= b.high),
        "first_close_above": first(lambda b: b.close > upper),
        "first_close_below": first(lambda b: b.close < lower),
        "minimum_low": str(min(b.low for b in eligible)) if eligible else None,
        "maximum_high": str(max(b.high for b in eligible)) if eligible else None,
        "stand_firm": "UNKNOWN",
        "condition_satisfied": None,
        "signal": "UNKNOWN",
        "action_match": None,
    }


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
    rows = []
    for source, symbol, contract, publication, nodes in CASES:
        row = {
            "source": source,
            "contract": contract,
            "visible_publication": publication,
            "historical_known_at_verified": False,
            "frequency": "1m",
            "source_signal_period": "UNKNOWN",
            "audit_window": "same trading day remainder",
            "author_zone_expiry": "UNKNOWN",
            "status": "BLOCKED",
        }
        try:
            published = datetime.fromisoformat(publication)
            day = date.fromisoformat(publication[:10])
            with (
                SessionLocal() as session,
                readonly_transaction(session, timeout_seconds=120),
            ):
                result = read_local(
                    build_market_data_service(session), symbol, contract, "1m", day, day
                )
                bars = result.bars
                raw = [
                    [
                        b.bar_end.isoformat(),
                        str(b.open),
                        str(b.high),
                        str(b.low),
                        str(b.close),
                    ]
                    for b in bars
                ]
                observations = [
                    dict(
                        id=name,
                        lower=lo,
                        upper=hi,
                        **geometry(bars, published, Decimal(lo), Decimal(hi)),
                    )
                    for name, lo, hi in nodes
                ]
                identity = dict(result.request_identity)
            # Only success after transaction exit proves readable state.
            row.update(
                status="GEOMETRY_ONLY",
                source_bar_count=len(bars),
                input_snapshot_hash=hashlib.sha256(
                    json.dumps(raw, separators=(",", ":")).encode()
                ).hexdigest(),
                request_identity=identity,
                nodes=observations,
            )
        except MarketDataError as exc:
            row["reason"] = exc.code
        except Exception as exc:
            row.update(reason="LOCAL_READ_UNVERIFIED", error_type=type(exc).__name__)
        rows.append(row)
    report = {
        "identity": "lms405-node-audit-v0.1",
        "results": rows,
        "causal_acceptance": False,
        "complete_action_cases": 0,
        "performance": None,
        "warning": "Current visible text uses publication as an unverified historical proxy; geometry is neither stand-firm nor author execution.",
        "no_download": True,
        "no_production_write": True,
    }
    (args.output / "node-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
