"""Replay D's original September window using its verified exchange trading days."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as kernel
from lms405_day_range_short_study import (
    FIELDS, FROZEN_CODE, FROZEN_RULE, SEAL, SEAL_SHA, SHANGHAI,
    field_totals, remove_worst_product, require, save_csv, study, summarize_delta,
)
from lms405_original_leg_study import verified_json
from lms_near405_replay import encoded, sha

BASE_REPORT_SHA = "080efb51f21d37c9e3929e8c685e1d7c8ae20869cbbfac07dd4c418a5dc3f5a8"
D_RUNNER = Path("scripts/research/lms405_day_range_short_study.py")
D_RUNNER_SHA = "426c679d71afa407a3ea67cfa2b471ae8ab2d38c38b8bf2077fd27b3c158c5ff"
WINDOW = "sep21"
EXCHANGES = {"I2701": "DCE", "OI2701": "CZCE", "RU2701": "SHFE", "SA2701": "CZCE", "V2701": "DCE"}
NOTICES = {
    "DCE": "https://finance.sina.com.cn/roll/2026-09-14/doc-iniruxus9362070.shtml",
    "CZCE": "https://www.hongtaqh.com/wsyyt/ywgg/202512/20251218_11350.html",
    "SHFE": "https://www.shfe.com.cn/publicnotice/notice/202609/t20260921_833503.html",
}


def verify_calendar(session_factory, window):
    from sqlalchemy import select
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.session_clock import SessionClockError, resolved_session_windows_for_trading_day
    from app.models import TradingCalendar

    dates = tuple(map(date.fromisoformat, window["trading_days"]))
    trading_days = dates[:-1]
    require(dates == tuple(date(2026, 9, day) for day in range(21, 26))
            and set(window["contracts"]) == set(EXCHANGES), "original date and contract scope")
    evidence = {}
    with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
        market = build_market_data_service(session)
        for contract in window["contracts"]:
            symbol = contract[:-4].lower()
            exchange = market.catalog.exchange_for_symbol(symbol)
            require(exchange == EXCHANGES[contract], (contract, "exchange"))
            rows = session.scalars(select(TradingCalendar).where(
                TradingCalendar.exchange_code == exchange, TradingCalendar.trade_date.in_(dates),
            ).order_by(TradingCalendar.trade_date)).all()
            require(tuple(row.trade_date for row in rows) == dates
                    and tuple((r.is_trading_day, r.has_night_session) for r in rows)
                    == ((True, True),) * 4 + ((False, False),)
                    and all(r.provider == "rqdata" for r in rows), (contract, "exchange calendar facts"))
            days = {}
            for day in trading_days:
                sessions = resolved_session_windows_for_trading_day(
                    session, exchange=exchange, symbol=symbol, trading_day=day,
                )
                days[day.isoformat()] = [
                    dict(start=s.window.start.astimezone(SHANGHAI), end=s.window.end.astimezone(SHANGHAI),
                         night=s.is_night) for s in sessions
                ]
            try:
                resolved_session_windows_for_trading_day(
                    session, exchange=exchange, symbol=symbol, trading_day=dates[-1],
                )
            except SessionClockError as error:
                require(error.code == "TRADING_SESSION_MISSING", (contract, "closure readback"))
            else:
                raise ValueError(f"UNEXPECTED_SESSION_ON_EXCHANGE_HOLIDAY: {contract}")
            evidence[contract] = dict(exchange=exchange, notice=NOTICES[exchange], provider="rqdata",
                                      closed_day=dates[-1], closed_day_resolver="TRADING_SESSION_MISSING",
                                      session_windows=days)
    return list(map(date.isoformat, trading_days)), evidence


def combine(base, supplement):
    closed = [{**r, **{field: Decimal(r[field]) for field in FIELDS}}
              for r in base["cohort_closed"] + supplement["cohort_closed"]]
    identities = {(r["window"], r["contract"], r["cycle_id"]) for r in closed}
    require(len(identities) == len(closed), "cohort deduplication")
    hypothesis = remove_worst_product(closed)
    sample_windows = {r["window"] for r in closed}
    enough = len(closed) >= 15 and len(hypothesis["by_product"]) >= 3 and len(sample_windows) >= 2
    mean = hypothesis["all"]["averages"]["net"]
    trimmed = hypothesis["without_worst"]["averages"]["net"]
    supported = enough and mean < 0 and trimmed < 0
    hypothesis.update(conclusion="SUPPORTED" if supported else "NOT_SUPPORTED" if enough else "INSUFFICIENT_SAMPLE",
                      sample_windows=sorted(sample_windows))

    segments = [{**s, "net": Decimal(s["net"])} for s in base["segments"] + supplement["segments"]]
    path = summarize_delta(segments, "net", lambda r: (r["window"], r["contract"], r["start"]))
    side_totals = {}
    for side in ("baseline", "candidate"):
        side_totals[side] = field_totals([
            {k: Decimal(v) for k, v in r["path"]["totals"][side].items()} for r in (base, supplement)
        ], (*FIELDS, "realized_gross", "unrealized", "closed_cycles", "operations"))
    require(path["net"] == side_totals["candidate"]["net"] - side_totals["baseline"]["net"], "combined cash bridge")
    skip_windows = set(base["path"]["skip_windows"]) | set(supplement["path"]["skip_windows"])
    path.update(
        conclusion="SUPPORTED" if len(skip_windows) >= 2 and min(path["net"], path["net_without_largest"]) > 0
                   else "INSUFFICIENT_SAMPLE" if len(skip_windows) < 2 else "NOT_SUPPORTED",
        skip_windows=sorted(skip_windows), totals=side_totals,
    )
    return dict(hypothesis=hypothesis, path=path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("env-file", "base-report", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    require(kernel.RULE_HASH == FROZEN_RULE and all(sha(Path(p).read_bytes()) == digest
            for p, digest in FROZEN_CODE.items()) and sha(D_RUNNER.read_bytes()) == D_RUNNER_SHA, "unchanged D code")
    base, seal = verified_json(args.base_report, BASE_REPORT_SHA), verified_json(SEAL, SEAL_SHA)
    window = next(w for w in seal["windows"] if w["id"] == WINDOW)
    omitted = [r for r in base["coverage"] if r["window"] == WINDOW]
    require({r["contract"] for r in omitted if r["reason"] == "TRADING_SESSION_MISSING"} == set(EXCHANGES),
            "original excluded windows")

    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    active, calendar = verify_calendar(SessionLocal, window)
    replay_scope = seal | dict(windows=[window | dict(trading_days=active)])
    supplement = study(SessionLocal, replay_scope)
    result = dict(base_report_sha256=BASE_REPORT_SHA, frozen_runner_sha256=D_RUNNER_SHA,
                  original_calendar_window=window["trading_days"], actual_trading_days=active, calendar=calendar,
                  supplement=supplement, combined=combine(base, supplement))
    args.output.mkdir()
    with (args.output / "report.json").open("x", encoding="utf-8") as output:
        output.write(encoded(result))
    for name in ("cohort_closed", "cohort_terminal", "segments", "operations", "skipped"):
        save_csv(args.output / f"{name.replace('_', '-')}.csv", supplement[name])
    save_csv(args.output / "path-windows.csv", [
        {k: v for k, v in r.items() if k not in {"baseline", "candidate"}}
        | {f"{side}_{k}": r[side][k] for side in ("baseline", "candidate")
           for k in (*FIELDS, "realized_gross", "unrealized", "closed_cycles", "operations")}
        for r in supplement["windows"]
    ])


if __name__ == "__main__":
    main()
