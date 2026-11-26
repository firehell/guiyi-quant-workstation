"""Audit delayed use of a frozen protection signal through price tests and session boundaries."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest, signals
from lms_near405_replay import encoded

SNAPSHOT = Path("output/lms405-snapshot-window-20261125/report.json")
SNAPSHOT_SHA = "131bfb315f2347197ce633109005d92da0e06901692202c6afa728caf1e2650b"
SHAPE_AUDIT = Path("output/lms405-shape-audit-20261125/report.json")
SHAPE_AUDIT_SHA = "692ad01e734a6a47d27f063e2b87299e9ce7f9d0aa3d060d444e11392c552079"
PRE_TOUCH = Path("output/lms405-pre-touch-protection-20261125/final.json")
PRE_TOUCH_SHA = "d5053217c8be047d853955709fdca77b8b268656f5cb2af0b078574399e94a60"
CHAIN = Path("output/lms405-sh-intermediate-chain-20261126/final-a.json")
CHAIN_SHA = "f223aadaa91b576429213971f58ee97861125e3a978bbc2c36577f8c7cffac41"
SH_PRIOR_PLAN, SH_UPDATE = "A5358325972992140", "WRouYm67Bc"
SH_MORNING_MARKET = {
    "1m": "3d919342b223d370957d8c1d4b798d4c821bcf5691e12a36e3118d0d806dd66c",
    "5m": "38286bb49000a484355ae964ca96d70637db375dd09c12cd600971730aae0b9b",
}


def verify_signal(series, comparison, shape_period, confirm_period, *, start, cutoff):
    shape_end = datetime.fromisoformat(comparison["shape_end"])
    confirmation_end = datetime.fromisoformat(comparison["confirmed_at"])
    if shape_end >= confirmation_end or datetime.fromisoformat(comparison["available_at"]) != confirmation_end + US:
        raise ValueError("PROTECTION_LIFETIME_SHAPE_TIME_UNVERIFIED")
    matching = [event for event in signals(series, shape_period, confirm_period, side="LONG", start=start, cut=cutoff)
                if event["shape_end"] == shape_end and event["confirmed_at"] == confirmation_end]
    if len(matching) != 1:
        raise ValueError("PROTECTION_LIFETIME_FROZEN_SIGNAL_NOT_UNIQUE")
    (source_signal,) = matching
    for field in ("close", "boundary"):
        if Decimal(comparison[field]) != source_signal[field]:
            raise ValueError("PROTECTION_LIFETIME_FROZEN_SIGNAL_CHANGED")
    (shape,) = [bar for bar in series[shape_period] if bar.end == shape_end]
    return source_signal | dict(shape_low=shape.low, shape_high=shape.high, contract=shape.contract)


def lifetime(series, signal, shape_period, confirm_period, *, as_of, revision_at):
    available = signal["available_at"]
    if not available < as_of:
        return None
    bars = [bar for bar in series[1] if signal["confirmed_at"] <= bar.end and bar.end + US < as_of]
    step = timedelta(minutes=shape_period)
    opposing = signals(series, shape_period, confirm_period, side="SHORT", start=available, cut=as_of)
    confirmation_bars = [bar for bar in series[confirm_period] if available < bar.end and bar.end + US < as_of]

    def close_event(rows, level, *, inclusive):
        point = next((bar for bar in rows if bar.close < level or (inclusive and bar.close == level)), None)
        return dict(bar_end=point.end, known_at=point.end + US, close=point.close) if point else None

    first_opposite = next((event for event in opposing if available < event["shape_end"] - step), None)
    first_gap = next((current for previous, current in zip(bars, bars[1:]) if previous.end != current.start), None)
    reset = close_event(confirmation_bars, signal["boundary"], inclusive=True)
    shape_failure = close_event(confirmation_bars, signal["shape_low"], inclusive=False)
    revision_known = revision_at if revision_at is not None and revision_at < as_of else None
    return dict(
        first_confirm_period_close_back_at_or_below_boundary=reset,
        first_confirm_period_close_below_full_shape=shape_failure,
        first_fresh_opposing_confirmation=first_opposite,
        first_resumed_minute_end=first_gap.end if first_gap else None,
        first_resumed_minute_known_at=first_gap.end + US if first_gap else None,
        plan_review_publication_time_proxy=revision_known,
        no_failure_observed_in_completed_prefix=(reset is None and first_opposite is None
                                                 and first_gap is None and revision_known is None),
    )


def check_points(series, signal, shape_period, confirm_period, checkpoints, revision=None):
    results = {}
    points = {point for cut in (*checkpoints.values(), signal["available_at"]) for point in (cut, cut + US)}
    for cut in sorted(points):
        args = (signal, shape_period, confirm_period)
        full = lifetime(series, *args, as_of=cut, revision_at=revision)
        prefix = {period: [bar for bar in rows if bar.end + US < cut] for period, rows in series.items()}
        if full != lifetime(prefix, *args, as_of=cut, revision_at=revision):
            raise ValueError("PROTECTION_LIFETIME_PREFIX_DIVERGED")
        results[cut] = full
    return dict(checks=len(points), checkpoints={key: dict(evaluated_at=point, result=results[point])
                                                 for key, point in checkpoints.items()})


def study(session, market):
    index = input_sources()
    prior = verified_json(SNAPSHOT, SNAPSHOT_SHA)["cases"]["SH2701"]
    reference = verified_json(PRE_TOUCH, PRE_TOUCH_SHA)["cases"]
    chain = verified_json(CHAIN, CHAIN_SHA)
    (candidate,) = prior["price_compatible_candidates_before_or_at_partial_quote"]
    shape_audit = verified_json(SHAPE_AUDIT, SHAPE_AUDIT_SHA)["cases"]["SH2701"]["inspections"]
    (early_mode,) = [key for key, value in shape_audit.items() if candidate in value["existing"]]
    shape_period, confirm_period = (int(value.removesuffix("m")) for value in early_mode.split("_to_"))
    contract = "SH2701"
    start, cutoff = at("2026-10-26T21:00"), datetime.fromisoformat(chain["morning_cutoff_exclusive"])
    plan, update = (load_source(index, source) for source in (SH_PRIOR_PLAN, SH_UPDATE))
    review = datetime.fromisoformat(update["published_at"]) + ONE
    review_rows = [row for row in chain["plan_windows"] if row["revision"] == SH_UPDATE]
    if (len(review_rows) != 1 or review_rows[0]["role"] != "REVIEW_PENDING"
            or datetime.fromisoformat(review_rows[0]["available"]) != review
            or not datetime.fromisoformat(plan["published_at"]) + ONE < start < review < cutoff):
        raise ValueError("PROTECTION_LIFETIME_REVIEW_SCOPE_CHANGED")
    series = read_window(session, market, contract, date(2026, 10, 27))
    early_fingerprints = {f"{period}m": digest(rows) for period, rows in series.items()}
    if any(early_fingerprints[period] != sha for period, sha in SH_MORNING_MARKET.items()):
        raise ValueError("PROTECTION_LIFETIME_MORNING_MARKET_CHANGED")
    early = verify_signal(series, candidate, shape_period, confirm_period, start=start, cutoff=review)
    (anchor,) = chain["observations"]["WRovrUdwHi"]["quote_anchors"]
    price_bound = chain["price_only_after_night_quote_anchor"]["first_compatible_prefix_end"]
    target = check_points(series, early, shape_period, confirm_period, dict(
        reset_minute_completion_boundary=at("2026-10-26T21:18") + US,
        after_reset_minute_available=at("2026-10-26T21:18") + 2 * US,
        shape_failure_completion_boundary=at("2026-10-26T21:44") + US,
        after_shape_failure_available=at("2026-10-26T21:44") + 2 * US,
        before_review=review, after_review=review + US, night_quote=datetime.fromisoformat(anchor),
        before_day_open=at("2026-10-27T09:00"), first_day_bar_known=at("2026-10-27T09:01") + 2 * US,
        first_compatible_price_prefix=datetime.fromisoformat(price_bound) + 2 * US, morning_post_cutoff=cutoff,
    ), revision=review)

    controls = {}
    for case in ("sh_second_night", "ru_first_night"):
        config = reference[case]
        begin, end = (datetime.fromisoformat(config[key]) for key in ("start", "cut"))
        control = read_window(session, market, config["contract"], date.fromisoformat(config["trading_day"]))
        fingerprints = {f"{period}m": digest(rows) for period, rows in control.items()}
        if fingerprints != config["market"]:
            raise ValueError("PROTECTION_LIFETIME_CONTROL_MARKET_CHANGED")
        rows = []
        for control_mode, events in config["variants"].items():
            for recorded in events:
                if recorded["touch_known_at"] is None:
                    continue
                shape, confirm = (int(value.removesuffix("m")) for value in control_mode.split("_to_"))
                record = verify_signal(control, recorded, shape, confirm, start=begin, cutoff=end)
                touch = datetime.fromisoformat(recorded["touch_known_at"])
                audit = check_points(control, record, shape, confirm,
                                     {"touch_at_availability_boundary": touch, "touch_known": touch + US})
                rows.append(dict(mode=control_mode, signal=record, frozen_touch_known_at=touch, **audit))
        controls[case] = dict(rows=rows, contract=config["contract"], market=fingerprints,
                              source=load_source(index, config["plan"]["id"]))
    return dict(version="lms405-protection-signal-lifetime-v1", contract=contract, sources=[plan, update],
                early_signal=early, early_signal_mode=early_mode, before_morning=target, same_session_controls=controls,
                market=early_fingerprints, price_only_after_night_quote=chain["price_only_after_night_quote_anchor"],
                inputs=dict(snapshot_sha256=SNAPSHOT_SHA, shape_audit_sha256=SHAPE_AUDIT_SHA,
                            pre_touch_sha256=PRE_TOUCH_SHA, position_chain_sha256=CHAIN_SHA),
                historical_edit_verified=False, author_lifetime_formula=None, author_action_samples=0,
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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PROTECTION_LIFETIME_') and code.isidentifier() else 'PROTECTION_LIFETIME_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
