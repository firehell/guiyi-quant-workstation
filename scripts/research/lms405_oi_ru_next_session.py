"""Check price conditions after the OI and RU night display and an RU control."""

import argparse
from datetime import date, datetime
from pathlib import Path

from lms405_counter_m_exit_clocks import observe
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, check_images, retention_row
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded

NIGHT = "WRoEvasxQR"
CLOSE = "U03"
DAY_RECAP = "WRoLeVhPQ1"
RU_RECAP = "S5359046580243515"
RU_CONTROL = "S5353606200165081"
OI_PLAN = "A5358686423089344"
RU_PLAN = "A5358686695981271"
DAY = date(2026, 10, 28)
OCTOBER_LEVELS = {
    "OI2701": (("range_divider_near", "10240"), ("range_divider_far", "10283"),
               ("first_long_target_near", "10321"), ("first_long_target_far", "10356")),
    "RU2701": (("protection_near", "19360"), ("protection_far", "19405"),
               ("m_near", "19515"), ("m_far", "19610"),
               ("extreme_m_near", "19765"), ("extreme_m_far", "19970")),
}
CONTROL_LEVELS = (("prior_m_near", "20640"), ("prior_m_far", "20530"),
                  ("next_protection_near", "20905"), ("next_protection_far", "20765"))


def market_identity(series):
    return {str(p): dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}


def study(session, market):
    frozen = verified_json(RETENTION, RETENTION_SHA)
    refs = frozen["snapshot_sources"]
    check_images(refs[CLOSE], refs[NIGHT])
    index = input_sources()
    sources = {key: load_source(index, key) for key in (CLOSE, NIGHT, DAY_RECAP, OI_PLAN, RU_PLAN, RU_RECAP, RU_CONTROL)}
    night_published = datetime.fromisoformat(sources[NIGHT]["published_at"])
    day_open = at(f"{DAY}T09:00")
    results = {}
    for contract, levels in OCTOBER_LEVELS.items():
        plan = OI_PLAN if contract == "OI2701" else RU_PLAN
        series = read_window(session, market, contract, DAY)
        first, last = series[1][0].start, series[1][-1].end
        fingerprints = market_identity(series)
        if fingerprints["1"] != frozen["contracts"][contract]["market"][str(DAY)]:
            raise ValueError("LMS_OI_RU_MARKET_CHANGED")
        if not (datetime.fromisoformat(sources[plan]["published_at"]) < first < night_published < day_open
                < last < datetime.fromisoformat(sources[DAY_RECAP]["published_at"])):
            raise ValueError("LMS_OI_RU_SOURCE_ORDER_CHANGED")
        prior_short = retention_row(frozen, contract, CLOSE, NIGHT, "short")
        new_long = retention_row(frozen, contract, CLOSE, NIGHT, "long")
        if (new_long["earlier_leg"] is not None
                or new_long["later_leg"]["quantity"] != new_long["later_leg"]["today_quantity"]
                or prior_short["retained"] != [prior_short["later_leg"]["quantity"]]):
            raise ValueError("LMS_OI_RU_LEG_INPUT_CHANGED")
        later_day = observe(series, day_open, last + 2 * US, "LONG", levels)
        # Observe a falling return to the same reference after an actual upward
        # crossing. The reference is not an author-authorized exit threshold.
        return_levels = levels[:1] if contract == "OI2701" else levels[2:4]
        gate_role = "range_divider_near" if contract == "OI2701" else "m_far"
        gate = later_day["price_observations"][gate_role]["first_fresh_cross"]
        observation = (observe(series, gate["at"] + US, last + 2 * US, "SHORT", return_levels)
                       if gate and any(b.start > gate["at"] for b in series[1]) else None)
        results[contract] = dict(
            plan=plan, recap=RU_RECAP if contract == "RU2701" else None,
            market=fingerprints, short_retention_through_display=prior_short, long_display=new_long,
            night_before_display=observe(series, first, night_published, "LONG", levels),
            night_scope="BEFORE_POST_DISPLAY_MINUTE_SNAPSHOT_TIME_UNVERIFIED",
            later_day=later_day, later_return_sensitivity=observation,
            later_return_scope="PRICE_COMPARISON_ACROSS_SESSION_SEGMENTS_WITHOUT_CARRYING_PERMISSION",
            author_next_day_position=None, actual_exit_at=None, m_participation=None,
        )

    control = {}
    published = datetime.fromisoformat(sources[RU_CONTROL]["published_at"])
    for reported_day in (date(2026, 10, 13), date(2026, 10, 14)):
        series = read_window(session, market, "RU2701", reported_day)
        start, end = series[1][0].start, series[1][-1].end
        if end < published:
            levels = CONTROL_LEVELS
            role = "RETROSPECTIVE_BOTH_LEVELS_PRIOR_LOCK_LOCATION_UNKNOWN"
        elif published < start:
            levels = CONTROL_LEVELS[2:]
            role = "NEXT_SESSION_SENSITIVITY_FOR_NEW_PROTECTION_ONLY"
        else:
            raise ValueError("LMS_OI_RU_CONTROL_ORDER_CHANGED")
        control[str(reported_day)] = dict(
            source_role=role, observed=observe(series, start, end + 2 * US, "SHORT", levels),
            market=market_identity(series), historical_revision_verified=False, author_405_identity=None,
        )
    return dict(
        version="lms405-oi-ru-next-session-v1", sources=sources, display=refs[NIGHT], earlier_display=refs[CLOSE],
        retention_reference_sha256=RETENTION_SHA, cases=results, ru_control=control,
        short_retention_assumptions=frozen["assumptions"], account_continuity_verified=False,
        historical_plan_revision_verified=False, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "LMS_OI_RU_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
