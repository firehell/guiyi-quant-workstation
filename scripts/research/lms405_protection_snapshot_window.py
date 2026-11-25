"""Audit protection-leg timing under alternative scopes of the same holdings screenshot."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_i2701_case import readback
from lms405_portfolio_replay import ARCHIVE, BOOK
from lms405_protection_lot_timing import (
    EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json,
)
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
SNAPSHOT = "WRov1j6e10"
REFERENCES = {
    "exposure": (EXPOSURE, EXPOSURE_SHA256),
    "quotes": (Path("output/lms-v-ta-oct-20261125/comparison.json"),
               "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"),
    "shapes": (Path("output/lms405-shape-audit-20261125/report.json"),
               "692ad01e734a6a47d27f063e2b87299e9ce7f9d0aa3d060d444e11392c552079"),
    "lots": (Path("output/lms405-protection-lot-timing-20261125/final.json"),
             "6a61d2ea4463ed8b2115ddc59d90a4726f53c23db44970f58c45307eafc925e8"),
}


def price_window(bars, tick, lots, totals):
    envelope = tick_bounds(bars, tick)
    earliest = None
    if earlier_lot_counts(None, envelope, lots, totals):
        low, high = tick_bounds(bars[:1], tick)
        for bar in bars:
            a, b = tick_bounds((bar,), tick)
            low, high = min(low, a), max(high, b)
            if earlier_lot_counts(None, (low, high), lots, totals):
                earliest = display(bar.bar_end)
                break
    return dict(minute_count=len(bars), envelope_ticks=envelope, first_compatible_prefix_end=earliest,
                whole_leg_price_possible=earliest is not None)


def snapshot_context(exposure, quotes):
    (row,) = [row for row in exposure["tables"] if row["source"] == SNAPSHOT]
    raw = (BOOK.with_name("portfolio-oct-table-totals.json")).read_bytes()
    (totals,) = [table for table in json.loads(raw) if table["source"] == SNAPSHOT]
    quantities = [leg["quantity"] for contract in row["contracts"].values() for leg in contract["legs"].values()]
    quantities += [qty for contract in totals["other_legs"].values() for qty in contract.values()]
    if (row["system"] != "4.0.5" or len(quantities) != totals["row_count"] or sum(quantities) != totals["total_lots"]
            or sha((ARCHIVE.parent / row["image"]["path"]).read_bytes()) != row["image"]["sha256"]):
        raise ValueError("PROTECTION_SNAPSHOT_SOURCE_OR_TOTALS_CHANGED")
    if any(set(row["contracts"][contract]["legs"]) != {"short"} for contract in ("I2701", "SH2701")):
        raise ValueError("PROTECTION_SNAPSHOT_VISIBLE_SIDES_CHANGED")
    matches_by_minute = {}
    for product, values in quotes["per_symbol"].items():
        for minute in values["contains"]:
            matches_by_minute.setdefault(minute, []).append(product)
    most = max(map(len, matches_by_minute.values()))
    (partial,) = [minute for minute, matches in matches_by_minute.items() if len(matches) == most]
    if quotes["joint_contains"] or most != 8 or set(quotes["per_symbol"]) - set(matches_by_minute[partial]) != {"jm"}:
        raise ValueError("PROTECTION_SNAPSHOT_PARTIAL_ANCHOR_CHANGED")
    return dict(source=SNAPSHOT, image=row["image"], published_at=row["published_at"],
                displayed_rows=totals["row_count"], displayed_lots=totals["total_lots"],
                covers_account=None, partial_quote_anchor=partial, partial_matches=sorted(matches_by_minute[partial]),
                joint_quote_anchor=None, table_totals_source_sha256=sha(raw))


def study(session, market, refs):
    snapshot = snapshot_context(refs["exposure"], refs["quotes"]["photos"][SNAPSHOT])
    anchor = datetime.fromisoformat(snapshot["partial_quote_anchor"])
    later_cut = datetime.fromisoformat(snapshot["published_at"]) + ONE
    day_open = at("2026-10-27T09:00")
    cases = {}
    for contract in ("I2701", "SH2701"):
        symbol = contract[:-4].lower()
        bars = read_session_series(session, market, symbol, contract, "1m", ONE, (DAY,))
        frozen = refs["lots"]["cases"][contract]
        if readback(bars)[DAY.isoformat()] != frozen["market"]:
            raise ValueError("PROTECTION_SNAPSHOT_MARKET_CHANGED")
        cutoff = datetime.fromisoformat(frozen["cutoff"])
        tick, lots = Decimal(frozen["tick_size"]), frozen["observed_lots"]
        totals = displayed_tick_totals(Decimal(frozen["displayed_opening_average"]), lots, tick)
        visible = [bar for bar in bars if bar.bar_end + US < cutoff]
        overnight = [bar for bar in visible if anchor < bar.bar_end <= day_open]
        daytime = [bar for bar in visible if bar.bar_end > day_open]
        geometries = refs["shapes"]["cases"][contract]["inspections"].values()
        existing = [event for group in geometries for key in ("existing", "outside") for event in group[key]]
        usable = [event for event in existing if event["whole_leg_price_compatible"] is True]
        prior = [row for row in usable if datetime.fromisoformat(row["available_at"]) <= anchor]
        low = min(bar.low for bar in bars)
        cases[contract] = dict(
            observed_lots=lots, displayed_opening_average=frozen["displayed_opening_average"],
            upper_price_cutoff=cutoff, new_whole_leg_price_windows={
                "after_partial_quote_during_night": price_window(overnight, tick, lots, totals),
                "after_publication_minute_during_night": price_window(
                    [bar for bar in overnight if bar.bar_end - ONE >= later_cut], tick, lots, totals,
                ),
                "daytime_only": price_window(daytime, tick, lots, totals),
            },
            night_lots_if_whole_leg_started_after_partial_quote=earlier_lot_counts(
                tick_bounds(overnight, tick), tick_bounds(daytime, tick), lots, totals,
            ),
            price_compatible_candidates_before_or_at_partial_quote=prior,
            early_candidate_price_windows=[
                dict(event=row, before_partial_quote=price_window(
                    [bar for bar in visible if datetime.fromisoformat(row["confirmed_at"]) < bar.bar_end <= anchor],
                    tick, lots, totals,
                )) for row in prior
            ],
            price_compatible_candidates_after_partial_quote=[
                row for row in usable if datetime.fromisoformat(row["available_at"]) > anchor
            ],
            actual_long_absent_from_account_at_partial_quote=None,
            reported_1475_observations=(
                [display(bar.bar_end) for bar in bars if bar.low <= Decimal("1475")] if contract == "SH2701" else None
            ),
            local_full_day_low=low, first_local_full_day_low_at=display(next(bar.bar_end for bar in bars if bar.low == low)),
        )
    return dict(
        version="lms405-protection-snapshot-window-v1", snapshot=snapshot, cases=cases,
        references={key: digest for key, (_, digest) in REFERENCES.items()},
        author_action_at=None, author_action_samples=0, fills=None, pnl=None, executable=False,
    )


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
        refs = {key: verified_json(path, digest) for key, (path, digest) in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=30):
            report = study(session, build_market_data_service(session), refs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "PROTECTION_SNAPSHOT_WINDOW_UNVERIFIED\n")


if __name__ == "__main__":
    main()
