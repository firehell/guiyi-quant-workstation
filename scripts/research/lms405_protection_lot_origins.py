"""Joint price bounds on the origin of the later displayed protection lots."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_leg_handoff import CLOSE, FIRST, GLASS, MORNING, SPECS_SHA
from lms405_fresh_reprotection import PAIR, PAIR_SHA
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import ONE
from lms405_rubber_leg_transition import CONTRACT as RUBBER
from lms405_rubber_leg_transition import LATER
from lms405_rubber_m_replacements import REFERENCE, REFERENCE_SHA, partition
from lms405_sh_lock_lifecycle import CONTRACT as CAUSTIC
from lms405_sh_lock_lifecycle import NIGHT, digest
from lms405_sh_recovery_progress import SNAPSHOTS, SNAPSHOTS_SHA
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

FRESH = Path("output/lms405-fresh-reprotection-20261126/reviewed.json")
FRESH_SHA = "e37c3efd709f4cd375b2db25d921452e47d2db4279c03d3a98ed707046b7eb8a"
RUBBER_GATES = Path("output/lms405-rubber-m-replacements-20261125/final.json")
RUBBER_GATES_SHA = "f91606c4311a08034969406d0939990c2f9a118e7f055cb0fb4997f39f002037"
BOUNDARIES = ("EVENT_MINUTE_ALLOWED_AFTER", "ONLY_COMPLETE_MINUTES_AFTER")
ORIGINS = ("retained", "new_before_first_gate", "new_between_gates", "new_after_second_gate")


def allocations(lots, previous, phases, old_totals, new_totals, *, require_no_retention=False):
    """Enumerate joint counts in tick envelopes. Counts describe ending lots only."""
    if not new_totals or (previous is not None and not old_totals) or len(phases) != 3:
        raise ValueError("LMS_LOT_ORIGINS_INVALID_AVERAGE_OR_WINDOWS")
    old_low, old_high = previous or (0, 0)
    phase_bounds = [bounds or (0, 0) for bounds in phases]
    valid = []
    for old in range(1 if require_no_retention or previous is None else lots + 1):
        replaced = lots - old
        if previous is None:
            kept_min, kept_max = 0, 0
        else:
            kept_min = max(old * old_low, old_totals.start - replaced * old_high)
            kept_max = min(old * old_high, old_totals.stop - 1 - replaced * old_low)
        if kept_min > kept_max:
            continue
        for before in range(replaced + 1):
            for mid in range(replaced - before + 1):
                additions = (before, mid, replaced - before - mid)
                if any(count and bounds is None for count, bounds in zip(additions, phases, strict=True)):
                    continue
                lower = kept_min + sum(n * lo for n, (lo, _) in zip(additions, phase_bounds, strict=True))
                upper = kept_max + sum(n * hi for n, (_, hi) in zip(additions, phase_bounds, strict=True))
                if lower <= new_totals.stop - 1 and upper >= new_totals.start:
                    valid.append((old, *additions))
    return valid


def phase_prices(minutes, gates, boundary, tick):
    first, second = gates
    if first >= second:
        raise ValueError("LMS_LOT_ORIGINS_UNORDERED_GATES")
    groups = ([], [], [])
    for bar in minutes:
        bucket = 2 if partition(bar, second, boundary) else int(partition(bar, first, boundary))
        groups[bucket].append(bar)
    return [tick_bounds(group, tick) for group in groups]


def evaluate(minutes, *, quotes, gates, tick, lots, old_avg, new_avg, new_start=None):
    old_totals = displayed_tick_totals(Decimal(old_avg), lots, tick) if old_avg else None
    new_totals = displayed_tick_totals(Decimal(new_avg), lots, tick)
    rows = {}
    combined = {boundary: set() for boundary in BOUNDARIES}
    for old_quote, quote in quotes:
        old_prices = tick_bounds([bar for bar in minutes if bar.end <= old_quote], tick) if old_quote else None
        # The old quote's own minute may straddle capture. Keeping it in the new envelope is permissive.
        new_minutes = [bar for bar in minutes if bar.end <= quote and (old_quote is None or bar.end >= old_quote)
                       and (new_start is None or bar.start >= new_start)]
        quote_key = f"{old_quote.isoformat() if old_quote else 'none'} / {quote.isoformat()}"
        rows[quote_key] = dict(old_price_envelope=old_prices)
        for boundary in BOUNDARIES:
            phases = phase_prices(new_minutes, gates, boundary, tick)
            allowed = allocations(lots, old_prices, phases, old_totals, new_totals,
                                  require_no_retention=new_start is not None)
            combined[boundary].update(allowed)
            rows[quote_key][boundary] = dict(
                price_envelopes=phases, feasible_count_allocations=len(allowed),
                retained_counts=sorted({row[0] for row in allowed}),
            )
    summaries = {}
    for boundary in BOUNDARIES:
        joint = sorted(combined[boundary])
        full = [row for row in joint if row[0] == 0]
        summaries[boundary] = dict(
            feasible_quote_cases=sum(bool(r[boundary]["feasible_count_allocations"]) for r in rows.values()),
            retained_counts=sorted({row[0] for row in joint}),
            full_rebuild_single_phase=[name for i, name in enumerate(ORIGINS[1:], start=1)
                                       if any(row[i] == lots for row in full)],
            any_full_rebuild=bool(full),
            min_earlier_new_if_rebuild=min((r[1] + r[2] for r in full), default=None),
            retained_if_all_replacement_after_second=sorted({r[0] for r in joint if r[1] == r[2] == 0 and r[3]}),
            joint_counts_across_quotes=joint,
        )
    return dict(gates=gates, old_opening_average=old_avg, new_opening_average=new_avg,
                old_opening_tick_totals=list(old_totals) if old_totals else None,
                new_opening_tick_totals=list(new_totals), quote_count=len(quotes),
                new_start=new_start, summaries=summaries, quotes=rows)


def study(session, market):
    pair = verified_json(PAIR, PAIR_SHA)
    fresh = verified_json(FRESH, FRESH_SHA)
    rubber = verified_json(REFERENCE, REFERENCE_SHA)
    rgates = verified_json(RUBBER_GATES, RUBBER_GATES_SHA)
    sh = verified_json(SNAPSHOTS, SNAPSHOTS_SHA)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    glass = pair["positions"][GLASS]
    for image in (glass[FIRST]["image"], glass[MORNING]["image"], glass[CLOSE]["image"], rubber["source_images"][FIRST],
                  rubber["source_images"][LATER], sh["snapshots"][NIGHT]["image"]):
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("LMS_LOT_ORIGINS_IMAGE_CHANGED")
    rw = fresh["cases"][GLASS]["windows"]["after_full_morning_post_minute"]
    sw = fresh["cases"][CAUSTIC]["windows"]["night"]
    iso = datetime.fromisoformat

    def gates(window):
        (shape,) = window["shape_candidates"]["1m_to_1m"]
        return iso(shape["confirmed_at"]), iso(window["first_touch_bar_end"])

    gquotes = [(iso(a), iso(b)) for a in pair["quote_anchors"][GLASS][FIRST]
               for b in pair["quote_anchors"][GLASS][CLOSE]]
    rquotes = [(iso(a), iso(b)) for a, values in rubber["pairwise_conditional_bounds"].items() for b in values]
    sh_late = fresh["cases"][CAUSTIC]["visible_long"]
    sh_today = sh["with_night_today_quantity"]
    if sh_today["today_quantity"] != sh_late["quantity"] or sh_today["prior_displayed_long_lots_retained"] != 0:
        raise ValueError("LMS_LOT_ORIGINS_TODAY_SCOPE_CHANGED")
    glass_first, glass_late = (glass[post]["legs"]["long"] for post in (FIRST, CLOSE))
    if (not glass_first["quantity"] == glass_late["quantity"] == glass_first["today_quantity"] == glass_late["today_quantity"]
            or not rubber["initial"]["lots"] == rubber["initial"]["today"] == rubber["later"]["lots"] == rubber["later"]["today"]):
        raise ValueError("LMS_LOT_ORIGINS_SAME_DAY_TODAY_FIELDS_CHANGED")
    windows = {
        GLASS: (date(2026, 10, 23), gquotes, gates(rw), glass_first["opening_average"],
                glass_late["opening_average"], glass_late["quantity"]),
        RUBBER: (date(2026, 10, 23), rquotes, tuple(iso(rgates["gates"][name]["end"]) for name in (
            "protection_near_1m_to_1m_same_run", "m_near_touch",
        )), rubber["initial"]["opening_average"], rubber["later"]["opening_average"], rubber["later"]["lots"]),
        CAUSTIC: (date(2026, 10, 28), [(None, iso(sw["price_cut_exclusive"]) - ONE)], gates(sw),
                  None, sh_late["opening_average"], sh_late["quantity"]),
    }
    source_ids = {GLASS: (FIRST, CLOSE), RUBBER: (FIRST, LATER), CAUSTIC: (NIGHT,)}
    cases = {}
    for contract, (day, quotes, clocks, old_avg, new_avg, lots) in windows.items():
        minutes = read_window(session, market, contract, day)[1]
        fingerprint = digest(minutes)
        expected = rgates["market"]["1m"]["sha256"] if contract == RUBBER else fresh["market"][contract]["1m"]
        if fingerprint != expected:
            raise ValueError("LMS_LOT_ORIGINS_MARKET_CHANGED")
        args = dict(gates=clocks, tick=specs[contract]["tick"], lots=lots, old_avg=old_avg, new_avg=new_avg)
        cases[contract] = evaluate(minutes, quotes=quotes, **args) | dict(
            trading_day=day, market_sha256=fingerprint, position_source_ids=source_ids[contract],
        )
        if contract == GLASS:
            # Sensitivity only: the morning screen did not show the long leg.
            post = iso(glass[MORNING]["published_at"]) + ONE
            cases[contract]["if_zero_at_morning_post"] = evaluate(minutes, quotes=quotes, new_start=post, **args) | dict(
                conditional_source=MORNING, observed_morning_long_quantity=None,
            )
        if contract == CAUSTIC:
            cases[contract]["confirmed_today_field_scope"] = sh_today
            cases[contract]["later_quote_clock"] = "LAST_COMPLETED_MINUTE_BEFORE_POST_NOT_CAPTURE_TIME"
    return dict(version="lms405-protection-lot-origins-v1", origin_columns=ORIGINS, cases=cases,
                phase_clock=dict(
                    event_minute_allowed_after="GATE_MINUTE_END_GREATER_OR_EQUAL_IS_LATER",
                    only_complete_minutes_after="MINUTE_START_STRICTLY_GREATER_THAN_GATE_END_IS_LATER",
                    strict_middle_can_include_second_gate_and_availability_overlapping_minute=True,
                ),
                references=dict(pair=PAIR_SHA, fresh=FRESH_SHA, rubber=REFERENCE_SHA, rubber_gates=RUBBER_GATES_SHA,
                                caustic_today=SNAPSHOTS_SHA, specifications=SPECS_SHA),
                scope="CONDITIONAL_SAME_ACCOUNT_PRICE_ENVELOPES_ONLY", actual_actions=None,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    load_dotenv(args.env_file, override=False)
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "LMS_LOT_ORIGINS_EVIDENCE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
