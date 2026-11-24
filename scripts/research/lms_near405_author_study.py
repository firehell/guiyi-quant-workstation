"""Replay near405 with a declared region mode and compare separate author labels."""

import argparse
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_author_regions as area_model
from guiyi_quant import lms_near405 as core
from guiyi_quant.lms405 import (
    Action,
    Position,
    Zone,
    apply_action,
    physical_contract,
    timestamp,
)
from guiyi_quant.lms_author_regions import AuthorRegion, RegionInput
from lms_confirmed_replay import read_bars, _csv
from lms_near405_replay import encoded, sha, summarize, validate_provenance


def load_regions(rows):
    return tuple(
        AuthorRegion(
            Zone(
                row["id"],
                row["contract"],
                Decimal(row["lower"]),
                Decimal(row["upper"]),
                datetime.fromisoformat(row["known_at"]),
                row["source"],
                _time(row, "expires_at"),
            ),
            datetime.fromisoformat(row["effective_at"]),
            row["purpose"],
            row["time_basis"],
            Decimal(row["recovery_long"])
            if row.get("recovery_long") is not None
            else None,
            Decimal(row["recovery_short"])
            if row.get("recovery_short") is not None
            else None,
        )
        for row in rows
    )


def _time(row, key):
    value = datetime.fromisoformat(row[key]) if row.get(key) is not None else None
    if value is not None:
        timestamp(value)
    return value


def compare_events(result, labels, *, contract, session_coverage):
    """Score explicitly observed events only. Labels never enter core replay."""
    ids = [label["id"] for label in labels]
    if any(not isinstance(item, str) or not item for item in ids) or len(
        set(ids)
    ) != len(ids):
        raise ValueError("INVALID_OBSERVATION_IDS")
    rows = []
    eligible_windows = []
    for label in labels:
        action = label["action"]
        Action(action, Decimal(1))
        side = label.get("original_side")
        if side is not None and side not in {"LONG", "SHORT"}:
            raise ValueError("INVALID_OBSERVATION_SIDE")
        if not isinstance(label["source"], str) or not label["source"]:
            raise ValueError("OBSERVATION_SOURCE_REQUIRED")
        physical_contract(label["contract"])
        if label["contract"] != contract:
            raise ValueError("OBSERVATION_CONTRACT_BOUNDARY")
        start, end = (_time(label, key) for key in ("earliest_at", "latest_at"))
        if start is not None and end is not None and start > end:
            raise ValueError("OBSERVATION_TIME_REVERSED")
        reasons = list(label.get("evidence_gaps", []))
        if action in {"LOCK", "CLEAR"} and side is None:
            reasons.append("AUTHOR_ORIGINAL_SIDE_UNVERIFIED")
        if not session_coverage:
            reasons.append("VERIFIED_SESSION_COVERAGE_REQUIRED")
        if result["checkpoint"]["mode"] != "HUMAN_CONFIRMATION":
            reasons.append("TEST_FIXTURE_STATE_PATH")
        if label.get("time_basis") != "AUTHOR_EVENT_TIME_OR_OBSERVED_INTERVAL":
            reasons.append("AUTHOR_EVENT_TIME_UNVERIFIED")
        if start is None or end is None:
            reasons.append("AUTHOR_EVENT_INTERVAL_MISSING")
        for field in ("version_405", "five_minute_alignment", "initial_state_aligned"):
            if label.get(field) is not True:
                reasons.append(field.upper() + "_UNVERIFIED")
        row = dict(
            id=label["id"],
            source=label["source"],
            contract=contract,
            expected_action=action,
            expected_original_side=side,
            earliest_at=start,
            latest_at=end,
            status="INDETERMINATE",
            reasons=reasons,
            proposal_ids=[],
        )
        rows.append(row)
        if reasons:
            continue
        evaluations = result["evaluations"]
        if not (
            datetime.fromisoformat(evaluations[0]["available_at"]) <= start
            and end <= datetime.fromisoformat(result["checkpoint"]["as_of"])
            and end
            < datetime.fromisoformat(evaluations[-1]["available_at"])
            + timedelta(minutes=5)
        ):
            reasons.append("OBSERVATION_OUTSIDE_EVALUATION_COVERAGE")
            continue
        observed = [
            e
            for e in evaluations
            if start <= datetime.fromisoformat(e["available_at"]) <= end
        ]
        if not observed or any(
            e["status"] in {"WARMUP", "INDETERMINATE", "RECOVERY_BOUNDARY_UNKNOWN"}
            for e in observed
        ):
            reasons.append("DECISION_WINDOW_NOT_FULLY_EVALUABLE")
            continue
        eligible_windows.append((start, end, row))

    for start, end, row in eligible_windows:
        if any(
            other is not row and start <= upper and lower <= end
            for lower, upper, other in eligible_windows
        ):
            row["reasons"].append("OVERLAPPING_OBSERVATION_WINDOWS")
            continue
        suggestions = [
            p
            for p in result["proposals"]
            if start <= datetime.fromisoformat(p["generated_at"]) <= end
        ]
        row["proposal_ids"] = [p["proposal_id"] for p in suggestions]
        if len(suggestions) > 1:
            row["reasons"].append("MULTIPLE_SUGGESTIONS_IN_INTERVAL")
        elif not suggestions:
            row["status"] = "NO_SUGGESTION"
        elif suggestions[0]["action"] != row["expected_action"]:
            row["status"] = "ACTION_MISMATCH"
        elif (
            row["expected_original_side"]
            and suggestions[0]["plan"]["side"] != row["expected_original_side"]
        ):
            row["status"] = "SIDE_MISMATCH"
        else:
            row["status"] = "ACTION_AND_TIME_MATCH"
    n = sum(row["status"] != "INDETERMINATE" for row in rows)
    matched = sum(row["status"] == "ACTION_AND_TIME_MATCH" for row in rows)
    return dict(
        rows=rows,
        eligible=n,
        matched=matched,
        match_fraction={"numerator": matched, "denominator": n} if n else None,
        false_positive_rate=None,
    )


def run(args):
    document = args.scenario.read_bytes()
    scenario = json.loads(document)
    contract = scenario["contract"]
    physical_contract(contract)
    regions = load_regions(scenario.get("regions", [])) if args.mode == "AUTHOR" else ()
    profile = RegionInput(args.mode, args.recovery, regions)
    bars = read_bars(args.bars, args.input_sha256)
    if any(bar.contract != contract for bar in bars):
        raise ValueError("SCENARIO_CONTRACT_BOUNDARY")
    provenance = args.provenance.read_bytes() if args.provenance else None
    if provenance is not None:
        validate_provenance(bars, args.input_sha256, json.loads(provenance))
    decisions = json.loads(args.decisions.read_bytes()) if args.decisions else []
    checkpoint = json.loads(args.checkpoint.read_bytes()) if args.checkpoint else None
    if not isinstance(decisions, list):
        raise ValueError("DECISION_LIST_REQUIRED")
    as_of = args.as_of or bars[-1].end + timedelta(microseconds=3)
    result = core.replay(
        bars,
        decisions,
        as_of=as_of,
        checkpoint=checkpoint,
        timely_fixture=args.timely_fixture,
        region_input=profile,
    )
    result["summary"] = summarize(result)
    result["comparison"] = compare_events(
        result,
        scenario.get("observations", []),
        contract=contract,
        session_coverage=provenance is not None,
    )
    result["artifact_identity"] = dict(
        input_sha256=args.input_sha256,
        scenario_sha256=sha(document),
        provenance_sha256=sha(provenance) if provenance is not None else None,
        core_sha256=sha(Path(core.__file__).read_bytes()),
        region_core_sha256=sha(Path(area_model.__file__).read_bytes()),
        script_sha256=sha(Path(__file__).read_bytes()),
    )
    return result


def review_archives(evidence, jm_prices, sh_prices):
    """Use frozen price-only results and the separately recomputed conditions."""
    from lms405_public_casebook import report as assess_conditions

    with (evidence / "two-case-timeline-20261028.csv").open(encoding="utf-8") as stream:
        timeline = list(csv.DictReader(stream))
    jm = json.loads(jm_prices.read_bytes())
    sh = json.loads(sh_prices.read_bytes())
    if (
        jm["identity"] != "lms405-jm2609-may-case-v1"
        or jm["mode"] != "RETROSPECTIVE_GEOMETRY_ONLY"
    ):
        raise ValueError("JM_PRICE_REPORT_IDENTITY_MISMATCH")
    if sh["contract"] != "SH2701" or sh["window"] != ["2026-10-26", "2026-10-27"]:
        raise ValueError("SH_PRICE_REPORT_IDENTITY_MISMATCH")
    conditions = assess_conditions(
        evidence / "two-case-condition-casebook-20261028.json"
    )
    sh_low = (
        sh.get("scoped_extrema", {}).get("2026-10-27", {}).get("day", {}).get("low")
    )
    sh_gap = (
        f"Author 1475 vs local day session low {Decimal(sh_low):g}"
        if sh_low is not None and Decimal(sh_low) != Decimal(1475)
        else "Author low comparison unavailable"
        if sh_low is None
        else "Day low matches but does not identify a signal"
    )
    # Explicit unit inputs from the casebook exercise transitions only.
    casebook = json.loads(
        (evidence / "two-case-condition-casebook-20261028.json").read_bytes()
    )
    semantic_rows = []
    for case in casebook["cases"]:
        before = Position(
            case["contract"],
            **{k: Decimal(v) for k, v in case["initial_unit_position"].items()},
        )
        action = Action(case["action"]["kind"], Decimal(case["action"]["quantity"]))
        after = apply_action(before, action)
        semantic_rows.append(
            dict(
                case=case["id"],
                action=action.kind,
                source=case["source"],
                before=dict(long=before.long, short=before.short),
                after=dict(long=after.long, short=after.short),
            )
        )
    return dict(
        study="LMS405_ARCHIVED_CASE_REVIEW",
        action_semantics_only=dict(
            input_kind="UNIT_SCENARIO_WITH_EXPLICIT_ACTION",
            rows=semantic_rows,
            accepted_as_author_prediction=False,
        ),
        scope="DEVELOPMENT_EVIDENCE",
        timeline_rows=len(timeline),
        jm_price_path=jm,
        sh_price_path=sh,
        condition_only=conditions,
        independent_author_comparison=dict(
            eligible=0,
            match_fraction=None,
            false_positive_rate=None,
            cases=[
                dict(
                    case="JM2609_MAY",
                    sources=["G02", "G03", "G04", "G07"],
                    status="INDETERMINATE",
                    region_role="DIVIDE",
                    gaps=[
                        "Historical plan revision, author timeframe and signal Bar",
                        "Action time, matching account, and prior position",
                        "Direction wording conflicts with chart and plan",
                    ],
                ),
                dict(
                    case="SH2701_OCT",
                    sources=["WRouYm67Bc", "WRozPmaK10", "U03"],
                    status="INDETERMINATE",
                    region_role="TARGET",
                    gaps=[
                        "Plan edited; historical contents unproven",
                        "Author timeframe, weak-side rule and signal Bar",
                        "Action time, matching account and prior position",
                        sh_gap,
                    ],
                ),
            ],
        ),
        executable=False,
        fill=None,
        performance=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--mode", choices=("AUTHOR", "INDEPENDENT"), required=True)
    replay.add_argument(
        "--recovery", choices=("KEYBAR", "TWO_CLOSES_BEYOND"), default="KEYBAR"
    )
    replay.add_argument("--input-sha256", required=True)
    replay.add_argument("--as-of", type=datetime.fromisoformat)
    replay.add_argument("--timely-fixture", action="store_true")
    for name in ("bars", "scenario"):
        replay.add_argument("--" + name, type=Path, required=True)
    for name in ("provenance", "decisions", "checkpoint"):
        replay.add_argument("--" + name, type=Path)
    replay.add_argument("--output", type=Path, required=True)
    archive = sub.add_parser("archive-review")
    for name in ("evidence", "jm-prices", "sh-prices", "output"):
        archive.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError("OUTPUT_ALREADY_EXISTS")
        if args.command == "archive-review":
            result = review_archives(args.evidence, args.jm_prices, args.sh_prices)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded(result))
        else:
            result = run(args)
            args.output.mkdir(parents=True, exist_ok=False)
            (args.output / "comparison.csv").write_text(
                _csv(result["comparison"]["rows"]), encoding="utf-8"
            )
            (args.output / "checkpoint.json").write_text(
                encoded(result["checkpoint"]), encoding="utf-8"
            )
            (args.output / "report.json").write_text(encoded(result), encoding="utf-8")
            (args.output / "COMPLETE").write_text(
                sha((args.output / "report.json").read_bytes()) + "\n", encoding="utf-8"
            )
    except FileExistsError:
        parser.error("OUTPUT_ALREADY_EXISTS")
    except (ValueError, TypeError, KeyError, ArithmeticError, OSError):
        parser.error("STUDY_INPUT_OR_REPORT_FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
