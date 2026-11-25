"""Test recovery clocks if a previous PVC target completion were carried forward."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_unlock_boundary_comparison import evaluate
from lms_near405_replay import encoded, sha

CONTRACT = "V2609"
DAYS = tuple(date(2026, 4, d) for d in (23, 24, 27, 28))
BAND = (Decimal(5226), Decimal(5262))
SECOND_BAND = (Decimal(5285), Decimal(5297))
REFERENCE = Path("output/lms405-unlock-boundary-20261125/final.json")
REFERENCE_SHA = "4a0c6c836fc64b0c5c0af5b4310395b5a8c7d9026c14b31ec459f433f715e541"
SOURCES = {
    "S5290904148773752": ("2026-04-23T16:35", "545212f209791dd2849b05cd110755aef719a7951515f0df4cab9b534d7b68b6"),
    "S5292358960155373": ("2026-04-27T16:56", "905c2129da0d1da3430dbded4d736b05bf5c7c1f649365f23f17b9f2d7986029"),
    "S5292720017903146": ("2026-04-28T16:50", "f7f98015d637ae333d05d2e220e7787603bafcf5a969bdb9228fa7d5556d2dd9"),
}


def first_end(minutes, level, *, field, include_equal=False):
    return next((bar.end + US for bar in minutes if getattr(bar, field) > level
                 or (include_equal and getattr(bar, field) == level)), None)


def label_candidate(event, *, prior_touch, prior_close, same_day, current_run, second_run):
    # A timestamp is when the matched completed close or range becomes usable.
    # The new shape must start strictly later, not merely confirm later.
    shape_start = event["shape_end"] - event["shape_minutes"] * ONE
    near = "NEAR" in event["modes"]

    def earlier(stamp):
        return stamp is not None and stamp < shape_start

    both_completed = earlier(same_day["first_far_close"]) and earlier(same_day["second_far_close"])
    return dict(
        prior_day_touch_allows_near=near and earlier(prior_touch),
        prior_day_close_allows_near=near and earlier(prior_close),
        same_day_touch_allows_near=near and earlier(same_day["first_far_touch"]),
        new_shape_after_current_first_far_cross=earlier(current_run["fresh_crossing_known_at"]),
        new_shape_after_both_far_closes=both_completed,
        new_shape_after_both_with_current_second_far_cross=(
            both_completed and earlier(second_run["fresh_crossing_known_at"])
        ),
    )


def inspect_day(series, *, start, cut, prior_touch, prior_close):
    minutes = [bar for bar in series[1] if bar.start >= start and bar.end + US < cut]
    first_far, second_far = BAND[1], SECOND_BAND[1]
    first = strict_runs(minutes, first_far, "LONG")
    second = strict_runs(minutes, second_far, "LONG")
    same_day = dict(first_far_touch=first_end(minutes, first_far, field="high", include_equal=True),
                    first_far_close=first_end(minutes, first_far, field="close"),
                    second_far_touch=first_end(minutes, second_far, field="high", include_equal=True),
                    second_far_close=first_end(minutes, second_far, field="close"))
    base = evaluate(series, start=start, cut=cut, side="LONG", band=BAND)
    empty = dict(fresh_crossing_known_at=None)
    shelf = [event | dict(conditions=label_candidate(
        event, prior_touch=prior_touch, prior_close=prior_close, same_day=same_day,
        current_run=first.get(event["confirmed_at"], empty) if "FAR" in event["modes"] else empty,
        second_run=second.get(event["confirmed_at"], empty) if "FAR" in event["modes"] else empty,
    )) for event in base["candidates"]]
    return dict(same_trading_day=same_day, candidates=shelf, minute_count=len(minutes),
                high=max((bar.high for bar in minutes), default=None), close=minutes[-1].close if minutes else None)


def study(session, market):
    ref = verified_json(REFERENCE, REFERENCE_SHA)["cases"]
    comparisons = dict(zip(DAYS[2:], (ref["pvc_not_unlocked"], ref["pvc_target_completed"]), strict=True))
    index = input_sources()
    sources = {}
    for sid, (displayed, fingerprint) in SOURCES.items():
        source = load_source(index, sid)
        if datetime.fromisoformat(source["published_at"]) != at(displayed) or source["archive_sha256"] != fingerprint:
            raise ValueError("PVC_RECOVERY_SOURCE_CHANGED")
        sources[sid] = source
    days, prior_touch, prior_close = {}, None, None
    for day in DAYS:
        series = read_window(session, market, CONTRACT, day)
        cut = at(f"{day.isoformat()}T15:01")
        inputs = {f"{period}m": dict(count=len(bars), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in bars
        ]).encode())) for period, bars in series.items()}
        args = dict(start=series[1][0].start, prior_touch=prior_touch, prior_close=prior_close)
        report = inspect_day(series, cut=cut, **args)
        if day in comparisons:
            frozen = comparisons[day]
            core = [{k: v for k, v in event.items() if k != "conditions"} for event in report["candidates"]]
            if (inputs != frozen["market_input"]
                    or encoded(core) != encoded(frozen["candidates"])):
                raise ValueError("PVC_RECOVERY_FROZEN_CASE_CHANGED")
        clocks = {event["available_at"] for event in report["candidates"]}
        clocks.update(t for t in report["same_trading_day"].values() if t is not None)
        cuts = clocks | {t + US for t in clocks}
        for end in sorted(cuts):
            prefix = {p: [b for b in bars if b.end + US < end] for p, bars in series.items()}
            earlier = inspect_day(prefix, cut=end, **args)
            if earlier["candidates"] != [e for e in report["candidates"] if e["available_at"] < end]:
                raise ValueError("PVC_RECOVERY_PREFIX_DIVERGED")
            if earlier["same_trading_day"] != {
                k: v if v is not None and v < end else None for k, v in report["same_trading_day"].items()
            }:
                raise ValueError("PVC_RECOVERY_PROGRESS_DIVERGED")
        days[day.isoformat()] = report | dict(market=inputs, prefix_checks=len(cuts),
                                             carried_touch_hypothesis=prior_touch, carried_close_hypothesis=prior_close)
        prior_touch = prior_touch or report["same_trading_day"]["first_far_touch"]
        prior_close = prior_close or report["same_trading_day"]["first_far_close"]
    return dict(version="lms405-pvc-recovery-carry-v1", contract=CONTRACT, days=days, sources=sources,
                first_band=BAND, retrospective_second_band=SECOND_BAND, frozen_recovery_sha256=REFERENCE_SHA,
                author_april27_report="NO_LONG_UNLOCK", author_april28_report="TARGETS_COMPLETED_ACTION_UNKNOWN",
                scope="RETROSPECTIVE_FIXED_BAND_CARRY_SENSITIVITY", author_plan_continuity=None,
                author_position=None, author_action_at=None, admitted_author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PVC_RECOVERY_")
                        else "PVC_RECOVERY_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
