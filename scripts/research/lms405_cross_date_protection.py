"""Check October 27 local/shared protection clocks on the October 22 six-leg photo."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_first_night_confirmation_clocks import DAY, POST, START
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_oi_ru_signal_deadlines import candidate_clocks, combine_support
from lms405_pa_signal_deadline import comparison, minute_ticks, quantity_support, time_constraints
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import published_protection_events
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

OCT27 = (Path("output/lms405-three-night-deadlines-20261126/final-a.json"),
         "609ca99cf782fb570256638cfdd758e18df49095c7a7dcdf1cfc1a5fdb689af0")


def quote_prefix(minutes, end, mode):
    if mode == "strict_before_quote_start":
        return [bar for bar in minutes if bar.end + US < end - ONE]
    if mode == "exclude_quote_bar_by_end_label":
        return [bar for bar in minutes if bar.end < end]
    if mode == "include_whole_quote_bar_sensitivity":
        return [bar for bar in minutes if bar.end <= end]
    raise ValueError("CROSS_DATE_UNKNOWN_QUOTE_MODE")


def common_bound(leg_bounds):
    if any(bound is None for bound in leg_bounds.values()):
        return dict(deadline_exclusive=None, full_window_incompatible_legs=[
            c for c, bound in leg_bounds.items() if bound is None], binding_legs=[])
    deadline = min(leg_bounds.values())
    return dict(deadline_exclusive=deadline, full_window_incompatible_legs=[],
                binding_legs=[c for c, bound in leg_bounds.items() if bound == deadline])


def quote_bar_lots(minutes, end, *, tick, lots, totals):
    before = {k for b in minutes if b.end < end for k in minute_ticks(b, tick)}
    coincident = {k for b in minutes if b.end == end for k in minute_ticks(b, tick)}
    return min(quantity_support(coincident, before, lots, totals), default=None)


def local_candidates(contract, series, band, plan, cutoff):
    if band is None:
        return dict(positioned=None, advance=None, first_touch=None, issue="NO_UNAMBIGUOUS_PROTECTION_BAND")
    geometry = candidate_clocks(series, START, cutoff, band, "PROTECTION_SEARCH_REFERENCE", None)
    published = datetime.fromisoformat(plan["published_at"]) + ONE
    region = ProtectionBandUpdate(contract, plan["id"], "PROTECTION", published, published,
                                  plan["id"], "SHORT", *band)
    early = next((row for row in published_protection_events(series, (region,), cutoff)
                  if row["operation"] == "PROTECT_EARLY"), None)
    return dict(positioned=next(iter(geometry["candidates"]), None),
                advance=early["signal"] | {"period": early["period"]} if early else None,
                first_touch=geometry["contact"], issue=None)


def study(session, market):
    old = verified_json(REFERENCE, REFERENCE_HASH)
    later = verified_json(*OCT27)
    source_ids = input_sources()
    photo = old["photo"]
    if (sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]
            or later["raw_quote_combinations"]["same_label_count"] != 0):
        raise ValueError("CROSS_DATE_REFERENCE_CHANGED")
    data, candidates, sources, matches = {}, {}, {}, {}
    for contract, row in old["cases"].items():
        series = read_window(session, market, contract, DAY)
        if {f"{p}m": digest(bars) for p, bars in series.items()} != row["market"]:
            raise ValueError("CROSS_DATE_MARKET_CHANGED")
        minutes = completed(series[1], START, POST)
        mark = Decimal(row["quote"])
        ends = {b.end for b in minutes if b.low <= mark <= b.high}
        if ends != {datetime.fromisoformat(t) for t in row["individual_quote_ends"]}:
            raise ValueError("CROSS_DATE_QUOTE_CHANGED")
        matches[contract] = ends
        previous_plan = row["plan"]
        plan_id, = [key for key, value in source_ids.items() if value["archive_path"] == previous_plan["archive_path"]]
        plan = load_source(source_ids, plan_id)
        if plan != previous_plan or datetime.fromisoformat(plan["published_at"]) + ONE >= START:
            raise ValueError("CROSS_DATE_PLAN_CHANGED")
        sources[contract] = plan | {"id": plan_id}
        leg, old_short = row["displayed_long"], row["original_short"]
        lots, tick = leg["quantity"], Decimal(row["tick"])
        if (lots != leg["today_quantity"] or lots != old_short["quantity"] or old_short["today_quantity"] != 0):
            raise ValueError("CROSS_DATE_LEG_SCOPE_CHANGED")
        band = tuple(map(Decimal, row["protection_band"])) if row["protection_band"] is not None else None
        candidates[contract] = dict(band=band, **local_candidates(contract, series, band, sources[contract], POST))
        data[contract] = dict(series=series, minutes=minutes, price=dict(tick=tick, lots=lots,
                             totals=displayed_tick_totals(Decimal(row["average"]), lots, tick), band=None))
    quote, = set.intersection(*matches.values())
    if quote - ONE <= START:
        raise ValueError("CROSS_DATE_COMMON_QUOTE_CHANGED")

    cutoff = quote - ONE
    local_gates = {}
    for contract, row in candidates.items():
        in_scope = local_candidates(contract, data[contract]["series"], row["band"], sources[contract], cutoff)
        prefix = {p: [b for b in rows if b.end + US < cutoff] for p, rows in data[contract]["series"].items()}
        if local_candidates(contract, prefix, row["band"], sources[contract], cutoff) != in_scope:
            raise ValueError("CROSS_DATE_LOCAL_PREFIX_CHANGED")
        local_gates[contract] = min((event["available_at"] for key in ("positioned", "advance")
                                     if (event := in_scope[key]) is not None), default=None)
    known = [value for value in local_gates.values() if value is not None]
    common_gates = {
        "opening_benchmark_price_only": START - US,
        "first_opening_bar_price_only": START + ONE + US,
        "first_available_local_candidate": min(known),
        "last_available_local_candidate": max(known),
    }
    audit = {}
    for mode in ("strict_before_quote_start", "exclude_quote_bar_by_end_label", "include_whole_quote_bar_sensitivity"):
        bounds, legs = {}, {}
        for contract, entry in data.items():
            rows = quote_prefix(entry["minutes"], quote, mode)
            bound = time_constraints(rows, event_clocks={}, quote_end=quote,
                                     **entry["price"])["latest_strict_signal_knowledge_bound_exclusive"]
            if bound is not None:
                before = comparison(rows, gate_known_at=bound - US, **entry["price"])
                at_bound = comparison(rows, gate_known_at=bound, **entry["price"])
                if not before["whole_leg_with_later_prices"] or at_bound["whole_leg_with_later_prices"]:
                    raise ValueError("CROSS_DATE_DEADLINE_EDGE_CHANGED")
            bounds[contract] = bound
            gates = common_gates | {"first_own_candidate": local_gates[contract]}
            legs[contract] = {name: comparison(rows, gate_known_at=clock, **entry["price"])
                              for name, clock in gates.items()}
        totals = {name: combine_support(tuple(x[name]["whole_leg_with_later_prices"] for x in legs.values()))
                  for name in (*common_gates, "first_own_candidate")}
        audit[mode] = dict(leg_deadlines_exclusive=bounds, common_price_deadline=common_bound(bounds),
                           by_contract=legs, every_leg_price_compatible=totals)
    quote_lots = {}
    for contract, entry in data.items():
        price = entry["price"]
        quote_lots[contract] = quote_bar_lots(entry["minutes"], quote, tick=price["tick"], lots=price["lots"],
                                             totals=price["totals"])
    return dict(
        version="lms405-cross-date-protection-quote-study-v1", photo=photo, local=candidates,
        plans=sources, trading_day=DAY, locatable_quote_end=quote, exact_capture_verified=False,
        independent_hypotheses=local_gates, common_price_hypotheses=common_gates, price_window_audit=audit,
        minimum_lots_at_quote_bar_prices_if_whole_bar_allowed=quote_lots,
        common_gates_do_not_supply_missing_local_authorization=True,
        earliest_and_latest_gate_use_only_nonmissing_candidates=True,
        known_local_scope_comparison="DEVELOPMENT_SAMPLE_NOT_BLIND",
        reference=dict(oct22=REFERENCE_HASH, oct27=OCT27[1]),
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('CROSS_DATE_') else 'CROSS_DATE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
