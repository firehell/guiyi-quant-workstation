"""Test separate and shared protection clocks for two visible 4.0.5 night legs."""

import argparse
from datetime import datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, check_images, retention_row
from lms405_oi_leg_intent import DISPLAYED_OPENING_AVERAGE
from lms405_oi_ru_next_session import CLOSE, DAY, NIGHT, OI_PLAN, RU_PLAN, market_identity
from lms405_pa_signal_deadline import comparison, minute_ticks, quantity_support, time_constraints
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_replay import input_sources
from lms405_portfolio_task_policy import published_protection_events
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_next_night_replay import OI, OI_SHA, TOUCH, TOUCH_SHA
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded

VERSION = "lms405-oi-ru-signal-deadlines-v1"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
CONFIG = {
    "OI2701": (OI_PLAN, "RANGE_DIVIDER", (Decimal(10240), Decimal(10283)), None),
    "RU2701": (RU_PLAN, "PROTECTION_SEARCH_REFERENCE", (Decimal(19360), Decimal(19405)), Decimal(19515)),
}
THREE_CONFIG = CONFIG | {"SH2701": (RU_PLAN, "PROTECTION_SEARCH_REFERENCE", (Decimal(1490), Decimal(1501)), Decimal(1513))}
COMMON_THREE = (Path("output/lms405-common-protection-oct27-20261125/final.json"),
                "1f8faeba34873d4be26cb01145dbb994305c01aa45a0af3d905ea35442f09264")


def first_time(rows, predicate):
    return next((bar.end for bar in rows if predicate(bar)), None)


def candidate_clocks(series, start, before, band, role, m):
    """Use author roles as inputs. OI's divider remains a price-only control."""
    minutes = completed(series[1], start, before)
    low, high = band

    def contact(bar):
        return bar.low <= high and bar.high >= low

    candidates = []
    for shape, confirmation in VARIANTS:
        shapes = {bar.end: bar for bar in series[shape] if bar.end + US < before}
        for event in signals(series, shape, confirmation, side="LONG", start=start, cut=before):
            if role == "PROTECTION_SEARCH_REFERENCE":
                if not (low <= event["close"] <= high or (
                    high < event["close"] and contact(shapes[event["shape_end"]])
                )):
                    continue
            candidates.append(event | {"clock": f"{shape}m_to_{confirmation}m"})
    candidates.sort(key=lambda event: (event["available_at"], event["clock"]))
    return dict(opening=minutes[0].end, contact=first_time(minutes, contact),
                close_inside=first_time(minutes, lambda b: low <= b.close <= high),
                close_above=first_time(minutes, lambda b: b.close > high),
                m_touch=first_time(minutes, lambda b: b.high >= m) if m is not None else None,
                candidates=candidates)


def minimum_outside_band(rows, *, band, tick, lots, totals, side):
    ticks = {value for bar in rows for value in minute_ticks(bar, tick)}
    edge = band[0] / tick if side == "BELOW" else band[1] / tick
    outside = {value for value in ticks if (value < edge if side == "BELOW" else value > edge)}
    return min(quantity_support(outside, ticks - outside, lots, totals), default=None)


def gate_check(rows, known_at, *, tick, lots, totals):
    if not rows:
        raise ValueError("OI_RU_DEADLINE_EMPTY_WINDOW")
    if known_at is None:
        return dict(known_at=None, candidate_ready_at_boundary=False,
                    price_compatible=None, minimum_lots_outside_strict_minutes=None)
    raw = comparison(rows, gate_known_at=known_at, lots=lots, totals=totals, tick=tick, band=None)
    return dict(known_at=known_at, candidate_ready_at_boundary=True, price_compatible=raw["whole_leg_with_later_prices"],
                minimum_lots_outside_strict_minutes=raw["minimum_outside_later_price_set"])


def both_ready(left, right):
    return max(left, right) if left is not None and right is not None else None


def combine_support(checks):
    if False in checks:
        return False
    return True if all(check is True for check in checks) else None


def evaluate_pair(data, quote_end, *, include_quote_minute):
    boundary = quote_end if include_quote_minute else quote_end - ONE
    cutoff = boundary + 2 * US
    cases, prefixes = {}, {}
    for contract, entry in data.items():
        rows = [bar for bar in entry["minutes"] if bar.end <= boundary]
        prefixes[contract] = rows
        clocks = candidate_clocks(entry["series"], entry["start"], cutoff, entry["band"], entry["role"], entry["m"])
        expected = dict(
            **{key: value if value is not None and value + US < cutoff else None
               for key, value in entry["post_clocks"].items() if key != "candidates"},
            candidates=[event for event in entry["post_clocks"]["candidates"] if event["available_at"] < cutoff],
        )
        if clocks != expected:
            raise ValueError("OI_RU_DEADLINE_PREFIX_DIVERGED")
        args = entry["price"]
        cases[contract] = dict(
            clocks=clocks, strict_knowledge_before=time_constraints(
                rows, event_clocks={}, quote_end=quote_end, band=None, **args,
            )["latest_strict_signal_knowledge_bound_exclusive"],
            minimum_below_reference=minimum_outside_band(rows, band=entry["band"], side="BELOW", **args),
            minimum_above_reference=minimum_outside_band(rows, band=entry["band"], side="ABOVE", **args),
        )
    oil, rubber = (cases[key]["clocks"] for key in CONFIG)
    oil_geom, rubber_geom = (next((e["available_at"] for e in row["candidates"]), None) for row in (oil, rubber))
    simultaneous = both_ready(oil_geom, rubber_geom)
    divider_known = oil["contact"] + US if oil["contact"] is not None else None
    rubber_m_known = rubber["m_touch"] + US if rubber["m_touch"] is not None else None
    policies = {
        "SEPARATE_APPROXIMATE_GEOMETRY": (oil_geom, rubber_geom),
        "SHARED_CLOCK_AFTER_BOTH_APPROXIMATE_GEOMETRIES": (simultaneous, simultaneous),
        "BOTH_WAIT_FOR_OI_DIVIDER_TOUCH": (divider_known, divider_known),
        "RU_WAIT_FOR_M_TOUCH": (oil_geom, rubber_m_known),
    }
    results = {}
    for name, pair in policies.items():
        legs = {contract: gate_check(prefixes[contract], gate, **data[contract]["price"])
                for contract, gate in zip(CONFIG, pair, strict=True)}
        results[name] = dict(legs=legs, both_price_compatible=combine_support(
            tuple(row["price_compatible"] for row in legs.values()),
        ))
    bounds = tuple(row["strict_knowledge_before"] for row in cases.values())
    joint_bound = min(bounds) if all(bound is not None for bound in bounds) else None
    return dict(quote_end=quote_end, quote_minute_in_price_envelope=include_quote_minute,
                shared_strict_knowledge_limit_exclusive=joint_bound, cases=cases, policies=results)


def study(session, market):
    retention = verified_json(RETENTION, RETENTION_SHA)
    spec = load_specs(verified_json(SPECS, SPECS_SHA))
    oil = verified_json(OI, OI_SHA)
    rubber = verified_json(TOUCH, TOUCH_SHA)["cases"]["ru_before_m"]
    photos = retention["snapshot_sources"]
    check_images(photos[CLOSE], photos[NIGHT])
    index, quotes = input_sources(), scoped_input_quotes()
    post = datetime.fromisoformat(photos[NIGHT]["published_at"])
    data, results, row_matches = {}, {}, {}
    for contract, (plan_id, role, band, m) in CONFIG.items():
        plan = load_source(index, plan_id)
        series = read_window(session, market, contract, DAY)
        start = series[1][0].start
        identity = market_identity(series)
        if (identity["1"] != retention["contracts"][contract]["market"][str(DAY)]
                or not datetime.fromisoformat(plan["published_at"]) + ONE < start < post):
            raise ValueError("OI_RU_DEADLINE_MARKET_OR_PLAN_CHANGED")
        prior = retention_row(retention, contract, CLOSE, NIGHT, "short")
        long_context = retention_row(retention, contract, CLOSE, NIGHT, "long")
        observed = long_context["later_leg"]
        lots, tick = observed["quantity"], spec[contract]["tick"]
        average = DISPLAYED_OPENING_AVERAGE if contract == "OI2701" else Decimal(rubber["visible_leg"]["display_average"])
        if (observed["today_quantity"] != lots or prior["later_leg"]["today_quantity"] != 0
                or prior["retained"] != [lots] or long_context["earlier_leg"] is not None
                or Decimal(observed["opening_average"]) != average):
            raise ValueError("OI_RU_DEADLINE_LEG_ORIGIN_CHANGED")
        if contract == "RU2701" and (rubber["plan"]["archive_sha256"] != plan["archive_sha256"]
                or tuple(map(Decimal, rubber["band"])) != band
                or rubber["visible_leg"]["image"] != photos[NIGHT]["image"]
                or rubber["market"] != {f"{period}m": digest(rows) for period, rows in series.items()}):
            raise ValueError("OI_RU_DEADLINE_RUBBER_REFERENCE_CHANGED")
        if contract == "OI2701" and (
            oil["sources"][plan_id] != plan or tuple(map(Decimal, oil["divider"])) != band
            or oil["observed_lots"] != lots or Decimal(oil["opening_average"]) != average
        ):
            raise ValueError("OI_RU_DEADLINE_OIL_REFERENCE_CHANGED")
        rows = completed(series[1], start, post)
        quote = quotes[NIGHT, contract]
        mark = Decimal(quote["mark"])
        matched = {bar.end for bar in rows if bar.low <= mark <= bar.high}
        if sorted(map(display, matched)) != quote["contains"]:
            raise ValueError("OI_RU_DEADLINE_QUOTE_CHANGED")
        row_matches[contract] = matched
        data[contract] = dict(series=series, minutes=rows, start=start, band=band, role=role, m=m,
                              post_clocks=candidate_clocks(series, start, post, band, role, m),
                              price=dict(tick=tick, lots=lots, totals=displayed_tick_totals(average, lots, tick)))
        results[contract] = dict(plan=plan, band=band, role=role, old_short_retention=prior, new_long_display=long_context,
                                 quote=quote, market=identity, author_vplus_at=None, author_permission=None, author_action_at=None)
    pair_ends = sorted(set.intersection(*row_matches.values()))
    if not pair_ends or photos[NIGHT]["quote_anchor"] is not None:
        raise ValueError("OI_RU_DEADLINE_PAIR_SCOPE_CHANGED")
    return dict(
        version=VERSION, source=photos[NIGHT], earlier_source=photos[CLOSE], cases=results, pair_price_quote_ends=pair_ends,
        comparisons=[evaluate_pair(data, end, include_quote_minute=include) for end in pair_ends for include in (False, True)],
        quote_scope="TWO_ROWS_ONLY_NO_TABLE_CAPTURE_TIME", common_decision_time_verified=False,
        historical_plan_revision_verified=False, references=dict(retention=RETENTION_SHA, oil=OI_SHA, rubber=TOUCH_SHA),
        price_constraints_only=True, author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def quote_combinations(end_sets):
    """Compare row labels without assigning a capture time."""
    count, joint, shortest = 0, 0, None
    for labels in product(*(sorted(ends) for ends in end_sets)):
        spread = max(labels) - min(labels)
        count += 1
        joint += min(labels) == max(labels)
        if shortest is None or (spread, labels) < shortest:
            shortest = (spread, labels)
    return dict(count=count, same_label_count=joint,
                min_spread_minutes=shortest[0] // ONE if shortest is not None else None,
                example_end_labels=shortest[1] if shortest is not None else None)


def strict_row_quote_check(minutes, quote_end, gate, *, tick, lots, totals):
    cut = quote_end - ONE
    prefix = [b for b in minutes if b.end + US < cut]
    audit = gate_check(prefix, gate, tick=tick, lots=lots, totals=totals)
    return audit | dict(candidate_ready_at_boundary=gate < cut)


def three_study(session, market):
    report = verified_json(*COMMON_THREE)
    retention = verified_json(RETENTION, RETENTION_SHA)
    spec = load_specs(verified_json(SPECS, SPECS_SHA))
    photos = retention["snapshot_sources"]
    check_images(photos[CLOSE], photos[NIGHT])
    if report["image"] != photos[NIGHT]["image"] or photos[NIGHT]["quote_anchor"] is not None:
        raise ValueError("OI_RU_DEADLINE_THREE_PHOTO_CHANGED")
    index, quotes = input_sources(), scoped_input_quotes()
    post = datetime.fromisoformat(photos[NIGHT]["published_at"])
    data, local = {}, {}
    for contract, (plan_id, role, band, m) in THREE_CONFIG.items():
        series = read_window(session, market, contract, DAY)
        identity = market_identity(series)
        if identity["1"] != retention["contracts"][contract]["market"][str(DAY)]:
            raise ValueError("OI_RU_DEADLINE_THREE_MARKET_CHANGED")
        plan = load_source(index, plan_id)
        published = datetime.fromisoformat(plan["published_at"]) + ONE
        start = series[1][0].start
        if not published < start < post:
            raise ValueError("OI_RU_DEADLINE_THREE_PLAN_CHANGED")
        previous = retention_row(retention, contract, CLOSE, NIGHT, "short")
        current = retention_row(retention, contract, CLOSE, NIGHT, "long")
        observed = current["later_leg"]
        lots = observed["quantity"]
        tick, average = spec[contract]["tick"], Decimal(observed["opening_average"]).quantize(Decimal("0.1"))
        if (observed["today_quantity"] != lots or previous["retained"] != [lots]
                or previous["later_leg"]["today_quantity"] != 0 or current["earlier_leg"] is not None
                or report["by_contract"][contract]["quantity"] != lots
                or Decimal(report["by_contract"][contract]["shown_average"]) != average):
            raise ValueError("OI_RU_DEADLINE_THREE_LEG_CHANGED")
        minutes = completed(series[1], start, post)
        quote = quotes[NIGHT, contract]
        mark = Decimal(quote["mark"])
        ends = {b.end for b in minutes if b.low <= mark <= b.high}
        if sorted(map(display, ends)) != quote["contains"] or not ends:
            raise ValueError("OI_RU_DEADLINE_THREE_QUOTE_CHANGED")
        clocks = candidate_clocks(series, start, post, band, role, m)
        deferred = None
        if contract == "SH2701":
            protection = ProtectionBandUpdate(contract, plan_id, "PROTECTION", published, published,
                                              plan_id, "SHORT", *band)
            options = published_protection_events(series, (protection,), post)
            delayed = published_protection_events(series, (protection,), post, advance_at_touch=True)
            early = next((row for row in options if row["operation"] == "PROTECT_EARLY"), None)
            first = early["signal"] | {"clock": f"{early['period']}m_to_1m"} if early is not None else None
            if early is not None:
                deferred = next((row["touch_known_at"] for row in delayed if "touch_known_at" in row
                                 and row["signal"] == early["signal"] and row["period"] == early["period"]), None)
        else:
            first = next(iter(clocks["candidates"]), None)
        if first is None or (contract == "SH2701" and deferred is None):
            raise ValueError("OI_RU_DEADLINE_THREE_CANDIDATE_CHANGED")
        period = int(first["clock"].split("m", 1)[0])
        (shape,) = [bar for bar in series[period] if bar.end == first["shape_end"]]
        location = "BELOW" if first["close"] < band[0] else "INSIDE" if first["close"] <= band[1] else "ABOVE"
        data[contract] = dict(minutes=minutes, ends=ends, lots=lots, tick=tick,
                              totals=displayed_tick_totals(average, lots, tick))
        local[contract] = dict(plan=plan, reference_role=role, band=band, first_candidate=first,
                               first_candidate_price_context=dict(
                                   shape_range=[shape.low, shape.high], confirmation_close_location=location,
                                   shape_overlaps_reference=shape.low <= band[1] and band[0] <= shape.high),
                               first_touch=clocks["contact"], first_m_touch=clocks["m_touch"],
                               deferred_advance_known_at=deferred, observed_long=observed, old_short=previous,
                               row_quote=quote, market=identity, author_signal=None, author_permission=None)

    order = tuple(THREE_CONFIG)
    learned = tuple(local[c]["first_candidate"]["available_at"] for c in order)
    caustic_gate = local["SH2701"]["deferred_advance_known_at"]
    oil_gate = local["OI2701"]["first_touch"] + US
    policies = {
        "separate_early_clocks": learned,
        "common_after_all_early_clocks": (max(learned),) * len(order),
        "only_caustic_waits_for_band_contact": (*learned[:-1], caustic_gate),
        "common_after_caustic_band_contact": (caustic_gate,) * len(order),
        "common_after_oil_divider_contact": (oil_gate,) * len(order),
    }
    evaluated, cache = {}, {}
    for name, gates in policies.items():
        rows, matched = {}, []
        for contract, gate in zip(order, gates, strict=True):
            entry = data[contract]
            checks, allowed = {}, set()
            for end in sorted(entry["ends"]):
                ident = contract, end, gate
                if ident not in cache:
                    cache[ident] = strict_row_quote_check(entry["minutes"], end, gate,
                                                         tick=entry["tick"], lots=entry["lots"], totals=entry["totals"])
                checks[end.isoformat()] = cache[ident]
                if cache[ident]["price_compatible"]:
                    allowed.add(end)
            matched.append(allowed)
            rows[contract] = dict(gate=gate, compatible_quote_count=len(allowed), by_quote=checks)
        evaluated[name] = dict(by_contract=rows, price_compatible_quote_combinations=quote_combinations(matched))
    return dict(
        version="lms405-three-contract-protection-deadlines-v1", source=photos[NIGHT], references=dict(
            joint_holdings=COMMON_THREE[1], retention=RETENTION_SHA,
        ), local=local, policies=evaluated, contract_order=order,
        raw_quote_combinations=quote_combinations([data[c]["ends"] for c in order]),
        quote_prices_exclude_quote_minute=True, same_account_as_predecessor_assumed=True,
        each_position_synchronized_with_its_quote_row_assumed=True,
        common_decision_time_verified=False, quote_capture_time_verified=False, historical_revision_verified=False,
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--with-caustic", action="store_true")
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
            run = three_study if args.with_caustic else study
            report = run(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OI_RU_DEADLINE_') and code.isidentifier() else 'OI_RU_DEADLINE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
