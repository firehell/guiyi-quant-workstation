"""Read-only price and position-display bounds around protection-plan changes."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_jm_divider_study import price_envelope
from lms405_m_permission_study import read_pair
from lms405_protection_timeframes import geometry_events
from lms405_replay import display
from lms405_right_side_study import US, at
from lms405_v_zone_progress import observations
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

INPUTS = {
    "oil_april": (
        "OI2609", ("2026-04-22", "2026-04-23"),
        "1a42654743d03e5091ec81b56261f9675ad7bda16e80c6973e38569c54047837",
    ),
    "oil_may": (
        "OI2609", ("2026-05-27", "2026-05-28", "2026-05-29"),
        "b882320647e76d9d31a02cf1ca367bbf4bd767375e38471af7239a322e90f25c",
    ),
    "soda_october": (
        "SH2701", ("2026-10-27",),
        "3d919342b223d370957d8c1d4b798d4c821bcf5691e12a36e3118d0d806dd66c",
    ),
}


def complete_window(minutes, start, cutoff):
    return [bar for bar in minutes if bar.start >= start and bar.end + US < cutoff]


def price_window(minutes, start, cutoff, side, levels):
    bars = complete_window(minutes, at(start), at(cutoff))
    if not bars:
        raise ValueError("PROTECTION_HANDOFF_WINDOW_EMPTY")
    return dict(start=at(start), cutoff_exclusive=at(cutoff), range=price_envelope(bars),
                levels={key: observations(bars, tuple(map(Decimal, band.split())), side)
                        for key, band in levels.items()})


def conditional_average_window(minutes, after_observation, cutoff, opening_average):
    # Exclude the bar that begins at the observation boundary. Its open may
    # precede the availability of that completed observation.
    eligible = complete_window(minutes, after_observation + US, cutoff)
    limits = price_envelope(eligible)
    containing = [display(b.end) for b in eligible if b.low <= opening_average <= b.high]
    return dict(after_observation=after_observation, price_envelope=limits,
                compatible=limits[0] <= opening_average <= limits[1] if limits else None,
                minutes_containing_mean=containing)


def compare_oil_april(minutes):
    post = "2026-04-22T10:21"
    return dict(
        sources=["S5290447639678222"], author_action_at=None,
        disclosure="STRONG_TARGET_REACHED_NEW_WEAK_SIDE_SIGNAL_SEARCH",
        completed_target=price_window(minutes, "2026-04-21T21:00", post, "LONG",
                                      {"strong_target": "9643 9657"}),
        new_protection=price_window(minutes, "2026-04-22T10:22", "2026-04-23T15:01", "SHORT",
                                    {"different_protection_range": "9596 9630"}),
    )


def compare_oil_may(minutes):
    levels = {"reused_candidate": "9739 9745", "other_completed_target": "9757 9792"}
    may27 = price_window(minutes, "2026-05-26T21:00", "2026-05-27T16:46", "LONG", levels)
    return dict(
        sources=["S5303228212185872", "S5303501070534706", "S5303501928533791"],
        author_action_at=None, same_position_across_days=None, author_may27_protection_band=None,
        may27_locked_report=may27 | dict(level_scope="NEXT_DAY_DISCLOSED_LEVELS_RETROSPECTIVE_ONLY"),
        protection_disclosure_scope="RELATED_EXCERPT_ONLY_FINAL_POLICY_UNKNOWN",
        may28_completed_targets=price_window(minutes, "2026-05-27T21:00", "2026-05-28T10:50", "LONG", levels),
        may28_protection_sensitivity=price_window(minutes, "2026-05-28T10:55", "2026-05-28T15:01", "SHORT",
                                                {"reused_candidate": levels["reused_candidate"]}),
        may29_same_level_sensitivity=price_window(minutes, "2026-05-28T21:00", "2026-05-29T15:01", "SHORT",
                                                 {"reused_candidate": levels["reused_candidate"]}),
    )


def compare_soda(series):
    minutes = series[1]
    post = "2026-10-26T21:57"
    after_post, cutoff = "2026-10-26T21:58", "2026-10-27T10:13"
    earlier_target = price_window(minutes, "2026-10-26T21:00", post, "SHORT",
                                 {"completed_target": "1498 1498", "next_target": "1483 1485"})
    new_target = price_window(minutes, after_post, cutoff, "SHORT", {"next_target": "1483 1485"})
    rebound = price_window(minutes, after_post, cutoff, "LONG",
                           {"reuse_1498_hypothesis": "1498 1498", "earlier_protection_band": "1516 1529"})
    gates = {
        "new_short_target_far_reach": new_target["levels"]["next_target"]["first_far_reach"],
        "rebound_above_completed_target": rebound["levels"]["reuse_1498_hypothesis"]["first_strict_close_beyond_far"],
        "strict_close_through_new_short_target": new_target["levels"]["next_target"]["first_strict_close_beyond_far"],
    }
    mean = Decimal("1490.1")
    whole = complete_window(minutes, series[1][0].start, at(cutoff))
    return dict(
        sources=["A5358325972992140", "WRouYm67Bc", "WRozNbg3en", "WRozPmaK10", "WRoAkcEppg"],
        prior_target=earlier_target, next_target=new_target, rebound_hypotheses=rebound,
        displayed_long_open_average=mean, price_envelope_before_photo_post=price_envelope(whole),
        author_action_at=None, author_new_protection_band=None, photo_time=None,
        conditional_whole_leg_average_checks={
            key: conditional_average_window(minutes, at(value), at(cutoff), mean) if value else None
            for key, value in gates.items()
        },
        long_shape_candidates={
            f"{shape}m_to_{confirmation}m": geometry_events(series, shape, confirmation,
                                                          start=at(after_post), as_of=at(cutoff), side="LONG")
            for shape, confirmation in ((1, 1), (5, 1), (5, 5))
        },
    )


def study(session, market):
    series, identity = {}, {}
    for key, (contract, days, digest) in INPUTS.items():
        raw, series[key] = read_pair(session, market, contract, tuple(map(date.fromisoformat, days)))
        identity[key] = {f"{p}m": dict(count=len(rows), sha256=bars_sha(rows)) for p, rows in raw.items()}
        if identity[key]["1m"]["sha256"] != digest:
            raise ValueError("PROTECTION_HANDOFF_FROZEN_MARKET_CHANGED")
    return dict(
        version="lms405-protection-handoff-study-v1", input_ohlc=identity,
        oil_april=compare_oil_april(series["oil_april"][1]), oil_may=compare_oil_may(series["oil_may"][1]),
        soda_october=compare_soda(series["soda_october"]),
        author_completion_formula=None, author_matches=None, admitted_author_samples=0,
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
        parser.exit(2, "PROTECTION_HANDOFF_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
