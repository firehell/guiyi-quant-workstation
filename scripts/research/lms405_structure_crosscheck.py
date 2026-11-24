"""Fixed-window cross-check of the JM2601 structure hypotheses against other diagrams."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_jm2601_structure import FIVE, LOCAL, ONE, US, structure_trace
from lms405_july22_geometry import INPUT_SHA256
from lms405_locked_exit_audit import verify_aggregation
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

# Source anchors have the roles retained in the admission table. 5m is the
# frozen research frequency, including where the source's frequency is unknown.
WINDOWS = (
    ("JM2509_JUL18_NIGHT", "JM2509", ("KB16", "KB17"),
     ("2025-07-18", "2025-07-21"), "2025-07-18T21:00", "2025-07-18T23:00:00.000002",
     ("889.5", "930", "932.5", "1006.5", "1007")),
    ("JM2509_JUL21_DAILY_COMPANION", "JM2509", ("KB16", "KB17"),
     ("2025-07-21",), "2025-07-21T09:00", "2025-07-21T15:00:00.000002",
     ("889.5", "930", "932.5", "1006.5", "1007")),
    ("JM2509_JUL22_RECOVERY", "JM2509", ("KB18", "H06", "H08"),
     ("2025-07-22",), "2025-07-22T09:00", "2025-07-22T11:35",
     ("1012.5", "1048.5", "930", "932.5")),
    ("JM2509_JUL22_AFTERNOON_COMPANION", "JM2509", ("KB18",),
     ("2025-07-22",), "2025-07-22T13:30", "2025-07-22T15:00:00.000002",
     ("1012.5", "1048.5")),
    ("PS2508_JUL17_HOLD", "PS2508", ("KB04",),
     ("2025-07-17", "2025-07-18"), "2025-07-17T09:00", "2025-07-17T21:29",
     ("43065", "43470", "45715")),
)
FIELDS = ("open", "high", "low", "close")
FROZEN_DAYS = (date(2025, 7, 21), date(2025, 7, 22))
FROZEN_SESSION_SPLIT = datetime(2025, 7, 21, 21, tzinfo=LOCAL)


def local_time(value):
    return value.astimezone(LOCAL).isoformat()


def compare_frozen_july(records, *, frozen, days):
    # This split is the known boundary of the sealed July export only.
    # The actual input's trading-day label comes from the MDS and Catalog.
    expected = {}
    for row in frozen:
        end = datetime.fromisoformat(row["bar_end_utc"])
        frozen_day = FROZEN_DAYS[int(end > FROZEN_SESSION_SPLIT)]
        if frozen_day in days:
            expected[end] = tuple(Decimal(row[k]) for k in FIELDS)
    actual = {bar.bar_end: ohlc(bar) for bar in records if bar.trading_day in FROZEN_DAYS}
    if actual != expected:
        raise ValueError("JULY_FROZEN_OHLC_DIVERGED")


def find_anchor(rows, price, end_field):
    return {field: [local_time(getattr(b, end_field)) for b in rows if getattr(b, field) == price]
            for field in ("low", "high", "close")}


def match(reference, start, cut, levels):
    minute, fives = reference
    trace = structure_trace(fives, as_of=cut)
    events = [row for row in trace["breakouts"] if row["confirmation_bar_end"] - FIVE >= start]
    # Verify that revealing the future does not change the observable prefix.
    visible_fives = [b for b in fives if b.end + US < cut]
    if trace != structure_trace(visible_fives, as_of=cut):
        raise ValueError("STRUCTURE_PREFIX_DIVERGED")
    visible_minutes = [b for b in minute if b.bar_end + US < cut]
    anchors = {raw: dict(minutes=find_anchor(visible_minutes, Decimal(raw), "bar_end"),
                         fives=find_anchor(visible_fives, Decimal(raw), "end")) for raw in levels}
    observed = [b for b in visible_fives if b.start >= start]
    previous = next((b for b in reversed(visible_fives) if b.end <= start), None)
    return dict(
        window_fives=len(observed),
        window_high=max((b.high for b in observed), default=None),
        window_low=min((b.low for b in observed), default=None),
        first_bar_open=observed[0].open if observed else None,
        prior_observed_close=previous.close if previous else None,
        anchor_matches=anchors,
        pivots=[p for p in trace["pivots"] if p["bar_end"] - FIVE >= start],
        events=events,
    )


def study(session, market, frozen):
    from app.market_data.market_data_service import MarketDataError

    cases, reads, first_opens = {}, {}, {}
    for name, contract, sources, date_strings, opened, through, levels in WINDOWS:
        start, cut = (datetime.fromisoformat(t).replace(tzinfo=LOCAL) for t in (opened, through))
        days = tuple(map(date.fromisoformat, date_strings))
        row = dict(contract=contract, sources=sources, trading_days=date_strings,
                   observation_window=[start, cut], author_period=None,
                   eligible_author_samples=0, author_signal_at=None, executable=False)
        cases[name] = row
        if name.endswith("COMPANION"):
            row["comparison_role"] = "ADJACENT_PRICE_PATH_NOT_AUTHOR_ACTION_WINDOW"
        try:
            raw, coverage = {"1m": [], "5m": []}, []
            for day in days:
                identity = (contract, day)
                if identity not in first_opens:
                    try:
                        sessions = market.session_windows(symbol=contract[:-4].lower(), trading_day=day)
                        first_opens[identity] = (min(w.start for w in sessions), None)
                    except MarketDataError as exc:
                        first_opens[identity] = (None, exc.code)
                first_open, session_error = first_opens[identity]
                for period, step in (("1m", ONE), ("5m", FIVE)):
                    if session_error or first_open + step + US >= cut:
                        coverage.append(dict(trading_day=day, period=period, bars=0, error=session_error,
                                             first_open=first_open, needed_before_cutoff=None if session_error else False))
                        continue
                    key = (*identity, period)
                    if key not in reads:
                        try:
                            values = read_session_series(session, market, contract[:-4].lower(), contract, period, step, (day,))
                            reads[key] = (values, None)
                        except MarketDataError as exc:
                            reads[key] = ((), exc.code)
                        except ValueError:
                            reads[key] = ((), "SESSION_COVERAGE_UNVERIFIED")
                    values, error = reads[key]
                    raw[period].extend(values)
                    coverage.append(dict(trading_day=day, period=period, bars=len(values), error=error,
                                         first_open=first_open, needed_before_cutoff=True))
            row["coverage"] = coverage
            if any(item["error"] for item in coverage):
                row.update(status="LOCAL_DATA_UNVERIFIED", reason="REQUIRED_PHYSICAL_DAY_OR_PERIOD_MISSING")
                continue
            if contract == "JM2509":
                compare_frozen_july(raw["5m"], frozen=frozen, days=days)
            fives = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw["5m"]]
            verify_aggregation(fives, raw["1m"])
        except (ValueError, KeyError):
            row.update(status="LOCAL_DATA_UNVERIFIED", reason="SESSION_AGGREGATION_OR_FROZEN_OHLC_MISMATCH")
            continue
        row.update(status="WINDOW_READABLE", input={period: dict(count=len(bars), hash=sha(encoded([
                       (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in bars
                   ]).encode())) for period, bars in raw.items()})
        row.update(match((raw["1m"], fives), start, cut, levels))
    return dict(version="lms405-structure-crosscheck-v1", cases=cases, executable=False,
                anchor_scope="LOADED_PREFIX_THROUGH_FIXED_CUTOFF", frozen_july_sha256=INPUT_SHA256,
                admitted_author_samples=0, author_matches=None, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--july-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or not args.july_input.is_file() or args.output.exists():
        parser.error("INPUT_MISSING_OR_OUTPUT_EXISTS")
    raw = args.july_input.read_bytes()
    if sha(raw) != INPUT_SHA256:
        parser.error("FROZEN_INPUT_HASH_MISMATCH")
    frozen = list(csv.DictReader(StringIO(raw.decode("utf-8"))))
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), frozen)
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(report))


if __name__ == "__main__":
    main()
