"""Compare prior-session and fresh-night conditions for three visible short legs."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_common_protection_window import enclosed_averages, summary
from lms405_fg_sa_case import FIVE, ONE, at, identity
from lms405_protection_timeframes import geometry_events
from lms405_replay import display, ohlc, read_session_series
from lms405_resonance_cases import scope_path
from lms405_sa_reentry_study import NEXT, PLANS, SHORT_DAY, SHORT_IMAGES, SHORT_PLANS, price_compatibility, source_evidence
from lms_near405_replay import encoded

DAYS = (NEXT, SHORT_DAY)
OPEN = at("26T21:00")
POST = at("26T22:04")
SNAPSHOT = "WRov1j6e10"
PRIOR_PLAN = "A5357264059367516"
NIGHT_PLAN = "A5358325549629506"
LEVELS = {
    "FG2701": ("828", "832", "832"),
    "JM2701": ("1392", "1415.5", "1372"),
    "SA2701": ("951", "957", "960"),
}
CONTROL_LEGS = {"OI2701": ("SHORT", "10340"), "V2701": ("LONG", "5117")}
CONTROL_HASHES = {
    "OI2701": "24c78894c36782fa192f13e13925db2ccbf3f99144e43a646a363705e853524f",
    "V2701": "d46d97c0428b16b608c0a1525d698f1d588a7c60e2c200e8d128d7f410ffe213",
}
MARKET_HASHES = {
    "FG2701": (
        "ac9cc960d67a57f334c2a98b192daf738d882ff1e9d7761026f54a8e50d4b468",
        "179814c17342556b7b21e15dd4a36a5250033cf4303c2e6c5ebf7d42c2678f91",
    ),
    "JM2701": (
        "3801cdf882185c05cd1142a68068a8c90e5a358d8537ee0994beebe54379a169",
        "d3950a0c7398a6875ced9baa106e155842bec492cecf9ff8c7a505b323230fd9",
    ),
    "SA2701": (
        "4ee4c9a0563990727d089441c11c9ea30c4b5c39a779c38f8cdc70fb72bf1fea",
        "010d3c99fd3e1cbcf7b2616fdef1b16f88a4336aa500ef91cbc22dfbbe574beb",
    ),
}
ARCHIVE_PLANS = {
    PRIOR_PLAN: PLANS[PRIOR_PLAN],
    NIGHT_PLAN: SHORT_PLANS[NIGHT_PLAN],
    "WRosWjuXsq": "cfcccad73460812992f61e0d1b7dd90bbb01c3565130c1dada3ca1da4e04c41d",
    "WRoCswszPF": "afebf72a690227e1972c21e9d1a10b160b82093a46e314f9018afb40aeb3d06c",
    "WRoCqMClgV": "d8b0b383ff14783389ca23e85d85bda4a23b3a11b6d1ac65aa42f2c44da59265",
    "WRoCtNmpu8": SHORT_PLANS["WRoCtNmpu8"],
}


def window(bars, trading_day, start, cutoff):
    return [b for b in bars if b.trading_day == trading_day and start < b.bar_end < cutoff]


def wait_windows(minutes, night, band, average):
    """An intraminute touch includes its own bar; a close must precede the next bar."""
    lower, upper = band
    scenarios = (
        ("night_touch", next((b for b in night if b.low <= upper and b.high >= lower), None), ONE),
        ("night_close_below_upper", next((b for b in night if b.close < upper), None), 0 * ONE),
        ("night_close_below_lower", next((b for b in night if b.close < lower), None), 0 * ONE),
    )
    return {
        name: None if bar is None else dict(
            bar_end=display(bar.bar_end), close=str(bar.close),
            price=price_compatibility(minutes, SHORT_DAY, bar.bar_end - offset, POST + 2 * ONE, average),
        ) for name, bar, offset in scenarios
    }


def check_contract(contract, minutes, fives):
    frozen = {"1m": identity(minutes), "5m": identity(fives)}
    if tuple(item["ohlc_sha256"] for item in frozen.values()) != MARKET_HASHES[contract]:
        raise ValueError("CARRY_STUDY_FROZEN_MARKET_INPUT_CHANGED")
    lower, upper, average = map(Decimal, LEVELS[contract])
    band = (lower, upper)
    day = window(minutes, NEXT, at("26T09:00"), at("26T15:01"))
    night = window(minutes, SHORT_DAY, OPEN, POST)
    next_day = window(minutes, SHORT_DAY, at("27T09:00"), at("27T15:01"))
    full_day = [b for b in minutes if b.trading_day == SHORT_DAY]
    if (len(day), len(night), len(next_day), len(full_day)) != (225, 63, 225, 345):
        raise ValueError("SA_FG_JM_SESSION_COUNTS_CHANGED")
    night_series = {
        1: [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in night],
        5: [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE)
            for b in window(fives, SHORT_DAY, OPEN, POST)],
    }
    signals = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = geometry_events(night_series, shape, confirm, start=OPEN, as_of=POST, side="SHORT")
        signals[f"{shape}m_to_{confirm}m"] = dict(
            events=events,
            after_first_confirmation_price=price_compatibility(
                minutes, SHORT_DAY, events[0]["confirmed_at"], POST + 2 * ONE, average,
            ) if events else None,
        )
    return dict(
        frozen_inputs=frozen, band=list(band), visible_short=dict(quantity="20", today_quantity="20", average=average),
        prior_session=scope_path(day, {"band": band}), night_before_post=scope_path(night, {"band": band}),
        price_before_post=price_compatibility(minutes, SHORT_DAY, OPEN, POST, average),
        night_waits=wait_windows(minutes, night, band, average), night_signals=signals,
        next_day_session=scope_path(next_day, {"band": band}), next_trading_day=scope_path(full_day, {"band": band}),
    ), night


def study(inputs, controls, evidence):
    publication = {key: datetime.fromisoformat(evidence[key]["published_at"]) for key in (PRIOR_PLAN, NIGHT_PLAN, SNAPSHOT)}
    if (not publication[PRIOR_PLAN] < at("26T09:00") < at("26T15:00") < publication[NIGHT_PLAN] < OPEN
            or publication[SNAPSHOT] != POST):
        raise ValueError("CARRY_STUDY_SOURCE_CHRONOLOGY_CHANGED")
    if inputs.keys() != LEVELS.keys() or controls.keys() != CONTROL_LEGS.keys():
        raise ValueError("CARRY_STUDY_CONTRACT_SCOPE_CHANGED")
    results, series = {}, {}
    for contract, (minute, five) in inputs.items():
        results[contract], series[contract] = check_contract(contract, minute, five)
    averages = {k: Decimal(row[-1]) for k, row in LEVELS.items()}
    intersection = set.intersection(*(set(row["price_before_post"]["single_price_compatible_minutes"])
                                     for row in results.values()))
    control_results, control_series = {}, {}
    for contract, (side, average) in CONTROL_LEGS.items():
        minutes = controls[contract]
        frozen = identity(minutes)
        if frozen["ohlc_sha256"] != CONTROL_HASHES[contract]:
            raise ValueError("CARRY_CONTROL_FROZEN_MARKET_INPUT_CHANGED")
        control_results[contract] = dict(
            frozen_1m=frozen, visible_leg=dict(side=side, quantity="40", today_quantity="40", average=average),
            price_before_post=price_compatibility(minutes, SHORT_DAY, OPEN, POST, average),
        )
        control_series[contract] = window(minutes, SHORT_DAY, OPEN, POST)
    all_minutes = {k: pair[0] for k, pair in inputs.items()} | controls
    broad_series = {k: window(bars, SHORT_DAY, OPEN, POST + 2 * ONE) for k, bars in all_minutes.items()}
    all_averages = averages | {k: Decimal(row[-1]) for k, row in CONTROL_LEGS.items()}
    return dict(
        version="lms405-session-carry-study-v1", prior_trading_day=NEXT.isoformat(), night_trading_day=SHORT_DAY.isoformat(),
        sources=evidence, contracts=results, common_price_windows=summary(enclosed_averages(series, averages)),
        same_minute_price_overlap=sorted(intersection),
        controls=control_results, obscured_today_average=["J2701"],
        five_leg_windows=dict(
            strict_before_post=summary(enclosed_averages(series | control_series, all_averages)),
            including_post_boundary=summary(enclosed_averages(broad_series, all_averages)),
        ),
        clock="PRICE_PATH_RETROSPECTIVE_NO_HISTORICAL_ARTICLE_REVISION",
        carry_permission=None, same_account_chain=None, trades=None,
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")

    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        evidence = source_evidence(ARCHIVE_PLANS, {SNAPSHOT: SHORT_IMAGES[SNAPSHOT]})
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            inputs = {contract: tuple(read_session_series(session, market, contract[:-4].lower(), contract,
                                                          frequency, period, DAYS)
                                      for frequency, period in (("1m", ONE), ("5m", FIVE))) for contract in LEVELS}
            controls = {contract: read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, DAYS)
                        for contract in CONTROL_LEGS}
        result = study(inputs, controls, evidence)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "CARRY_STUDY_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
