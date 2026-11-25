"""Compare the existing keybar hypotheses at two author-described day opens."""

import argparse
from datetime import date
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_handoff_study import INPUTS
from lms405_protection_lot_timing import verified_json
from lms405_protection_shape_audit import outside_events, price_digest
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_replay import ohlc
from lms405_right_side_study import US, at
from lms_near405_replay import encoded, sha

JM_REFERENCE = Path("output/lms-fg-sa-oct-20261125/jm-m-difficulty-final.json")
JM_SHA = "dfa88fa6f5aa8bece55854e7be47be9e08de55a8ba63e0f3d58ac99d76d043dd"


def market_identity(series):
    return {f"{period}m": dict(count=len(rows), sha256=sha(encoded(price_digest(rows)).encode()))
            for period, rows in series.items()}


def opening_comparison(series, day, side):
    start, end = at(f"{day}T09:00"), at(f"{day}T10:15:00.000002")
    night = [bar for bar in series[1] if bar.end <= start]
    if not night:
        raise ValueError("OPENING_NIGHT_CONTEXT_MISSING")
    # The shared keybar classifier accepts gaps between supplied bars. Keep
    # overnight prices out of its morphology input for this comparison.
    segment = {period: [bar for bar in rows if bar.start >= start and bar.end + US < end]
               for period, rows in series.items()}
    opening = {}
    for period, rows in segment.items():
        if not rows or rows[0].start != start:
            raise ValueError("OPENING_BAR_MISSING")
        first = rows[0]
        opening[f"{period}m"] = dict(end=first.end, known_at=first.end + US, ohlc=ohlc(first),
                                     close_from_open=first.close - first.open)
    confirmed = {}
    for shape, confirm in VARIANTS:
        for name, comparison in (("keybar", geometry_events), ("outside", outside_events)):
            inputs = dict(start=start, side=side)
            events = comparison(segment, shape, confirm, as_of=end, **inputs)
            split = opening[f"{shape}m"]["known_at"]
            prefix = {period: [bar for bar in rows if bar.end + US < split] for period, rows in segment.items()}
            earlier = comparison(prefix, shape, confirm, as_of=split, **inputs)
            if earlier != [row for row in events if row["available_at"] < split]:
                raise ValueError("OPENING_PREFIX_DIVERGED")
            if name == "outside" and shape != confirm:
                # The same-bar outside condition is already counted under shape→shape.
                events = [row for row in events if row["kind"] == "OUTSIDE_NEXT_CLOSE"]
            confirmed[f"{name}_{shape}m_to_{confirm}m"] = events
    return dict(start=start, cutoff_exclusive=end, night_low=min(bar.low for bar in night),
                night_close=night[-1].close, day_open=opening["1m"]["ohlc"][0],
                reopen_gap=opening["1m"]["ohlc"][0] - night[-1].close,
                initial_completed_bars=opening, candidates=confirmed)


def study(session, market):
    contract, oil_days, oil_digest = INPUTS["oil_may"]
    oil = {day: read_window(session, market, contract, date.fromisoformat(day)) for day in oil_days}
    oil_payload = [row for series in oil.values() for row in price_digest(series[1])]
    coal_day = "2026-09-09"
    coal = read_window(session, market, "JM2701", date.fromisoformat(coal_day))
    coal_identity = market_identity(coal)
    prior = verified_json(JM_REFERENCE, JM_SHA)["cases"][coal_day]
    if sha(encoded(oil_payload).encode()) != oil_digest or coal_identity["1m"]["sha256"] != prior["minute_sha256"]:
        raise ValueError("OPENING_FROZEN_MARKET_CHANGED")
    index = input_sources()
    cases = {}
    for symbol, day, series, side, source_id, cue in (
        (contract, oil_days[-1], oil[oil_days[-1]], "LONG", "R20260529OI", "CONDITIONAL_OPENING_UNLOCK"),
        ("JM2701", coal_day, coal, "SHORT", "S5341270434121818", "SHORT_TERM_M_OPPORTUNITY_SKIPPED"),
    ):
        source = index[source_id]
        cases[symbol] = opening_comparison(series, day, side) | dict(
            trading_day=day, direction_hypothesis=side, disclosure=cue, source_id=source_id,
            source=source, source_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
            market=market_identity(series), author_ebar_at=None, author_action_at=None,
        )
    return dict(version="lms405-opening-ebar-audit-v1", cases=cases, admitted_author_action_samples=0,
                author_match_rate=None, fills=None, pnl=None, executable=False)


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
        parser.exit(2, "OPENING_EBAR_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
