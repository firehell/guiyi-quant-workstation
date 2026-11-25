"""Check which protection-leg claims survive the oil, glass and caustic-soda evidence."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_leg_handoff import CLOSE, FIRST, GLASS, MORNING
from lms405_fresh_reprotection import PAIR, PAIR_SHA
from lms405_i2701_case import FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_oi_leg_intent import CONTRACT as OIL
from lms405_oi_leg_intent import CUT, DAY, OCT27_QUOTES, START, first_contact, lot_bound
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_replay import display
from lms405_right_side_study import US
from lms405_rubber_quote_windows import price_constraints
from lms405_sh_lock_lifecycle import NIGHT, completed, digest
from lms_near405_replay import encoded, sha

VERSION = "lms405-protection-origin-comparison-v1"
NIGHT_IMAGE = Path("02-持仓记录/2026-10-27/RoEvasxQR-position-screen.png")
NIGHT_IMAGE_SHA = "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a"
REFERENCES = {
    "oil": (Path("output/lms405-oi-leg-intent-20261125/final.json"),
            "9658a0c6ce83b51f0bd21e290667d783a1b8e24c66624cb1d797ffcd56664dad"),
    "quotes": (OCT27_QUOTES, FROZEN_COMPARISON_SHA256),
    "glass": (PAIR, PAIR_SHA),
    "lot_origins": (Path("output/lms405-protection-lot-origins-20261126/scoped.json"),
                    "69643cf155a2b23eee1746db0fabe5c5a8a9f707e435000ef6daadeae890f4ac"),
    "caustic": (Path("output/lms405-sh-cycle-permissions-20261126/final-a.json"),
                "f69045985afb4b72644c450627ba269eb35c3153361d6138964ffe8c022920a6"),
}


def quote_minute_bounds(minutes, quote_end, *, gates, tick, lots, average, band):
    """Allow all prices in the quote minute. Return necessary counts, with no inferred fills."""
    prefix = [b for b in minutes if b.end <= quote_end]
    if not prefix or prefix[-1].end != quote_end:
        raise ValueError("OI_CONDITIONAL_QUOTE_BAR_MISSING")
    totals = displayed_tick_totals(average, lots, tick)
    paths = {name: lot_bound(prefix, gate, tick=tick, lots=lots, totals=totals) for name, gate in gates.items()}
    return dict(timing=paths, price=price_constraints(prefix, tick=tick, lots=lots, average=average, band=band))


def oil_case(session, market, frozen, quotes):
    raw, series = read_pair(session, market, OIL, (DAY,))
    market_bindings = dict(readback_1m=readback(raw[1])[DAY.isoformat()],
                           digest_5m=dict(count=len(series[5]), sha256=digest(series[5])))
    if market_bindings != dict(readback_1m=frozen["market"]["1m"], digest_5m=frozen["market"]["5m"]):
        raise ValueError("OI_ORIGIN_MARKET_CHANGED")
    for record in frozen["sources"].values():
        if sha((ARCHIVE.parent / record["archive_path"]).read_bytes()) != record["archive_sha256"]:
            raise ValueError("OI_ORIGIN_SOURCE_CHANGED")
    if sha((ARCHIVE.parent / NIGHT_IMAGE).read_bytes()) != NIGHT_IMAGE_SHA:
        raise ValueError("OI_ORIGIN_NIGHT_IMAGE_CHANGED")
    transition = frozen["snapshot_transition"]
    end_long = transition["later_legs"]["long"]
    qty = end_long["quantity"]
    if ("long" in transition["earlier_legs"] or qty != end_long["today_quantity"]
            or transition["same_trading_day"] or transition["sides"]["short"]["bounds"] != [40, 40]):
        raise ValueError("OI_ORIGIN_SNAPSHOT_SCOPE_CHANGED")
    minutes = completed(series[1], START, CUT)
    quote = quotes["photos"][NIGHT]["per_symbol"]["oi"]
    mark = Decimal(quote["mark"])
    candidates = [b for b in minutes if b.low <= mark <= b.high]
    if [display(b.end) for b in candidates] != quote["contains"]:
        raise ValueError("OI_ORIGIN_QUOTE_WINDOWS_CHANGED")
    band = tuple(map(Decimal, frozen["divider"]))
    touch = first_contact(minutes, band)
    settled = next(b for b in minutes if band[0] <= b.close <= band[1])
    if (display(touch.end) != frozen["first_divider_contact_minute"]["end"]
            or display(settled.end) != frozen["first_divider_close_inside"]):
        raise ValueError("OI_ORIGIN_DIVIDER_TIME_CHANGED")
    gates = dict(touch_minute_included=touch.start, touch_known_strict=touch.end + US,
                 first_close_inside_known_strict=settled.end + US)
    gates.update((f"pre_divider_geometry_{i}", datetime.fromisoformat(event["available_at"]))
                 for i, event in enumerate(frozen["geometry"]["1m_to_1m"], 1)
                 if event["earlier_than_first_divider_contact_bar"])
    leg = dict(tick=Decimal(frozen["spec"]["tick"]), lots=qty, average=Decimal(frozen["opening_average"]), band=band)
    conditional = {display(bar.end): quote_minute_bounds(minutes, bar.end, gates=gates, **leg) for bar in candidates}
    return dict(contract=OIL, evidence_sources=frozen["sources"], observed_divider=band, role="RANGE_DIVIDER",
                market=market_bindings, gate_times=gates, row_quote=mark, conditional_quote_minutes=conditional,
                quote_clock_scope="COMPLETE_QUOTE_MINUTE_ALLOWED_FOR_RETROSPECTIVE_BOUND_ONLY",
                end_long_lots=qty, end_long_today_lots=end_long["today_quantity"], prior_long_lots=None,
                end_long_from_prior_trading_day_if_same_account=0, assumed_original_short_retention=[40, 40],
                old_protection_proven=None, in_scope_protection_permission=None, author_long_task=None,
                scope="NEW_OPPOSITE_EXPOSURE_WITH_UNRESOLVED_INTENT")


def compare(oil, glass, origins, caustic):
    for row in glass["positions"][GLASS].values():
        image = row["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("GLASS_ORIGIN_ATTACHMENT_CHANGED")
    carry = glass["continuity_on_assumed_same_account"]
    if (not carry["glass_night_to_morning"]["inconsistent_same_scope"]
            or carry["glass_morning_to_close"]["bounds"] != [20, 20]
            or "long" in glass["positions"][GLASS][MORNING]["legs"]):
        raise ValueError("GLASS_ORIGIN_OBSERVATION_CHANGED")
    glass_origins = origins["cases"][GLASS]
    if origins["references"]["pair"] != PAIR_SHA or glass_origins["position_source_ids"] != [FIRST, CLOSE]:
        raise ValueError("GLASS_ORIGIN_INPUT_SCOPE_CHANGED")
    partial = glass_origins["summaries"]["ONLY_COMPLETE_MINUTES_AFTER"]
    display = {key: glass["positions"][GLASS][key]["legs"] for key in (FIRST, MORNING, CLOSE)}
    complete = [key for key, trial in caustic["scenarios"].items() if trial["matches_new_long_quantity_constraint"]]
    return dict(version=VERSION, cases={OIL: oil, GLASS: dict(
        source_ids=list(display), legs_at_source=display, inconsistent_original_short_chain=True,
        assumed_morning_to_close_short_retention=[20, 20], morning_long_lots=None,
        single_side_possible_retained=partial["retained_counts"],
        single_side_retained_if_all_new_lots_after_near=partial["retained_if_all_replacement_after_second"],
        single_side_minimum_earlier_lots_if_no_retention=partial["min_earlier_new_if_rebuild"],
        scope="CONDITIONAL_SINGLE_SIDE_BOUNDS_NO_CONTINUOUS_ACCOUNT_JOIN",
    ), "SH2701": dict(
        source_ids=list(caustic["sources"]), allowed_fixture_paths=complete,
        day_trading_date=caustic["day_trading_date"], night_trading_date=caustic["night_trading_date"],
        scope="SEPARATE_PERMISSION_FIXTURES_MATCH_NEW_LONG_QUANTITY_ONLY_UNDER_ASSUMPTION",
    )}, inputs={key: fingerprint for key, (_, fingerprint) in REFERENCES.items()},
        actual_account_continuity=None, author_actions_scored=0, author_match_rate=None,
        executable=False, fills=None, pnl=None)


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
        refs = {key: verified_json(path, fingerprint) for key, (path, fingerprint) in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            oil = oil_case(session, build_market_data_service(session), refs["oil"], refs["quotes"])
        report = compare(oil, refs["glass"], refs["lot_origins"], refs["caustic"])
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        reason = str(exc)
        parser.exit(2, (reason if reason.startswith(("OI_ORIGIN_", "GLASS_ORIGIN_")) and reason.isidentifier()
                        else "PROTECTION_ORIGIN_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
