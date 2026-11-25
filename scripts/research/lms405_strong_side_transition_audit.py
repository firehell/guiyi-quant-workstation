"""Compare fixed break, persistence and target observations across adjacent VPLUS plans."""

import argparse
from datetime import datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_i2701_case import FROZEN_COMPARISON_SHA256
from lms405_managed_portfolio import BASELINE, BASELINE_SHA256
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, DAYS, FIVE, LOCAL, input_sources
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import display, ohlc, read_session_series
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

CASES = {
    "RU2701": dict(
        band=(19505, 19570), targets=((19320, 19420), (19220, 19290)),
        plans=("A5357264793370945", "A5358325972992140", "A5358686695981271"),
        state_after=("RANGE_BEARISH_STRONG_SIDE", "BEARISH_TREND_RESTORED"), review="U05",
    ),
    "FG2701": dict(
        band=(828, 832), targets=((825, 825), (814, 821)),
        plans=("A5357264059367516", "A5358325549629506", "A5358686423089344"),
        state_after=("PAUSED_BEARISH_TREND_RANGE", "PAUSED_BEARISH_TREND_RANGE"), review="WRoCswszPF",
    ),
}
IRON = {
    "I2701": dict(
        band=("668.5", "671.5"), targets=((654, "662.5"),),
        plans=("A5357264059367516", "A5358325549629506", "A5358686423089344"),
        state_after=("RANGE_BEARISH_STRONG_SIDE", "RANGE"), review="WRoCldvp4f",
    ),
}
STUDIED = DAYS[1:3]
IRON_REFERENCE = Path("output/lms-i2701-oct-20261125/comparison.json")


def persistence(bars, edge):
    runs = strict_runs(bars, edge, "SHORT")
    first = next((end for end, run in runs.items() if run["close_count"] >= 2), None)
    fresh = next((end for end, run in runs.items() if run["close_count"] >= 2
                  and run["fresh_crossing_known_at"] is not None), None)
    terminal = runs.get(bars[-1].end)
    return dict(first_two_at=first, first_two_after_in_segment_break_at=fresh,
                longest=max((run["close_count"] for run in runs.values()), default=0),
                terminal=0 if terminal is None else terminal["close_count"])


def price_path(bars, band):
    if not bars:
        raise ValueError("STRONG_SIDE_OBSERVATION_WINDOW_EMPTY")
    low, high = min(bar.low for bar in bars), max(bar.high for bar in bars)
    return dict(
        **observations(bars, band, "SHORT"), open=bars[0].open, close=bars[-1].close,
        low=low, high=high, first_low_at=next(bar.end for bar in bars if bar.low == low),
        below_far_at_end=bars[-1].close < band[0],
        near_persistence=persistence(bars, band[1]), far_persistence=persistence(bars, band[0]),
    )


def persistence_after_target(bars, edge, target):
    """Use a completed target-price observation strictly before the evaluation close."""
    target_end = next((bar.end for bar in bars if bar.low <= target), None)
    runs = strict_runs(bars, edge, "SHORT")
    qualified = [end for end, run in runs.items()
                 if target_end is not None and target_end < end and run["close_count"] >= 2]
    return dict(target=target, target_first_reached_at=target_end,
                first_qualified_at=qualified[0] if qualified else None,
                qualified_at_end=bool(qualified) and qualified[-1] == bars[-1].end)


def source_details(index, ids):
    result = {}
    for key in ids:
        source = index[key]
        path = ARCHIVE.parent / source["archive_path"]
        result[key] = source | dict(sha256=sha(path.read_bytes()))
    return result


def study(session, market, *, include_iron=False):
    reference = verified_json(BASELINE, BASELINE_SHA256)
    iron_reference = verified_json(IRON_REFERENCE, FROZEN_COMPARISON_SHA256) if include_iron else None
    index = input_sources()
    cases = {}
    inputs = CASES | IRON if include_iron else CASES
    for contract, case in inputs.items():
        series = {day: read_window(session, market, contract, day) for day in STUDIED}
        full_five = []
        for day in DAYS:
            if day in series:
                full_five.extend(series[day][5])
            else:
                bars = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, (day,))
                full_five.extend(Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in bars)
        digest = sha(encoded(price_digest(full_five)).encode())
        if digest != reference["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("STRONG_SIDE_FROZEN_5M_INPUT_CHANGED")
        if contract in IRON:
            rows = price_digest(series[STUDIED[-1]][1])
            minute_identity = dict(bars=len(rows), ohlc_sha256=sha(json.dumps(rows, separators=(",", ":")).encode()))
            if minute_identity != iron_reference["market_1m"]["i"][STUDIED[-1].isoformat()]:
                raise ValueError("STRONG_SIDE_FROZEN_IRON_MINUTES_CHANGED")
        sources = source_details(index, (*case["plans"], case["review"]))
        timelines = {}
        band = tuple(map(Decimal, case["band"]))
        for day, plan_id, review_id, wording in zip(
                STUDIED, case["plans"][:-1], case["plans"][1:], case["state_after"], strict=True):
            day_start = datetime.combine(day, time(9), LOCAL)
            one = series[day][1]
            prev = next(b for b in reversed(full_five) if b.end < one[0].start)
            published = datetime.fromisoformat(sources[plan_id]["published_at"])
            reviewed = datetime.fromisoformat(sources[review_id]["published_at"])
            if not (published + timedelta(minutes=1) < one[0].start < one[-1].end < reviewed):
                raise ValueError("STRONG_SIDE_SOURCE_WINDOW_CHANGED")
            paths = {f"{p}m": dict(trading_day=price_path(bars, band),
                                   day_session=price_path([b for b in bars if b.start >= day_start], band),
                                   sha256=sha(encoded(price_digest(bars)).encode()))
                     for p, bars in series[day].items()}
            minute = paths["1m"]["trading_day"]
            far = minute["far_persistence"]
            timelines[day.isoformat()] = dict(
                prior_plan=plan_id, next_plan_review=review_id, after_session_wording=wording,
                prior_close=prev.close, night_open=one[0].open, first_minute_close=one[0].close,
                night_start=display(one[0].start), paths=paths,
                targets=[observations(one, tuple(map(Decimal, levels)), "SHORT") for levels in case["targets"]],
                retrospective_1m_comparison=dict(
                    ever_touched_far=minute["first_far_reach"] is not None,
                    ever_closed_below_far=minute["first_strict_close_beyond_far"] is not None,
                    ever_two_closes_below_far=far["first_two_at"] is not None,
                    at_least_two_closes_below_far_at_end=far["terminal"] >= 2,
                ),
            )
            if include_iron:
                targets = [Decimal(levels[0]) for levels in case["targets"]]
                timelines[day.isoformat()]["persistence_after_old_target_1m"] = {
                    "first_target": persistence_after_target(one, band[0], targets[0]),
                    "all_targets": persistence_after_target(one, band[0], min(targets)),
                }
        cases[contract] = dict(band=band, market_5m_sha256=digest, sources=sources, trading_days=timelines,
                               strategy_transition_at=None, author_signal_at=None)
    return dict(version="lms405-strong-side-transition-audit-v1", cases=cases, admitted_author_action_samples=0,
                baseline_sha256=BASELINE_SHA256, historical_source_revision_verified=False,
                candidate_policy="PRICE_PATH_COMPARISON_ONLY", executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-iron", action="store_true")
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
            report = study(session, build_market_data_service(session), include_iron=args.include_iron)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "STRONG_SIDE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
