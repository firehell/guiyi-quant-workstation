"""Bound the SA2701 visible legs and compare entry explanations on frozen local bars."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_fg_sa_case import DAYS, FIVE, ONE, at, identity, price_path
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import geometry_events
from lms405_replay import display, keybar_windows, ohlc, read_session_series
from lms_near405_replay import encoded, sha

CONTRACT = "SA2701"
FIRST, NEXT = DAYS
BASE_1M_SHA256 = "bdd1efb4d040f8b79c5195f44f49658c15696de639a1b0bfdf5974594a7e4198"
BASE_5M_SHA256 = "81762d0a3da54ab2e7cd15229f9c8ec1d59952437099ccdbf126a83d015f50fe"
SHORT_DAY = date(2026, 10, 27)
PAIRED_DAYS = (*DAYS, SHORT_DAY)
PAIRED_HASHES = (
    "5e3cbe5b8f8deeb038ffd60e823bc239b83357e5810c656b1667ef89a698f980",
    "adaeac6b5af747c687b2176586e43f58cb440da919b16de8ac4109de1655037d",
)
PLANS = {
    "A5356884629782554": "472e86230c32b11bc0f226a1e838004be289a9327f114e807e8811e5c18d7eff",
    "WRo1n9FjvJ": "308554c18338b2780bed0ca7a3b2badb2915c4dc583b6e42b9a149cafa7e1451",
    "A5357264059367516": "d29d551079537fb3d3b2995ede2bcc274d870b4174de851749918c6954838b5d",
    "WRot1I9NxX": "be20285f7c416b0b2990d45de6a0f757febdee94488fcc874b8bc57185e29894",
}
IMAGES = {
    "WRnY5bznUE": (
        "RnY5bznUE-position-screen.png", "8fc91662bf312c2e966c97be4c192ad4730638a6cfcc1a7a089830e845ae1434",
        "2026-10-23T10:13:00+08:00",
    ),
    "WRo2KQ43iX": (
        "Ro2KQ43iX-position-screen.png", "c98d0864d8120f9c4b7276e72d570da113e846952d504f67c877892a6a2a18a6",
        "2026-10-23T22:07:00+08:00",
    ),
    "WRo39kul2n": (
        "Ro39kul2n-table2-screen.png", "e32278d3c79115d170e64ff87e3dd600dac5c43bbeba35816d15376b125d8112",
        "2026-10-23T23:07:00+08:00",
    ),
}
SHORT_PLANS = {
    "A5358325549629506": "3365107db1b12289bec850660e8b43c09cb05572cb837fc8f7022feb9a289195",
    "WRoCtNmpu8": "3be25458665c8f5a3210c15bc2bd48799977b4eb3cb92af853879ee6e5ba9e0c",
    "A5358686423089344": "add29c32af564b02876a11b0901606738ccf07ce9c4ee8ca8c551b22de13e541",
}
SHORT_IMAGES = {
    "WRov1j6e10": (
        "Rov1j6e10-position-screen.png", "35106f37378f2410b5235773a58c3e9c44581fe3eb84a2af66bf2402405cc9cb",
        "2026-10-26T22:04:00+08:00",
    ),
    "WRozNbg3en": (
        "WRozNbg3en-position-screen.png", "d8503ed169ba33faa3affbcd815549f9a334c227b4ef34ef5fb54bbb3266dd47",
        "2026-10-27T10:13:00+08:00",
    ),
}


def source_evidence(plans=PLANS, images=IMAGES):
    sources = input_sources()
    report = {}
    for source, expected in plans.items():
        entry = sources[source]
        if sha((ARCHIVE.parent / entry["archive_path"]).read_bytes()) != expected:
            raise ValueError("SA_PLAN_SOURCE_CHANGED")
        report[source] = entry | dict(archive_sha256=expected)
    for source, (name, expected, published) in images.items():
        entry = sources[source]
        image = Path(entry["archive_path"]).with_name(name)
        if entry["published_at"] != published or sha((ARCHIVE.parent / image).read_bytes()) != expected:
            raise ValueError("SA_POSITION_IMAGE_CHANGED")
        report[source] = entry | dict(image_path=image.as_posix(), image_sha256=expected)
    return report


def price_compatibility(minutes, trading_day, start, cutoff, average):
    """Containment tests an exact single price. A multi-price average only needs the total envelope."""
    selected = [b for b in minutes if b.trading_day == trading_day and start < b.bar_end < cutoff]
    if not selected:
        raise ValueError("SA_PRICE_WINDOW_EMPTY")
    price = Decimal(average)
    low, high = min(b.low for b in selected), max(b.high for b in selected)
    return dict(
        trading_day=trading_day.isoformat(), start=display(start), cutoff_exclusive=display(cutoff),
        quote=str(price), bars=len(selected), range=[str(low), str(high)],
        average_range_compatible=low <= price <= high,
        single_price_compatible_minutes=[display(b.bar_end) for b in selected if b.low <= price <= b.high],
    )


def pure_candidate_diagnostics(fives, night, cutoff, side="LONG"):
    bars = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in fives]
    replay = candidate.replay(bars, as_of=cutoff)
    closes = {b.end.isoformat(): b.close for b in bars}
    actions_by_time = {p["generated_at"]: p["action"] for p in replay["proposals"]}
    rows = []
    for row in replay["evaluations"]:
        end = datetime.fromisoformat(row["bar_end"])
        if night < end < cutoff and row["signal_direction"] == side:
            rows.append(dict(
                bar_end=display(end), close=str(closes[row["bar_end"]]), environment=row["environment"],
                rolling_range=[row["region"]["lower"], row["region"]["upper"]],
                status=row["status"], proposed_action=actions_by_time.get(row["available_at"]),
            ))
    return {
        f"night_{side.lower()}_confirmations": rows,
        "prefix_proposals": len(replay["proposals"]),
        "prefix_actions": len(replay["transitions"]),
    }


def compare(minutes, fives, evidence):
    snapshots = {source: datetime.fromisoformat(evidence[source]["published_at"]) for source in IMAGES}
    new_plan_at = datetime.fromisoformat(evidence["A5357264059367516"]["published_at"])
    early, before_night, night = at("22T21:00"), at("23T15:01"), at("23T21:00")
    morning_cut, night_cut = (snapshots[k] for k in ("WRnY5bznUE", "WRo2KQ43iX"))
    if not morning_cut < before_night < new_plan_at < night < night_cut < snapshots["WRo39kul2n"]:
        raise ValueError("SA_SOURCE_CHRONOLOGY_CHANGED")
    shapes = keybar_windows(fives, minutes, night, night_cut, contract=CONTRACT, long=True)
    night_plan_path = price_path(minutes, ("951", "957", "974"), night, night_cut)
    confirmed = {
        "after_first_divider_close": night_plan_path["levels"]["957"]["first_close_above"],
        "after_first_keybar_touch_minute": min((s["first_1m_touch"] for s in shapes if s["first_1m_touch"]),
                                                default=None),
        "after_first_fast_keybar": min((s["first_1m_close"] for s in shapes if s["first_1m_close"]),
                                      default=None),
        "after_first_slow_keybar": min((s["next_5m_at"] for s in shapes if s["next_5m_close"]),
                                      default=None),
    }
    boundary_minutes = [b for b in minutes if b.trading_day == NEXT and b.bar_end in (night_cut, night_cut + ONE)]
    if len(boundary_minutes) != 2:
        raise ValueError("SA_POST_BOUNDARY_COVERAGE_CHANGED")
    next_day = price_path(minutes, ("951", "957", "974"), at("26T09:00"), at("26T15:01"))
    if next_day["count"] != 225:
        raise ValueError("SA_DAY_SESSION_COVERAGE_CHANGED")
    return dict(
        version="lms405-sa-reentry-study-v1", contract=CONTRACT,
        sources=evidence, frozen_inputs={"1m": identity(minutes), "5m": identity(fives)},
        clock="PRICE_PATH_RETROSPECTIVE_NO_HISTORICAL_ARTICLE_REVISION",
        observed=dict(
            morning_short=dict(source="WRnY5bznUE", quantity="20", today_quantity="20",
                               average="944", assumed_trading_day=FIRST.isoformat()),
            night_long=dict(source="WRo2KQ43iX", quantity="20", today_quantity="20",
                            average="963", assumed_trading_day=NEXT.isoformat()),
            night_close_repeat_long=dict(source="WRo39kul2n", quantity="20", today_quantity="20",
                                         average="963", assumed_trading_day=NEXT.isoformat()),
            missing_side=None, same_account_chain=None, trades=None,
        ),
        price_checks={
            "morning_short_same_trading_day": price_compatibility(minutes, FIRST, early, morning_cut, "944"),
            "night_long_previous_day_session": price_compatibility(minutes, FIRST, at("23T09:00"), before_night, "963"),
            "night_long_current_trading_day": price_compatibility(minutes, NEXT, night, night_cut, "963"),
            **{key: price_compatibility(minutes, NEXT, datetime.fromisoformat(time), night_cut, "963")
               if time else None for key, time in confirmed.items()},
        },
        post_boundary_envelope=[
            dict(start=display(b.bar_end - ONE), end=display(b.bar_end), range=[str(b.low), str(b.high)])
            for b in boundary_minutes
        ],
        old_day_price=price_path(minutes, ("931", "936", "953", "957"), at("23T09:00"), before_night),
        night_new_plan_price=night_plan_path,
        next_day_new_plan_price=next_day, night_keybars=shapes,
        baseline=pure_candidate_diagnostics(fives, night, night_cut),
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def minute_close_geometry(minutes, start, cutoff, side, *, fives=None):
    # Confirm a completed shape as soon as its minute close is available.
    bars = {
        1: [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in minutes
            if start < b.bar_end < cutoff],
    }
    shape_period = 1
    if fives is not None:
        shape_period = 5
        bars[5] = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in fives
                   if start < b.bar_end < cutoff]
    return geometry_events(bars, shape_period, 1, start=start, as_of=cutoff, side=side)


def short_compare(minutes, fives, evidence):
    night = at("26T21:00")
    night_cut = datetime.fromisoformat(evidence["WRov1j6e10"]["published_at"])
    morning_cut = datetime.fromisoformat(evidence["WRozNbg3en"]["published_at"])
    if not at("26T15:00") < datetime.fromisoformat(evidence["A5358325549629506"]["published_at"]) < night:
        raise ValueError("SA_SHORT_PLAN_CHRONOLOGY_CHANGED")
    # Include the full publication-minute envelope only for price exclusion.
    bounded_cutoff = night_cut + 2 * ONE
    night_path = price_path(minutes, ("957", "951", "946", "943"), night, night_cut)
    next_day_path = price_path(minutes, ("957", "951", "946", "974", "984"), at("27T09:00"), at("27T15:01"))
    first_return = night_path["levels"]["957"]["first_low_at_or_below"]
    after_return = (price_compatibility(minutes, SHORT_DAY, datetime.fromisoformat(first_return) - ONE,
                                       bounded_cutoff, "960") if first_return else None)
    eligible = minute_close_geometry(minutes, night, night_cut, "SHORT")
    return dict(
        sources=evidence, clock="PRICE_PATH_RETROSPECTIVE_NO_HISTORICAL_ARTICLE_REVISION",
        observed={source: dict(side="SHORT", quantity="20", today_quantity="20", average="960",
                               assumed_trading_day=SHORT_DAY.isoformat()) for source in SHORT_IMAGES},
        same_account_chain=None, trades=None,
        price_checks={
            "previous_day_session": price_compatibility(minutes, NEXT, at("26T09:00"), at("26T15:01"), "960"),
            "before_night_post": price_compatibility(minutes, SHORT_DAY, night, night_cut, "960"),
            "after_or_during_first_return_to_957": after_return,
            "after_first_1m_geometry_close": price_compatibility(minutes, SHORT_DAY, eligible[0]["confirmed_at"],
                                                                 bounded_cutoff, "960") if eligible else None,
            "before_morning_post_day_session": price_compatibility(minutes, SHORT_DAY, at("27T09:00"),
                                                                  morning_cut, "960"),
        },
        post_boundary_envelope=[
            dict(start=display(b.bar_end - ONE), end=display(b.bar_end), range=[str(b.low), str(b.high)])
            for b in minutes if b.bar_end in (night_cut, night_cut + ONE)
        ],
        night_plan_price=night_path, next_day_plan_price=next_day_path,
        short_keybars_5m=keybar_windows(fives, minutes, night, night_cut, contract=CONTRACT, long=False),
        short_keybars_5m_to_1m=minute_close_geometry(minutes, night, night_cut, "SHORT", fives=fives),
        short_keybars_1m=eligible, baseline=pure_candidate_diagnostics(fives, night, night_cut, "SHORT"),
    )


def paired_compare(minutes, fives, long_case, short_sources):
    night, night_cut = at("23T21:00"), at("23T22:07")
    long_1m = minute_close_geometry(minutes, night, night_cut, "LONG")
    return dict(
        version="lms405-sa-paired-participation-study-v1", contract=CONTRACT,
        frozen_inputs={"1m": identity(minutes), "5m": identity(fives)},
        long=long_case | dict(
            long_keybars_1m=long_1m,
            long_keybars_5m_to_1m=minute_close_geometry(minutes, night, night_cut, "LONG", fives=fives),
            after_first_1m_geometry_close=price_compatibility(minutes, NEXT, long_1m[0]["confirmed_at"],
                                                             night_cut + 2 * ONE, "963") if long_1m else None,
        ),
        short=short_compare(minutes, fives, short_sources),
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-short", action="store_true", help="Compare the second night in the short direction.")
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
        evidence = source_evidence()
        days = PAIRED_DAYS if args.include_short else DAYS
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            minutes = read_session_series(session, market, "sa", CONTRACT, "1m", ONE, days)
            fives = read_session_series(session, market, "sa", CONTRACT, "5m", FIVE, days)
        initial_minutes, initial_fives = ([b for b in series if b.trading_day in DAYS] for series in (minutes, fives))
        if (identity(initial_minutes)["ohlc_sha256"] != BASE_1M_SHA256
                or identity(initial_fives)["ohlc_sha256"] != BASE_5M_SHA256):
            parser.exit(2, "SA_FROZEN_MARKET_INPUT_CHANGED\n")
        result = compare(initial_minutes, initial_fives, evidence)
        if args.include_short:
            if (identity(minutes)["ohlc_sha256"], identity(fives)["ohlc_sha256"]) != PAIRED_HASHES:
                parser.exit(2, "SA_PAIRED_MARKET_INPUT_CHANGED\n")
            result = paired_compare(minutes, fives, result, source_evidence(SHORT_PLANS, SHORT_IMAGES))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "SA_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
