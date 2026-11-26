"""Test separate and shared protection clocks for two visible 4.0.5 night legs."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA, check_images, retention_row
from lms405_oi_leg_intent import DISPLAYED_OPENING_AVERAGE
from lms405_oi_ru_next_session import CLOSE, DAY, NIGHT, OI_PLAN, RU_PLAN, market_identity
from lms405_pa_signal_deadline import comparison, minute_ticks, quantity_support, time_constraints
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_replay import input_sources
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
