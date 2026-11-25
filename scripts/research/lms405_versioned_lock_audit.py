"""Compare author-reported locks and profit-taking with role-specific price windows."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_exit_study import MINUTE_HASHES as GLASS_MINUTE_HASHES
from lms405_glass_lock_followup import window
from lms405_portfolio_replay import ARCHIVE, LOCAL, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

JM, RU = "S5307830937850724", "S5291275490430891"
JM_RANGE, OI, FG = "S5291265836190034", "S5306128623993006", "S5343083008886025"
LOCK = "LOCK_REPORTED"
PROFIT = "TAKE_PROFIT_REPORTED_SIZE_UNKNOWN"
VERSION_SPLIT = {"4.0.5": LOCK, "5.0": PROFIT}
REFERENCE = Path("output/lms405-versioned-lock-20261125/verified.json")
REFERENCE_SHA = "e61635c6ca198163dabf2ed9d7dfbcca4b71b38dd322f739f2e01f0b17ec8b74"
COMPARISON_CASES = {
    "coal_range": dict(contract="JM2609", day=(2026, 4, 24), source=JM_RANGE, band=("1258.5", "1269"),
                        role="UNORIENTED_DIVIDER", sides=("LONG", "SHORT"), actions=VERSION_SPLIT),
    "rubber_correction": dict(contract="RU2609", day=(2026, 4, 24), source=RU, band=("16930", "17040"),
                               role="CORRECTION_TEST_AREA", sides=("SHORT",), actions=VERSION_SPLIT,
                               frozen="RU2609_0424"),
    "coal_protection": dict(contract="JM2609", day=(2026, 6, 8), source=JM, band=("1446", "1464"),
                            role="SEARCH_BEFORE_OR_INSIDE_PROTECTION_AREA", sides=("SHORT",),
                            actions=VERSION_SPLIT, frozen="JM2609_0608", subsequent_day=(2026, 6, 9),
                            subsequent_frozen="JM2609_0609"),
    "oil_protection": dict(contract="OI2609", day=(2026, 6, 4), source=OI, band=("10273", "10315"),
                           role="WEAK_SIDE_PROTECTION_REFERENCE", sides=("SHORT",), actions=VERSION_SPLIT,
                           interpretation_source="WR2IUYCQHj"),
    "glass_profit": dict(contract="FG2701", day=(2026, 9, 14), source=FG, band=("940", "946"),
                         role="OPPOSING_EXTREME_M_AREA", sides=("LONG",), actions={"4.0.5": PROFIT},
                         frozen_glass=True),
}


def market_fingerprints(series):
    return {f"{p}m": dict(bars=len(rows), sha256=digest(rows)) for p, rows in series.items()}


def return_clocks(minutes, band):
    """Count completed returns into a divider without crossing a session break."""
    lower, upper = band
    events = {"FROM_ABOVE": [], "FROM_BELOW": []}
    for prev, bar in zip(minutes, minutes[1:]):
        if prev.end != bar.start or not lower <= bar.close <= upper:
            continue
        if prev.close > upper:
            events["FROM_ABOVE"].append(display(bar.end))
        elif prev.close < lower:
            events["FROM_BELOW"].append(display(bar.end))
    return dict(inside_close_count=sum(lower <= bar.close <= upper for bar in minutes),
                same_session_returns=events)


def directional_evidence(series, start, cut, band, sides):
    comparison = {}
    for side in sides:
        facts = window(series, start, cut, band=band, side=side)
        clocks = {}
        for timeframe, events in facts.pop("candidates").items():
            inside = [event for event in events if band[0] <= event["close"] <= band[1]]
            clocks[timeframe] = dict(count=len(events), first=events[0] if events else None,
                                     inside_close_count=len(inside), first_inside=inside[0] if inside else None)
        comparison[side] = facts | dict(geometry=clocks)
    return comparison


def compare_reported_actions(session, market):
    from app.market_data.market_data_service import MarketDataError

    frozen = verified_json(REFERENCE, REFERENCE_SHA)["market"]
    index = input_sources()
    sources, results, gaps = {}, {}, {}
    for case, config in COMPARISON_CASES.items():
        contract, day, source_id = config["contract"], date(*config["day"]), config["source"]
        for key in (source_id, config.get("interpretation_source")):
            if key is not None:
                source = index[key]
                sources[key] = source | dict(sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
        source = sources[source_id]
        publication = datetime.fromisoformat(source["published_at"]).astimezone(LOCAL).replace(second=0, microsecond=0)
        try:
            series = read_window(session, market, contract, day)
            later = (read_window(session, market, contract, date(*config["subsequent_day"]))
                     if "subsequent_day" in config else None)
        except MarketDataError as exc:
            gaps[case] = dict(contract=contract, trading_day=day, subsequent_day=config.get("subsequent_day"),
                              source=source_id, actions_reported=config["actions"], code=exc.code)
            continue
        market_digests = market_fingerprints(series)
        if ("frozen" in config and frozen[config["frozen"]] != market_digests
                or config.get("frozen_glass") and market_digests["1m"]["sha256"] != GLASS_MINUTE_HASHES[day.isoformat()]):
            raise ValueError("VERSIONED_LOCK_COMPARISON_MARKET_DRIFT")
        start = at(f"{day}T09:00")
        cut = min(series[1][-1].end + 2 * US, publication)
        band = tuple(map(Decimal, config["band"]))
        compare = directional_evidence(series, start, cut, band, config["sides"])
        trading_day_start = series[1][0].start
        full_minutes = completed(series[1], trading_day_start, cut)
        prior_night = (directional_evidence(series, trading_day_start, start, band, config["sides"])
                       if trading_day_start < start else None)
        post_day_night = None
        if later is not None:
            later_fingerprints = market_fingerprints(later)
            if later_fingerprints != frozen[config["subsequent_frozen"]]:
                raise ValueError("VERSIONED_LOCK_COMPARISON_NEXT_DAY_DRIFT")
            night_start, night_cut = later[1][0].start, at(f"{date(*config['subsequent_day'])}T09:00")
            if not start < night_start < night_cut < publication:
                raise ValueError("VERSIONED_LOCK_COMPARISON_NIGHT_NEGATIVE")
            post_day_night = dict(fingerprints=later_fingerprints,
                                  direction=directional_evidence(later, night_start, night_cut, band, config["sides"]))
        results[case] = dict(
            contract=contract, source=source_id, interpretation_source=config.get("interpretation_source"),
            trading_day=day, role=config["role"], band=band, market=market_digests, by_direction=compare,
            trading_day_prices=dict(low=min(b.low for b in full_minutes), high=max(b.high for b in full_minutes),
                                    close=full_minutes[-1].close),
            prior_night_direction=prior_night,
            returns=return_clocks(completed(series[1], start, cut), band) if case == "coal_range" else None,
            subsequent_night=post_day_night, actions_reported=config["actions"],
            exact_action_time_by_version={version: None for version in config["actions"]},
            same_account=None, original_leg_quantity=None, remaining_quantity_after_profit_taking=None,
            first_direction_target=None, target_then_reverse_eligible=None, raw_author_signal=None,
        )
    return dict(version="lms405-versioned-action-comparison-v1", frozen_study_sha256=REFERENCE_SHA,
                price_windows_are_retrospective=True, sources=sources, cases=results, missing_gaps=gaps,
                author_claims_are_not_fills=True, admitted_author_action_samples=0, executable=False,
                fills=None, pnl=None)


def study(session, market):
    index = input_sources()
    sources = {}
    for key in (JM, RU):
        source = index[key]
        sources[key] = source | dict(sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
    jm_day = read_window(session, market, "JM2609", date(2026, 6, 8))
    jm_next = read_window(session, market, "JM2609", date(2026, 6, 9))
    ru = read_window(session, market, "RU2609", date(2026, 4, 24))
    band = Decimal(1446), Decimal(1464)
    june_open = jm_next[1][0].start
    jm_report = datetime.fromisoformat(sources[JM]["published_at"]).astimezone(LOCAL)
    cut = jm_report.replace(second=0, microsecond=0)
    if display(june_open) != "2026-06-08T21:00+08:00" or display(cut) != "2026-06-09T09:36+08:00":
        raise ValueError("VERSIONED_LOCK_SOURCE_WINDOW_CHANGED")
    prior = window(jm_day, at("2026-06-08T09:00"), at("2026-06-08T15:01"), band=band, side="SHORT")
    night_end = at("2026-06-09T09:00")
    night = window(jm_next, june_open, night_end, band=band, side="SHORT")
    night_minutes = completed(jm_next[1], june_open, night_end)
    limit_ref = Decimal("1340.5")
    morning = window(jm_next, night_end, cut, band=band, side="SHORT")
    after_report = completed(jm_next[1], cut + ONE, at("2026-06-09T15:01"))
    if not after_report:
        raise ValueError("VERSIONED_LOCK_FORWARD_WINDOW_MISSING")
    divider = Decimal(1360), Decimal("1366.5")
    rebound = Decimal("1411.5")
    ru_band = Decimal(16930), Decimal(17040)
    ru_cut = datetime.fromisoformat(sources[RU]["published_at"]).astimezone(LOCAL)
    market = {key: {f"{p}m": dict(bars=len(bars), sha256=digest(bars)) for p, bars in series.items()}
              for key, series in (("JM2609_0608", jm_day), ("JM2609_0609", jm_next), ("RU2609_0424", ru))}
    return dict(
        version="lms405-versioned-lock-audit-v1", sources=sources, market=market,
        coal=dict(
            contract="JM2609", before_night=prior, night=night, morning_before_review=morning,
            day_to_night_open_gap=night_minutes[0].open - prior["close"],
            night_low_first_at=display(next(b.end for b in night_minutes if b.low == night["low"])),
            author_limit_reference=limit_ref, night_touched_author_limit_reference=night["low"] <= limit_ref,
            forward_plan_price_only=dict(
                minute_count=len(after_report), first_bar_end=display(after_report[0].end),
                low=min(b.low for b in after_report), high=max(b.high for b in after_report),
                short_divider=observations(after_report, divider, "SHORT"),
                continuation_up=observations(after_report, (rebound, rebound), "LONG"),
                author_hold_or_reentry=None,
            ),
            actions_reported={"4.0.5": "LOCKED_YESTERDAY_TIME_UNRESOLVED", "5.0": "NIGHT_PROFIT_TAKING_REPORTED"},
            prior_band_revision_known_at=None, lock_time=None, order_binding=None,
        ),
        rubber=dict(
            contract="RU2609", trading_day=window(ru, ru[1][0].start, ru_cut, band=ru_band, side="SHORT"),
            day_session=window(ru, at("2026-04-24T09:00"), ru_cut, band=ru_band, side="SHORT"),
            band_role="AUTHOR_CORRECTION_TEST_RANGE", lock_band=None,
            actions_reported={"4.0.5": "LOCK_REPORTED", "5.0": "PROFIT_TAKING_REPORTED"},
            lock_time=None, order_binding=None,
        ),
        admitted_author_action_samples=0, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-reported-actions", action="store_true")
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
            run = compare_reported_actions if args.compare_reported_actions else study
            report = run(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError, StopIteration):
        parser.exit(2, "VERSIONED_LOCK_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
