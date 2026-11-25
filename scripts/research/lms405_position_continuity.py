"""Compare position lifecycle explanations against the same nine-product snapshots."""

import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_replay import read_session_series
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_snapshot_comparison import ONE, SIDES
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

EXPOSURE = Path("output/lms405-exposure-20261125/exposure-audit.json")
SNAPSHOTS = Path("output/lms405-sized-portfolio-20261125/visible-snapshot-comparison.json")
PVC = Path("output/lms405-v-exit-20261125/verified.json")
INPUTS = {
    EXPOSURE: EXPOSURE_SHA256,
    SNAPSHOTS: "1075e7bfedb49307b28ef0ae7139f9d355f025e831e7c235c336f7caf093310a",
    PVC: "b6082e514c80036c0907d39bb2690f6c9416ba1e852beab2a7ad087f64939e58",
}
# For non-anchored tables, the trading day is a conditional placement of the
# image in the session named by the post. This does not date any action.
TRADING_DAYS = {
    source: date(2026, 10, day) for source, day in (
        ("WRnTlEfj1t", 23), ("WRnY5bznUE", 23), ("WRo00BFM1E", 23),
        ("WRo2KQ43iX", 26), ("WRov1j6e10", 27), ("WRozNbg3en", 27),
        ("WRoAkcEppg", 27), ("U03", 27), ("WRoEvasxQR", 28),
    )
}
UNKNOWN = "UNRESOLVED"
ALLOWED = "COMPATIBLE"
EXCLUDED = "INCOMPATIBLE"


def continuity(earlier, later, *, same_day, at_prior_session_close=False, minimum_price_replacements=0):
    """Bounds for earlier displayed lots surviving in the later side of the same account."""
    earlier_quantity, later_quantity = (leg.get("quantity") for leg in (earlier, later))
    if earlier_quantity is None or later_quantity is None:
        return dict(bounds=None, unchanged=UNKNOWN, full_replacement=UNKNOWN)

    before_today, after_today = (leg.get("today_quantity") for leg in (earlier, later))
    lower = 0
    upper = min(earlier_quantity, later_quantity)
    if same_day and after_today is not None:
        lower = later_quantity - after_today
        if before_today is not None:
            upper = min(earlier_quantity - before_today, lower) + min(before_today, after_today)
            if lower > earlier_quantity - before_today:
                # An older lot cannot be newly opened within the same trading day.
                upper = -1
    elif not same_day and after_today is not None:
        later_older = later_quantity - after_today
        upper = min(upper, later_older)
        if at_prior_session_close:
            # No prior-day order can open after its last quote and the next day's
            # new orders are today's positions, so all remaining older lots survived.
            lower = later_older

    first_price, second_price = (leg.get("opening_average") for leg in (earlier, later))
    same_average = None if None in (first_price, second_price) else Decimal(first_price) == Decimal(second_price)
    if earlier_quantity == later_quantity and same_average is False:
        upper = min(upper, earlier_quantity - 1)
    upper = min(upper, earlier_quantity - minimum_price_replacements)

    unchanged, full_replacement = EXCLUDED, EXCLUDED
    bounds = None
    if lower <= upper:
        bounds = [lower, upper]
        if earlier_quantity == later_quantity == upper:
            unchanged = ALLOWED if same_average is True else UNKNOWN
        full_replacement = ALLOWED if lower == 0 else EXCLUDED
    return dict(
        bounds=bounds, unchanged=unchanged, full_replacement=full_replacement,
        inconsistent_same_scope=lower > upper,
        minimum_new_lots=None if bounds is None else later_quantity - upper,
        minimum_removed_earlier_lots=None if bounds is None else earlier_quantity - upper,
        price_envelope_minimum_removed=minimum_price_replacements or None,
    )


def protect_only(original_side, long_short, later_legs):
    if original_side is None:
        return UNKNOWN
    protection_side = next(side for side in SIDES if side != original_side)
    if (long_short[original_side]["unchanged"] == EXCLUDED
            or later_legs.get(protection_side, {}).get("quantity") is not None):
        return EXCLUDED
    # Observing the original leg without its opposite does not show zero opposite lots.
    return UNKNOWN


def snapshot_sources(exposure, anchors):
    verified = {row["source"]: row for row in anchors["snapshots"]}
    result = {}
    for table in exposure["tables"]:
        source = table["source"]
        if source in result or source not in TRADING_DAYS:
            raise ValueError("CONTINUITY_TABLE_SET_CHANGED")
        image = table["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("CONTINUITY_ATTACHMENT_CHANGED")
        anchor = table["quote_anchor"]
        if anchor is not None:
            row = verified[source]
            if (
                anchor != row["quote_anchor"]
                or datetime.fromisoformat(anchor).date() != TRADING_DAYS[source]
                or any(
                    quote["quote_aligned"] is not True
                    or quote["author_visible_legs"] != table["contracts"][contract]["legs"]
                    for contract, quote in row["contracts"].items()
                )
            ):
                raise ValueError("CONTINUITY_ANCHOR_CHANGED")
        result[source] = table | {
            "trading_day": TRADING_DAYS[source],
            "timing_scope": "ALIGNED_QUOTE" if anchor else "CONDITIONAL_POST_SESSION",
        }
    if result.keys() != TRADING_DAYS.keys() or verified.keys() != {
        source for source, table in result.items() if table["quote_anchor"]
    }:
        raise ValueError("CONTINUITY_COVERAGE_CHANGED")
    return result


def pvc_constraint(pvc, tables):
    before, after = (pvc["observations"][key] for key in ("first_night", "lunch"))
    for row in (before, after):
        leg = tables[row["source"]]["contracts"]["V2701"]["legs"]["long"]
        if (row["total"] != leg["quantity"] or row["today"] != leg["today_quantity"]
                or Decimal(row["opening_average"]) != Decimal(leg["opening_average"])):
            raise ValueError("PVC_PRICE_BOUND_LEG_CHANGED")
    price_bound = pvc["conditional_lot_analysis"]["aggregate_price_envelopes"]["minimum_replaced_lots"]
    if type(price_bound) is not int or not 0 < price_bound <= before["total"]:
        raise ValueError("PVC_PRICE_BOUND_INVALID")
    return (before["source"], after["source"], "V2701", "long"), price_bound


def contract_histories(tables):
    return {contract: [table for table in tables.values() if contract in table["contracts"]]
            for contract in CONTRACTS}


def session_close_facts(session, market, anchors, tables):
    facts = {}
    for contract, history in contract_histories(tables).items():
        for before, after in zip(history, history[1:]):
            days = (before["trading_day"], after["trading_day"])
            if days[0] == days[1] or not before["quote_anchor"]:
                continue
            anchor = datetime.fromisoformat(before["quote_anchor"])
            # Limit this test to the two selected close-to-next-trading-day boundaries.
            if anchor.hour != 15 or anchor.minute != 0 or days not in (
                (date(2026, 10, 23), date(2026, 10, 26)),
                (date(2026, 10, 27), date(2026, 10, 28)),
            ):
                continue
            bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, days)
            first_day = [bar for bar in bars if bar.trading_day == days[0]]
            second_day = [bar for bar in bars if bar.trading_day == days[1]]
            readback = {"count": len(first_day), "sha256": bars_sha(first_day)}
            if readback != anchors["market_1m"][f"{contract}:{days[0].isoformat()}"]:
                raise ValueError("CONTINUITY_ANCHOR_MARKET_CHANGED")
            next_start = second_day[0].bar_end - ONE
            if first_day[-1].bar_end != anchor or next_start <= anchor:
                raise ValueError("CONTINUITY_SESSION_BOUNDARY_UNVERIFIED")
            later_post = datetime.fromisoformat(after["published_at"])
            if not next_start < later_post <= second_day[-1].bar_end:
                raise ValueError("CONTINUITY_LATER_POST_OUTSIDE_NEXT_TRADING_DAY")
            facts[(before["source"], after["source"], contract)] = dict(
                last_end=anchor, next_start=next_start,
                earlier_day=readback, later_day=dict(count=len(second_day), sha256=bars_sha(second_day)),
            )
    return facts


def study(tables, anchors, pvc, session_facts):
    pvc_key, price_bound = pvc_constraint(pvc, tables)
    products = {}
    for contract, history in contract_histories(tables).items():
        transitions = []
        for before, after in zip(history, history[1:]):
            prior, current = (table["contracts"][contract] for table in (before, after))
            earlier_source, later_source = before["source"], after["source"]
            if (
                datetime.fromisoformat(before["published_at"]) >= datetime.fromisoformat(after["published_at"])
                or before["trading_day"] > after["trading_day"]
            ):
                raise ValueError("CONTINUITY_TIME_REVERSED")
            earlier_legs, later_legs = prior["legs"], current["legs"]
            same_day = before["trading_day"] == after["trading_day"]
            verified_close = session_facts.get((earlier_source, later_source, contract))
            orientations = {
                side: continuity(
                    earlier_legs.get(side, {}), later_legs.get(side, {}), same_day=same_day,
                    at_prior_session_close=verified_close is not None,
                    minimum_price_replacements=price_bound if
                    (earlier_source, later_source, contract, side) == pvc_key else 0,
                )
                for side in SIDES
            }
            original = (prior.get("pair") or {}).get("older_side_by_today_field")
            observed_positive = any(leg.get("quantity") is not None for leg in later_legs.values())
            transitions.append(dict(
                earlier=earlier_source, later=later_source, same_trading_day=same_day,
                verified_session_boundary=verified_close,
                earlier_legs=earlier_legs, later_legs=later_legs, sides=orientations,
                earlier_older_side_hypothesis=original,
                only_remove_protection=protect_only(original, orientations, later_legs),
                endpoint_flat=EXCLUDED if observed_positive else UNKNOWN,
            ))
        repeated = [v for row in transitions for v in row["sides"].values() if v["bounds"] is not None]
        products[contract] = dict(
            visible_tables=len(history), transitions=transitions,
            minimum_prior_removal_positive=sum(v["minimum_removed_earlier_lots"] > 0 for v in repeated),
            pure_full_replacement_excluded=sum(v["full_replacement"] == EXCLUDED for v in repeated),
            snapshot_paths_compared=len(repeated),
        )
    baseline = Counter(
        row["variants"]["BASELINE"]["before_quote_close"]["classification"]
        for snapshot in anchors["snapshots"] for row in snapshot["contracts"].values()
    )
    return dict(
        version="lms405-position-continuity-study-v1", contracts=products,
        sources={key: {field: row[field] for field in
                      ("source_url", "published_at", "archive_path", "image", "quote_anchor",
                       "trading_day", "timing_scope", "binding")} for key, row in tables.items()},
        frozen_flat_start_baseline=dict(sorted(baseline.items())),
        identity_scope="CONDITIONAL_SAME_ACCOUNT_AND_DISPLAY_OPENING_BASIS",
        chronology="PUBLICATION_ORDER; QUOTE_ANCHORS_SEPARATE",
        account_continuity=None, author_action_matches=None, admitted_author_action_samples=0,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("CONTINUITY_ENV_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        documents = {}
        for path, expected in INPUTS.items():
            payload = path.read_bytes()
            if sha(payload) != expected:
                raise ValueError("CONTINUITY_REFERENCE_CHANGED")
            documents[path] = json.loads(payload)
        anchors = documents[SNAPSHOTS]
        tables = snapshot_sources(documents[EXPOSURE], anchors)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            boundaries = session_close_facts(session, build_market_data_service(session), anchors, tables)
        results = study(tables, anchors, documents[PVC], boundaries)
        results["input_sha256"] = {str(path): digest for path, digest in INPUTS.items()}
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(results))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "CONTINUITY_SOURCE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
