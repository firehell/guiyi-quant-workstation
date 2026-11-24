"""Compare displayed same-contract legs without inferring account continuity or fills."""

import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from guiyi_quant.lms405 import physical_contract
from lms405_portfolio_replay import ARCHIVE, BOOK, CONTRACTS, visible_legs
from lms_near405_replay import encoded, sha

FIELDS = BOOK.with_name("portfolio-oct-leg-fields.json")
TOTALS = BOOK.with_name("portfolio-oct-table-totals.json")
VERSION = "lms405-oct-exposure-audit-v1"
SIDES = ("long", "short")


def attachment(source, filename, archive):
    paths = source["images"].split(";")
    hashes = source["sha256"].split(";")
    matches = [(p, h) for p, h in zip(paths, hashes, strict=True) if Path(p).name == filename]
    if len(matches) != 1:
        raise ValueError("IMAGE_IDENTITY_MISMATCH")
    relative, expected = matches[0]
    path = (archive / relative).resolve()
    if not path.is_relative_to(archive.resolve()) or sha(path.read_bytes()) != expected:
        raise ValueError("IMAGE_HASH_MISMATCH")
    return dict(path=relative, sha256=expected)


def displayed_contract(sides, fields):
    legs = {}
    if sides.keys() != fields.keys():
        raise ValueError("LEG_FIELDS_DO_NOT_MATCH_QUANTITY_ROWS")
    for side, quantity in sides.items():
        value, today = fields[side]
        average = Decimal(value) if value is not None else None
        if average is not None and (not average.is_finite() or average <= 0):
            raise ValueError("INVALID_OPENING_AVERAGE")
        if today is not None and (type(today) is not int or quantity is None or not 0 <= today <= quantity):
            raise ValueError("INVALID_TODAY_QUANTITY")
        legs[side] = dict(quantity=quantity, opening_average=value, today_quantity=today)

    known = {side: Decimal(leg["quantity"]) for side, leg in legs.items() if leg["quantity"] is not None}
    result = dict(legs=legs, pair=None)
    if len(known) != 2:
        return result
    long, short = (known[side] for side in SIDES)
    older_side = next(
        (side for side, other in (SIDES, SIDES[::-1])
         if legs[side]["today_quantity"] == 0 and legs[other]["today_quantity"] == known[other]),
        None,
    )
    result["pair"] = dict(
        equal=long == short,
        smaller_larger_lots=[str(min(long, short)), str(max(long, short))],
        displayed_net_lots=str(long - short),
        displayed_gross_lots=str(long + short),
        older_side_by_today_field=older_side,
    )
    return result


def compare(earlier, later):
    old_quantity, new_quantity = earlier["quantity"], later["quantity"]
    old_average, new_average = earlier["opening_average"], later["opening_average"]
    old_today, new_today = earlier["today_quantity"], later["today_quantity"]
    quantity_equal = old_quantity == new_quantity if None not in (old_quantity, new_quantity) else None
    average_equal = Decimal(old_average) == Decimal(new_average) if None not in (old_average, new_average) else None
    today_equal = old_today == new_today if None not in (old_today, new_today) else None
    if quantity_equal is False or average_equal is False:
        result = "QUANTITY_OR_OPENING_AVERAGE_CHANGED"
    elif quantity_equal is True and average_equal is True:
        result = "SAME_QUANTITY_AND_OPENING_AVERAGE"
    else:
        result = "INSUFFICIENT_FIELDS"
    return dict(
        result=result, quantity_equal=quantity_equal,
        opening_average_equal=average_equal, today_quantity_equal=today_equal,
    )


def audit(book, supplement, sources, archive):
    baseline = {(row["source"], row["table"]): row for row in book["snapshots"]}
    if len(baseline) != len(book["snapshots"]):
        raise ValueError("DUPLICATE_BASELINE_TABLE")
    eligible = {key for key, row in baseline.items() if row["system"] != "5.0"}
    excluded = {key for key, row in baseline.items() if row["system"] == "5.0"}
    seen, tables = set(), []
    for row in supplement["tables"]:
        key = (row["source"], row["table"])
        if key in seen or key in excluded:
            raise ValueError("DUPLICATE_OR_EXCLUDED_TABLE")
        seen.add(key)
        base = baseline.get(key)
        if base:
            if "additional_quantities" in row or "binding" in row:
                raise ValueError("BASELINE_OVERRIDE")
            sides, system, binding = base["legs"], base["system"], base["binding"]
        else:
            sides, system, binding = row["additional_quantities"], "4.0.5", row["binding"]
            if binding != "SYSTEM_POST_MIXED_ROWS":
                raise ValueError("ADDITIONAL_TABLE_MUST_KEEP_MIXED_ROW_SCOPE")
        visible_legs(sides)  # Apply the existing physical-contract and quantity contract.
        if sides.keys() != row["fields"].keys():
            raise ValueError("CONTRACTS_DO_NOT_MATCH_QUANTITY_ROWS")
        source = sources[row["source"]]
        image = attachment(source, row["image"], archive)
        if not (archive / source["path"]).is_file():
            raise ValueError("SOURCE_TRANSCRIPTION_MISSING")
        tables.append(dict(
            source=row["source"], table=row["table"], system=system, binding=binding,
            published_at=source["published_at"], edited=source["edited"], source_url=source["url"],
            archive_path=source["path"], image=image, quote_anchor=base.get("quote_anchor") if base else None,
            contracts={symbol: displayed_contract(legs, row["fields"][symbol]) for symbol, legs in sides.items()},
        ))
    if eligible - seen:
        raise ValueError("BASELINE_TABLE_MISSING")
    tables.sort(key=lambda t: (datetime.fromisoformat(t["published_at"]), t["source"], t["table"]))

    previous, comparisons, pairs = {}, [], []
    for index, table in enumerate(tables):
        identity = dict(source=table["source"], table=table["table"], binding=table["binding"])
        for contract, observation in sorted(table["contracts"].items()):
            if observation["pair"] is not None:
                pairs.append(identity | dict(contract=contract) | observation["pair"])
            for side, leg in sorted(observation["legs"].items()):
                key = (contract, side)
                if key in previous:
                    previous_index, previous_identity, previous_leg = previous[key]
                    comparisons.append(dict(
                        contract=contract, side=side,
                        earlier=previous_identity | previous_leg, later=identity | leg,
                        intervening_tables_without_leg=index - previous_index - 1,
                    ) | compare(previous_leg, leg))
                previous[key] = (index, identity, leg)

    groups = Counter((p["binding"], p["equal"]) for p in pairs)
    return dict(
        version=VERSION, chronology="PUBLICATION_ORDER", tables=tables, pairs=pairs,
        pair_counts_by_binding={
            binding: dict(equal=groups[binding, True], unequal=groups[binding, False])
            for binding in sorted({p["binding"] for p in pairs})
        },
        comparisons=comparisons,
        comparison_counts=dict(sorted(Counter(c["result"] for c in comparisons).items())),
        only_today_quantity_changed=sum(
            c["result"] == "SAME_QUANTITY_AND_OPENING_AVERAGE" and c["today_quantity_equal"] is False
            for c in comparisons
        ),
        excluded_5_0_tables=[dict(source=source, table=table) for source, table in sorted(excluded)],
        account_continuity=None, action_at=None, author_action_matches=None,
        admitted_author_action_samples=0, executable=False, fills=None, pnl=None,
    )


def reconcile_display(table, totals):
    quantities = {
        contract: {side: leg["quantity"] for side, leg in observation["legs"].items()}
        for contract, observation in table["contracts"].items()
    }
    if set(totals["other_legs"]) & set(CONTRACTS):
        raise ValueError("SUPPLEMENT_CONTAINS_STUDY_CONTRACT")
    quantities.update(totals["other_legs"])
    if not quantities:
        raise ValueError("EMPTY_DISPLAY")
    for contract, legs in quantities.items():
        physical_contract(contract)
        if not legs or set(legs) - set(SIDES) or any(type(q) is not int or q <= 0 for q in legs.values()):
            raise ValueError("DISPLAY_INCOMPLETE_OR_QUANTITY_INVALID")
    row_count = sum(map(len, quantities.values()))
    lot_sum = sum(Decimal(lots) for legs in quantities.values() for lots in legs.values())
    if row_count != totals["row_count"] or lot_sum != totals["total_lots"]:
        raise ValueError("DISPLAY_TOTALS_MISMATCH")

    partitions = dict(equal_pairs=[], unequal_pairs=[], single_visible_side=[])
    for contract, legs in sorted(quantities.items()):
        if len(legs) == 1:
            partitions["single_visible_side"].append(contract)
        elif legs["long"] == legs["short"]:
            partitions["equal_pairs"].append(contract)
        else:
            partitions["unequal_pairs"].append(contract)
    return dict(
        **{key: table[key] for key in ("source", "table", "published_at", "system", "binding", "image", "source_url")},
        displayed_row_count=row_count, displayed_lot_sum_for_reconciliation=str(lot_sum),
        visible_contract_count=len(quantities),
        unseen_study_contracts=sorted(set(CONTRACTS) - quantities.keys()),
        all_visible_contracts_equal_paired=len(partitions["equal_pairs"]) == len(quantities),
        **partitions,
    )


def portfolio_scope(audit_report, supplements):
    indexed = {(row["source"], row["table"]): row for row in supplements}
    expected = {(row["source"], row["table"]) for row in audit_report["tables"]}
    if len(indexed) != len(supplements) or expected != indexed.keys():
        raise ValueError("DISPLAY_TABLE_SET_MISMATCH")
    rows = [reconcile_display(table, indexed[table["source"], table["table"]]) for table in audit_report["tables"]]
    covers = [row for row in rows if row["system"] == "4.0.5" and row["binding"] == "SYSTEM_COVER"]
    return dict(
        version="lms405-oct-table-scope-v1",
        observation_scope="RECONCILED_SCREENSHOT_ROWS_ONLY",
        tables=rows,
        cover_tables_with_all_visible_contracts_equal_paired=[
            row["source"] for row in covers if row["all_visible_contracts_equal_paired"]
        ],
        cover_tables_with_equal_pairs_and_single_visible_sides=[
            row["source"] for row in covers if row["equal_pairs"] and row["single_visible_side"]
        ],
        cover_tables_without_visible_equal_pairs=[row["source"] for row in covers if not row["equal_pairs"]],
        excluded_5_0_tables=audit_report["excluded_5_0_tables"],
        account_whole_portfolio_exposure=None,
        portfolio_risk_budget=None,
        account_continuity=None,
        author_action_matches=None,
        admitted_author_action_samples=0,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--portfolio-scope", action="store_true", help="Reconcile full displayed table totals.")
    args = parser.parse_args()
    try:
        raw_book, raw_fields = BOOK.read_bytes(), FIELDS.read_bytes()
        with ARCHIVE.open(newline="", encoding="utf-8") as stream:
            sources = {row["source_id"]: row for row in csv.DictReader(stream)}
        report = audit(json.loads(raw_book), json.loads(raw_fields), sources, ARCHIVE.parent)
        input_hashes = dict(quantities=sha(raw_book), leg_fields=sha(raw_fields))
        if args.portfolio_scope:
            raw_totals = TOTALS.read_bytes()
            report = portfolio_scope(report, json.loads(raw_totals))
            input_hashes["display_totals"] = sha(raw_totals)
        report["input_sha256"] = input_hashes
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
