"""Reproduce unresolved public case conditions; never supplies author signals."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.public_conditions import Condition, PublicCase, assess_case


def report(path: Path) -> dict:
    raw = path.read_bytes()
    book = json.loads(raw)
    if book["schema_version"] != "lms405-public-casebook-v0.1":
        raise ValueError("UNKNOWN_CASEBOOK_SCHEMA")
    if book["historical_immutability_verified"] is not False:
        raise ValueError("HISTORICAL_PROOF_NOT_SUPPORTED_BY_THIS_STUDY")
    at = datetime.fromisoformat(book["recorded_at"]) + timedelta(seconds=1)
    results = []
    seen = set()
    for row in book["cases"]:
        if row["id"] in seen:
            raise ValueError("DUPLICATE_CASE")
        seen.add(row["id"])
        case = PublicCase(
            row["id"],
            row["contract"],
            row["source"],
            datetime.fromisoformat(row["available_at"]),
            row["version_405"],
            tuple(row["actions"]),
            tuple(tuple(r) for r in row["alternatives"]),
            tuple(tuple(r) for r in row["precedence"]),
        )
        names = set().union(*map(set, case.alternatives))
        if names != set(row["condition_meaning"]):
            raise ValueError("CONDITION_DEFINITION_MISMATCH")
        position = Position(
            row["contract"],
            **{k: Decimal(v) for k, v in row["initial_unit_position"].items()},
        )
        action = Action(row["action"]["kind"], Decimal(row["action"]["quantity"]))
        facts = []
        for item in row.get("disclosed_conditions", []):
            if item["time_kind"] != "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME":
                raise ValueError("AUTHOR_BAR_TIME_NOT_IDENTIFIED")
            facts.append(
                Condition(
                    item["name"],
                    case.id,
                    case.contract,
                    item["value"],
                    datetime.fromisoformat(item["observed_at"]),
                    datetime.fromisoformat(item["known_at"]),
                    item["source"],
                    item["time_kind"],
                )
            )
        result = assess_case(case, position, action, tuple(facts), as_of=at)
        results.append(
            dict(
                case_id=case.id,
                source=case.source,
                state_kind="UNIT_SCENARIO_NOT_OBSERVED_AUTHOR_POSITION",
                condition_facts_supplied=len(facts),
                missing_original_facts=row["missing"],
                assessment=result,
            )
        )
    return dict(
        study="LMS405_PUBLIC_CONDITIONS_V0_1",
        casebook_sha256=hashlib.sha256(raw).hexdigest(),
        input_kind="SOURCE_CONDITIONS_WITHOUT_MARKET_SIGNAL_LABELS",
        historical_immutability_verified=False,
        author_signal_success_rate=None,
        eligible_golden_signal_samples=0,
        holdout_samples=0,
        executable=False,
        fill=None,
        performance=None,
        cases=results,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = report(args.casebook)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
