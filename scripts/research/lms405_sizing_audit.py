"""Compare LMS 4.0.5 displayed lot sizes using previously archived contract specifications."""

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, BOOK, CONTRACTS
from lms_near405_replay import encoded, sha

SPECS = BOOK.with_name("portfolio-oct-contract-spec-sources.json")
EXPOSURE_SHA256 = "d359577caffa505a9d6c1840680c430cfc4e8fbfd6ad7812d445404ba8ba464a"
HALF_LOT = Decimal("0.5")
AUGUST_IMAGE = Path("02-持仓记录/2026-08-11/0023CoqUgy1ifzqicrvdrj50iq090dkz2.jpg")
AUGUST_IMAGE_SHA256 = "8a4f889d36375fb7830d976615c51cdb41f3633e86aca8d81bda83d5f8ba9d74"
AUGUST_VISIBLE = {"FG2609": 20, "OI2609": 40, "SA2609": 20, "JM2609": 20, "SH2609": 16, "I2609": 16, "RU2609": 20}


def positive_decimal(value):
    number = Decimal(value)
    if not number.is_finite() or number <= 0:
        raise ValueError("POSITIVE_FINITE_VALUE_REQUIRED")
    return number


def load_specs(sources):
    specs = {}
    for archive in sources["archives"]:
        for contract, expected in archive["contracts"].items():
            if contract in specs or contract not in CONTRACTS:
                raise ValueError("SPEC_CONTRACT_SET_MISMATCH")
            path = Path(archive["root"], archive["directory"], f"{contract}-instrument.json")
            raw = path.read_bytes()
            if sha(raw) != expected:
                raise ValueError("SPEC_FILE_HASH_MISMATCH")
            instrument = json.loads(raw)
            if instrument["order_book_id"] != contract:
                raise ValueError("SPEC_CONTRACT_IDENTITY_MISMATCH")
            specs[contract] = dict(
                multiplier=positive_decimal(instrument["contract_multiplier"]),
                tick=positive_decimal(instrument["tick_size"]),
                source_path=str(path), source_sha256=expected, capture_date=archive["capture_date"],
            )
    if specs.keys() != set(CONTRACTS):
        raise ValueError("SPEC_CONTRACT_SET_MISMATCH")
    return specs


def normalized_leg(leg, specification):
    quantity = leg["quantity"]
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("DISPLAYED_QUANTITY_REQUIRED")
    multiplier, tick = specification["multiplier"], specification["tick"]
    opening_average = positive_decimal(leg["opening_average"])
    return dict(
        quantity=quantity, opening_average=opening_average,
        opening_notional_per_lot=opening_average * multiplier, tick_cny_per_lot=tick * multiplier,
        opening_notional=quantity * opening_average * multiplier, tick_cny=quantity * tick * multiplier,
    )


def common_target(contracts, per_lot_field):
    if len(contracts) < 2:
        raise ValueError("TWO_DISPLAYED_CONTRACTS_REQUIRED")
    # If either leg might be the sized leg, use an envelope containing both rounding intervals.
    # An empty intersection rules out a common target even with this extra allowance.
    envelopes = {}
    for contract, legs in sorted(contracts.items()):
        lower = min((leg["quantity"] - HALF_LOT) * leg[per_lot_field] for leg in legs.values())
        upper = max((leg["quantity"] + HALF_LOT) * leg[per_lot_field] for leg in legs.values())
        envelopes[contract] = (lower, upper)
    high_lower = max(envelopes, key=lambda contract: envelopes[contract][0])
    low_upper = min(envelopes, key=lambda contract: envelopes[contract][1])
    lower, upper = envelopes[high_lower][0], envelopes[low_upper][1]
    return dict(
        contract_envelopes=envelopes,
        common_target_possible_with_envelopes=lower <= upper,
        required_minimum=lower, allowed_maximum=upper,
        minimum_contract=high_lower, maximum_contract=low_upper,
    )


def value_range(values):
    return [min(values), max(values)]


def sizing_report(exposure, specs):
    observations, displays = defaultdict(list), []
    for table in exposure["tables"]:
        if table["system"] != "4.0.5" or table["binding"] != "SYSTEM_COVER":
            continue
        contracts = {
            contract: {side: normalized_leg(leg, specs[contract]) for side, leg in item["legs"].items()}
            for contract, item in table["contracts"].items()
        }
        for contract, legs in contracts.items():
            observations[contract].append(legs)
        displays.append(dict(
            source=table["source"], table=table["table"], published_at=table["published_at"],
            source_url=table["source_url"], image=table["image"], contracts=contracts,
            equal_opening_notional=common_target(contracts, "opening_notional_per_lot"),
            equal_cny_per_tick=common_target(contracts, "tick_cny_per_lot"),
        ))

    if not displays:
        raise ValueError("NO_405_COVER_TABLES")
    summary = {}
    for contract in CONTRACTS:
        entries = observations[contract]
        all_legs = [leg for sides in entries for leg in sides.values()]
        quantities = sorted({leg["quantity"] for leg in all_legs})
        summary[contract] = dict(
            tables=len(entries), displayed_quantities=quantities,
            stable_lots_across_visible_tables=len(quantities) == 1 if len(entries) >= 2 else None,
            opening_notional_range=value_range([leg["opening_notional"] for leg in all_legs]) if all_legs else None,
            tick_cny_range=value_range([leg["tick_cny"] for leg in all_legs]) if all_legs else None,
        )
    return dict(
        version="lms405-oct-sizing-audit-v1",
        reference_price_kind="SCREENSHOT_OPENING_AVERAGE",
        contract_spec_scope="RETROSPECTIVE_LOCAL_RQDATA_INSTRUMENT_CAPTURE",
        position_scope="405_COVER_TABLES_VISIBLE_LEGS_ONLY",
        lot_rounding_assumption="NEAREST_WHOLE_LOT_WITH_BOTH_HALF_LOT_ENDPOINTS_ALLOWED",
        contract_specifications=specs, displays=displays, by_contract=summary,
        account_equity=None, account_margin=None, original_sizing_formula=None, executable=False,
    )


def compare_visible_quantities(october, august):
    """Test a common quantity rescale conditional on comparable strategy rows."""
    comparable, absent, lower_limits, upper_limits = {}, [], {}, {}
    for later, observation in october.items():
        earlier = later[:-4] + "2609"
        before = august.get(earlier)
        after = observation["displayed_quantities"]
        if before is None or not after:
            absent.append(later[:-4])
            continue
        # Scale the observed earlier whole lots. Allow a half-lot either way in the later display.
        lower_limits[later] = (max(after) - HALF_LOT) / before
        upper_limits[later] = (min(after) + HALF_LOT) / before
        comparable[later[:-4]] = dict(august_contract=earlier, august_lots=before,
                                     october_contract=later, october_lots=after,
                                     same_lots_observed=all(quantity == before for quantity in after))
    return dict(
        comparable=comparable, no_comparable_august_row=sorted(absent),
        fixed_lots_all_displayed_possible=all(row["same_lots_observed"] for row in comparable.values()) if comparable else None,
        common_quantity_scale_possible=max(lower_limits.values()) <= min(upper_limits.values()) if lower_limits else None,
        lower_scale_by_contract=lower_limits, upper_scale_by_contract=upper_limits,
        account_and_strategy_continuity=None, record_scope="DISPLAYED_SNAPSHOT_QUANTITIES_ONLY",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exposure-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-august-quantities", action="store_true")
    args = parser.parse_args()
    try:
        exposure, spec_sources = args.exposure_audit.read_bytes(), SPECS.read_bytes()
        if sha(exposure) != EXPOSURE_SHA256:
            raise ValueError("EXPOSURE_AUDIT_HASH_MISMATCH")
        report = sizing_report(json.loads(exposure), load_specs(json.loads(spec_sources)))
        report["input_sha256"] = dict(exposure=sha(exposure), spec_sources=sha(spec_sources))
        if args.compare_august_quantities:
            if sha((ARCHIVE.parent / AUGUST_IMAGE).read_bytes()) != AUGUST_IMAGE_SHA256:
                raise ValueError("AUGUST_HOLDING_IMAGE_HASH_MISMATCH")
            report["version"] = "lms405-august-october-visible-sizing-v1"
            report["august_comparison"] = compare_visible_quantities(report["by_contract"], AUGUST_VISIBLE)
            report["august_source"] = dict(source="WRcSq3muJk", image=AUGUST_IMAGE.as_posix(),
                                           sha256=AUGUST_IMAGE_SHA256, row_system=None)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
