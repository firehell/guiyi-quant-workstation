"""Compare displayed long-leg formation against protection and M milestones."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import readback
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import (
    EXPOSURE,
    displayed_tick_totals,
    earlier_lot_counts,
    tick_bounds,
    verified_json,
)
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

VERSION = "lms405-reversal-stage-bounds-v1"
PHOTO = Path("output/lms-fg-sa-oct-20261125/comparison.json")
PHOTO_SHA = "05979cc11d08f7518dedb09202ba3125e84171d11f9d3af74db8f601b0c1a63d"
COMMON = Path("output/lms405-common-protection-oct27-20261125")
RU22_SHA = "ef337f6c8610671d4664cee1160da052c845cf8eba23707059f9a067cb4f466c"
RU27_SHA = "1f8faeba34873d4be26cb01145dbb994305c01aa45a0af3d905ea35442f09264"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
CASES = (
    ("fg_reappearance", "FG2701", date(2026, 10, 23), "A5356884629782554", "WRo00BFM1E",
     "828.8", ("829", "836"), ("842", "844")),
    ("ru_first_night", "RU2701", date(2026, 10, 23), "A5356884885635211", "WRnTlEfj1t",
     "19505.0", ("19530", "19680"), ("19790", "19935")),
    ("ru_second_night", "RU2701", date(2026, 10, 28), "A5358686695981271", "WRoEvasxQR",
     "19470.0", ("19360", "19405"), ("19515", "19610")),
)


def lot_split(minutes, boundary, *, tick, lots, totals):
    """All later lots must use the price envelope after the supplied split."""
    before = tick_bounds([bar for bar in minutes if bar.bar_end <= boundary], tick)
    after = tick_bounds([bar for bar in minutes if bar.bar_end > boundary], tick)
    allowed = earlier_lot_counts(before, after, lots, totals)
    return dict(before_bounds_ticks=before, after_bounds_ticks=after,
                minimum_earlier_lots=min(allowed, default=None),
                maximum_earlier_lots=max(allowed, default=None),
                entire_leg_possible_after=0 in allowed)


def assess_window(timeline, start, capture, protection, m, *, tick, lots, average):
    search = [bar for bar in timeline if bar.bar_end - ONE >= start]
    observed = [bar for bar in search if bar.bar_end <= capture]
    totals = displayed_tick_totals(average, lots, tick)
    if not earlier_lot_counts(None, tick_bounds(observed, tick), lots, totals):
        raise ValueError("DISPLAY_AVERAGE_OUTSIDE_ASSUMED_OBSERVATION_WINDOW")
    lot_options = dict(tick=tick, lots=lots, totals=totals)
    near, far = protection
    m_near, m_far = m
    checks = (
        ("protection_first_overlap", lambda bar: bar.low <= far and bar.high >= near, True),
        ("close_above_protection_near", lambda bar: bar.close > near, False),
        ("close_above_protection_far", lambda bar: bar.close > far, False),
        ("m_near_reached", lambda bar: bar.high >= m_near, True),
        ("m_far_reached", lambda bar: bar.high >= m_far, True),
        ("close_above_m_far", lambda bar: bar.close > m_far, False),
    )
    gates = {}
    for name, check, include_bar in checks:
        first = next((bar for bar in search if check(bar)), None)
        boundary = first.bar_end if first else None
        if boundary and include_bar:
            boundary -= ONE
        gates[name] = dict(
            first_bar_end=display(first.bar_end) if first else None,
            seen_by_capture=first is not None and first.bar_end <= capture,
            gate_bar_allowed_for_touch=include_bar,
            lot_bounds=lot_split(observed, boundary, **lot_options) if boundary else None,
            only_full_minutes_after_close=(lot_split(observed, first.bar_end + ONE, **lot_options)
                                           if first and not include_bar else None),
        )
    return dict(start=display(start), capture_upper_bound=display(capture), completed_minutes=len(observed),
                market_bounds_ticks=tick_bounds(observed, tick), rounded_total_ticks=list(totals), gates=gates)


def photo_row(tables, source, contract):
    table = tables[source]
    image = table["image"]
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("REVERSAL_STAGE_HOLDINGS_IMAGE_CHANGED")
    return dict(source=source, version_on_post=table["system"], binding=table["binding"], image=image,
                published_at=table["published_at"], legs=table["contracts"][contract]["legs"])


def report(session, market):
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    photo = verified_json(PHOTO, PHOTO_SHA)
    ru22 = verified_json(COMMON / "oct22-check.json", RU22_SHA)
    ru27 = verified_json(COMMON / "final.json", RU27_SHA)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    tables = {table["source"]: table for table in exposure["tables"]}
    catalog = input_sources()
    cases = {}
    for name, contract, day, plan, source, display_average, protection, m in CASES:
        symbol = contract[:-4].lower()
        timeline = read_session_series(session, market, symbol, contract, "1m", ONE, (day,))
        if name == "ru_second_night":
            identity = readback(timeline)[day.isoformat()]
            expected = ru27["input_1m"][contract]
            matches = identity == {k: expected[k] for k in identity}
        else:
            identity = dict(full_day_count=len(timeline), full_day_sha256=bars_sha(timeline))
            expected = ru22["input_1m"][contract]
            matches = identity == {k: expected[k] for k in identity}
        if not matches:
            raise ValueError("REVERSAL_STAGE_MARKET_IDENTITY_CHANGED")
        holding = photo_row(tables, source, contract)
        long, short = (holding["legs"][side] for side in ("long", "short"))
        if long["quantity"] != long["today_quantity"] or long["quantity"] != short["quantity"]:
            raise ValueError("EXPECTED_VISIBLE_EQUAL_LEGS_WITH_TODAY_LONG")
        if Decimal(long["opening_average"]) != Decimal(display_average):
            raise ValueError("DISPLAY_AVERAGE_REREAD_MISMATCH")
        start = timeline[0].bar_end - ONE
        plan_available = datetime.fromisoformat(catalog[plan]["published_at"])
        published = datetime.fromisoformat(holding["published_at"])
        if not plan_available < start < published:
            raise ValueError("REVERSAL_STAGE_SOURCE_ORDER_CHANGED")
        # Publication is an upper bound with minute precision, not a quote anchor.
        anchors = {"before_post_minute": published - ONE, "full_post_minute_sensitivity": published + ONE}
        starts = {"trading_day": start}
        earlier = None
        if name == "fg_reappearance":
            (close_anchor,) = photo["photos"][source]["joint_equal_close"]
            anchors = {"joint_close_anchor": datetime.fromisoformat(close_anchor)}
            earlier = photo_row(tables, "WRnY5bznUE", contract)
            if "long" in earlier["legs"] or earlier["legs"]["short"] != short:
                raise ValueError("FG_BEFORE_IMAGE_TRANSCRIPTION_CHANGED")
            starts |= {f"after_early_photo_candidate_{n}": datetime.fromisoformat(value)
                       for n, value in enumerate(photo["photos"][earlier["source"]]["joint_contains"], start=1)}
        args = dict(tick=specs[contract]["tick"], lots=long["quantity"], average=Decimal(display_average))
        paths = {
            f"{start_name}/{capture_name}": assess_window(timeline, lower, upper, tuple(map(Decimal, protection)),
                                                          tuple(map(Decimal, m)), **args)
            for start_name, lower in starts.items() for capture_name, upper in anchors.items()
        }
        cases[name] = dict(contract=contract, trading_day=day, plan=plan, plan_source=catalog[plan],
                           market=identity, holding=holding, earlier_holding=earlier, protection=protection, m=m,
                           tick=args["tick"], displayed_long_average=display_average, windows=paths,
                           author_signal_at=None, author_action_at=None)
    return dict(version=VERSION, cases=cases, historical_article_revisions_verified=False,
                future_gates_are_retrospective_comparisons=True, account_continuity=None, admitted_author_actions=0,
                author_matches=None, fills=None, pnl=None, executable=False)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = report(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")
    except (MarketDataError, OperationalError):
        parser.error("LOCAL_MARKET_READ_FAILED")


if __name__ == "__main__":
    main()
