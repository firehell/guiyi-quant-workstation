"""Contrast M classification, failed excursions and trend recovery in RU and SH."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import geometry_events
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_v_zone_progress import observations
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

APRIL_DIVIDER = ("RU2609", "2026-04-27", None, "S5292366539525356", (("divider", "LONG", 17130, 17210),))
JUNE_M = ("RU2609", "2026-06-23", None, "S5313021782003245",
          (("divider", "SHORT", 17850, 17930), ("strong_side_target", "SHORT", 17555, 17670)))
CASES = (
    APRIL_DIVIDER,
    ("RU2609", "2026-05-27", None, "S5303234774436285", (("divider", "LONG", 17255, 17370),)),
    ("SH2607", "2026-06-05", None, "S5306498940930568", (("weak_side_m", "LONG", 1950, 1964),)),
    JUNE_M,
    ("RU2701", "2026-10-26", "A5357264793370945", "A5358325972992140",
     (("short_trend_recovery", "SHORT", 19505, 19570),)),
    ("RU2701", "2026-10-27", "A5358325972992140", "A5358686695981271",
     (("short_trend_recovery", "SHORT", 19505, 19570),)),
    ("RU2701", "2026-10-28", "A5358686695981271", "S5359046580243515",
     (("weak_side_m", "LONG", 19515, 19610),)),
)
VERSION_SCOPE_CASES = (
    ("RU2609", "2026-04-21", None, "S5290187538302824", (("upper_pa", "LONG", 17130, 17210),)),
    ("RU2609", "2026-04-24", None, "S5291275490430891", (("bearish_test_area", "SHORT", 16930, 17040),)),
    APRIL_DIVIDER,
    JUNE_M,
)
# These labels describe what the source says. None of them identifies a position lot or fill.
VERSION_DISCOURSE = {
    "2026-04-21": dict(two_unnamed_systems="PRIOR_M_PARTICIPATION_REPORTED", known_version=None,
                       protect_or_limit_add="GUIDANCE"),
    "2026-04-24": {"4.0.5": "LOCK_REPORTED", "5.0": "TAKE_PROFIT_REPORTED"},
    "2026-04-27": dict(m="DAY_SESSION_PROBE_DESCRIPTION", known_version=None),
    "2026-06-23": {"4.0.5": "INTRADAY_M_ROLE", "5.0": "TRIAL_STOP_ROLE", "cross_system_hedge_known": None},
}
VARIANTS = ((1, 1), (5, 1), (5, 5))


def close_returns(bars, band):
    """Read closes back inside after an outside close, retaining any session break."""
    lower, upper = band
    result = []
    for previous, current in zip(bars, bars[1:]):
        if lower <= current.close <= upper and not lower <= previous.close <= upper:
            result.append(dict(
                previous_close_at=previous.end, previous_close=previous.close,
                return_at=current.end, close=current.close,
                from_side="ABOVE" if previous.close > upper else "BELOW",
                adjacent=previous.end == current.start,
            ))
    return result


def compare_band(series, start, cutoff, side, band):
    minutes = series[1]
    price = observations(minutes, band, side)
    lower, upper = band
    far = price["far"]
    return dict(
        band=band, side=side, price=price,
        minute_close_returns=close_returns(minutes, band),
        five_minute_close_returns=close_returns(series[5], band),
        terminal_run={f"{period}m": strict_runs(rows, far, side).get(rows[-1].end)
                      for period, rows in series.items()},
        geometry={
            f"{shape}m_to_{confirmation}m": [
                event | dict(inside=lower <= event["close"] <= upper,
                             strictly_beyond_far=(event["close"] > far if side == "LONG" else event["close"] < far))
                for event in geometry_events(series, shape, confirmation, start=start, as_of=cutoff, side=side)
            ] for shape, confirmation in VARIANTS
        },
    )


def study(session, market, *, version_scope=False):
    index = input_sources()
    cases = {}
    selected_cases = VERSION_SCOPE_CASES if version_scope else CASES
    for contract, day, plan_id, label_id, zones in selected_cases:
        raw, series = read_pair(session, market, contract, (date.fromisoformat(day),))
        minutes = series[1]
        start, close = minutes[0].start, at(f"{day}T15:00")
        cutoff = close + 2 * US
        label = load_source(index, label_id)
        zone_source = load_source(index, plan_id) if plan_id else label
        label_time = datetime.fromisoformat(label["published_at"]).astimezone(close.tzinfo)
        zone_time = datetime.fromisoformat(zone_source["published_at"])
        if minutes[-1].end != close or label_time.date() != close.date() or label_time <= cutoff:
            raise ValueError("M_CLASSIFICATION_WINDOW_MISMATCH")
        if plan_id and zone_time.replace(second=0, microsecond=0) + ONE >= start:
            raise ValueError("M_CLASSIFICATION_PLAN_NOT_BEFORE_SESSION")
        low_bar = min(minutes, key=lambda bar: bar.low)
        high_bar = max(minutes, key=lambda bar: bar.high)
        cases[day] = dict(
            contract=contract, start=start, cutoff_exclusive=cutoff, label_id=label_id, label=label,
            zone_source_id=plan_id or label_id, zone_source=zone_source,
            zone_timing="DISPLAYED_PRIOR_PLAN_HISTORY_UNVERIFIED" if plan_id else "RETROSPECTIVE_DISCLOSURE",
            open=minutes[0].open, low=low_bar.low, low_bar_end=low_bar.end,
            high=high_bar.high, high_bar_end=high_bar.end,
            close=minutes[-1].close, market={
                f"{period}m": dict(count=len(bars), sha256=bars_sha(bars)) for period, bars in raw.items()
            },
            bands={role: compare_band(series, start, cutoff, side, (Decimal(low), Decimal(high)))
                   for role, side, low, high in zones},
        )
        if version_scope:
            cases[day].update(author_disclosure=VERSION_DISCOURSE[day], author_position=None, author_action_at=None)
    version = "lms405-rubber-version-scope-v1" if version_scope else "lms405-rubber-m-classification-v1"
    return dict(version=version, cases=cases, historical_text_versions_verified=False,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version-scope", action="store_true", help="Compare disclosures with and without named versions.")
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), version_scope=args.version_scope)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError):
        parser.exit(2, "M_CLASSIFICATION_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
