"""Compare empty, old-short and locked starting states under one near-LMS replay policy."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms_near405 import CarryInSeed, replay
from lms405_carry_in_study import CONTRACTS, SNAPSHOT_SHA256
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, DAYS
from lms405_sizing_audit import EXPOSURE_SHA256, positive_decimal
from lms405_snapshot_comparison import ONE, visible_leg_checks
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

EXPOSURE = Path("output/lms405-exposure-20261125/exposure-audit.json")
SNAPSHOTS = Path("output/lms405-sized-portfolio-20261125/visible-snapshot-comparison.json")
PREVIOUS = Path("output/lms405-sized-portfolio-20261125/short-carry-in.json")
PROXY_REPLAY = Path("output/lms405-same-rules-carry-in-20261125/report.json")
PROXY_REPLAY_SHA256 = "789fee826e390bd3907d37834beca19de9da9d278c0db10c793550916313dd1c"
INPUTS = {
    EXPOSURE: EXPOSURE_SHA256,
    SNAPSHOTS: SNAPSHOT_SHA256,
    PREVIOUS: "1cd609a652d5ffacc21f1c1a91e2ff71bc4be183b60327d9a0253202458c95e1",
}
SCENARIOS = {"FLAT": (None, False), "OLD_SHORT_ONLY": ("SHORT", False), "OBSERVED_LOCK": ("SHORT", True)}


def projection(result, visible, lots):
    initial = result["checkpoint"]["initial_state"]
    state = result["current_state"]
    scaled = {side: str(Decimal(state[side]) * lots) for side in ("long", "short")}
    same_cycle = initial["cycle_id"] is not None and state["cycle_id"] == initial["cycle_id"]
    return dict(
        projected_lots=scaled, compared=visible_leg_checks(visible, scaled),
        initial_cycle_retained=same_cycle if initial["cycle_id"] else None,
        last_event=result["transitions"][-1] if result["transitions"] else None,
    )


def transition_behavior(rows):
    return [
        (row["action"], row["reason"], row["known_at"], row["after"]["long"], row["after"]["short"])
        for row in rows
    ]


def run_case(contract, bars, visible_seed, available, quote_rows, source, *, separate_exit=False):
    lots = positive_decimal(visible_seed["short"]["quantity"])
    if (visible_seed["short"]["today_quantity"] != 0
            or visible_seed["long"]["today_quantity"] != visible_seed["long"]["quantity"]
            or lots != positive_decimal(visible_seed["long"]["quantity"])):
        raise ValueError("UNVERIFIED_OLD_SHORT_AND_LOCKED_LEG")
    anchors, scenarios = {}, {}
    for snapshot in quote_rows:
        anchor = datetime.fromisoformat(snapshot["quote_anchor"])
        row = snapshot["contracts"][contract]
        if not available < anchor or row["quote_aligned"] is not True:
            raise ValueError("UNVERIFIED_REPLAY_ANCHOR")
        anchors[anchor] = dict(
            source=snapshot["source"], observed_at=anchor, visible_legs=row["author_visible_legs"],
            previous_full_window_flat=row["variants"]["BASELINE"]["before_quote_close"], scenarios={},
        )

    exit_policy = {"carry_exit_evidence": ()} if separate_exit else {}
    for name, (direction, locked) in SCENARIOS.items():
        seed = CarryInSeed(contract, available, direction, locked, source)
        initial = replay(bars, as_of=available, timely_fixture=True, carry_in=seed, **exit_policy)["checkpoint"]
        checkpoint = initial
        for anchor, row in anchors.items():
            direct = replay(bars, as_of=anchor, timely_fixture=True, carry_in=seed, **exit_policy)
            result = replay(bars, as_of=anchor, timely_fixture=True, carry_in=seed,
                            checkpoint=json.loads(encoded(checkpoint)), **exit_policy)
            if result != direct:
                raise ValueError("CARRY_IN_CHECKPOINT_MISMATCH")
            checkpoint = result["checkpoint"]
            row["scenarios"][name] = projection(result, row["visible_legs"], lots)

        last_anchor = max(anchors)
        human = replay(bars, as_of=last_anchor, carry_in=seed, **exit_policy)
        if human["transitions"] or human["checkpoint"]["initial_state"] != human["current_state"]:
            raise ValueError("CARRY_IN_WITHOUT_HUMAN_ACCEPTANCE_CHANGED")
        crossings = result["transitions"]
        initial_cycle = initial["initial_state"]["cycle_id"]
        initial_exit = next((item for item in crossings if item["action"] == "CLEAR"
                             and item["before"]["cycle_id"] == initial_cycle), None)
        reasons = {p["proposal_id"]: p for p in result["proposals"]}
        exit_bar = None
        if initial_exit:
            bar = bars[reasons[initial_exit["proposal_id"]]["index"]]
            exit_bar = dict(end=bar.end, close=bar.close)
        scenarios[name] = dict(
            initial_state=initial["initial_state"], first_seeded_cycle_exit=initial_exit, first_exit_bar=exit_bar,
            version=result["version"], rule_hash=result["rule_hash"], all_fixture_transitions=crossings,
            human_proposals_without_confirmation=len(human["proposals"]),
            human_transitions_without_confirmation=0,
        )
        if separate_exit:
            unresolved = [row for row in result["evaluations"] if row.get("carry_exit_status") == "UNKNOWN"]
            first_proxy = next((row for row in unresolved if row["carry_exit_proxy_reason"]), None)
            scenarios[name].update(
                unresolved_seeded_exit_bars=len(unresolved),
                first_ignored_proxy_exit=(
                    dict(bar_end=first_proxy["bar_end"], reason=first_proxy["carry_exit_proxy_reason"])
                    if first_proxy else None
                ),
            )
    if len({item["rule_hash"] for item in scenarios.values()}) != 1:
        raise ValueError("CARRY_IN_SCENARIO_RULES_CHANGED")
    return dict(
        source_opening_averages={side: leg["opening_average"] for side, leg in visible_seed.items()},
        lots_per_unit=lots, scenarios=scenarios, anchors=list(anchors.values()),
    )


def compute(session, market, exposure, snapshots, previous, *, proxy_replay=None):
    (first,) = [row for row in exposure["tables"] if row["source"] == snapshots["first_night_source"]]
    if first["system"] != "4.0.5" or first["binding"] != "SYSTEM_COVER":
        raise ValueError("EXPECTED_405_COVER")
    if sha((ARCHIVE.parent / first["image"]["path"]).read_bytes()) != first["image"]["sha256"]:
        raise ValueError("FIRST_NIGHT_IMAGE_CHANGED")
    known = datetime.fromisoformat(first["published_at"]) + ONE
    if known != datetime.fromisoformat(previous["seed_available_at"]):
        raise ValueError("CARRY_IN_AVAILABLE_TIME_CHANGED")
    coverage, cases = {}, {}
    for contract in CONTRACTS:
        raw, series = read_pair(session, market, contract, DAYS[:3])
        coverage[contract] = {f"{n}m": {"count": len(rows), "sha256": bars_sha(rows)} for n, rows in raw.items()}
        if coverage[contract] != previous["market"][contract]:
            raise ValueError("CARRY_IN_MARKET_PREFIX_CHANGED")
        quotes = {b.end: b.close for b in series[1]}
        for s in snapshots["snapshots"]:
            if quotes.get(datetime.fromisoformat(s["quote_anchor"])) != Decimal(s["contracts"][contract]["mds_close"]):
                raise ValueError("CARRY_IN_QUOTE_ANCHOR_CHANGED")
        cases[contract] = run_case(contract, series[5], first["contracts"][contract]["legs"],
                                   known, snapshots["snapshots"], first["source"],
                                   separate_exit=proxy_replay is not None)
    report = dict(
        version="lms405-same-rules-carry-in-study-v1", source=first["source"], image=first["image"],
        source_published_at=first["published_at"], seed_known_at=known, cases=cases, market=coverage,
        initial_direction_hypothesis="SHORT", original_author_plan=None, author_open_at=None,
        account_continuity=None, admitted_author_action_samples=0, author_matches=None, executable=False,
        fills=None, pnl=None,
    )
    if proxy_replay is not None:
        if (proxy_replay["market"] != coverage
                or datetime.fromisoformat(proxy_replay["seed_known_at"]) != known):
            raise ValueError("PROXY_REPLAY_INPUTS_CHANGED")
        report.update(version="lms405-carry-in-explicit-exit-study-v1", admitted_exit_evidence=0)
        for contract, case in cases.items():
            old_case = proxy_replay["cases"][contract]
            new_flat = case["scenarios"]["FLAT"]["all_fixture_transitions"]
            old_flat = old_case["scenarios"]["FLAT"]["all_fixture_transitions"]
            if transition_behavior(new_flat) != transition_behavior(old_flat):
                raise ValueError("EXPLICIT_EXIT_CHANGED_FLAT_CONTROL")
            for row, old in zip(case["anchors"], old_case["anchors"], strict=True):
                if (row["observed_at"], row["source"]) != (datetime.fromisoformat(old["observed_at"]), old["source"]):
                    raise ValueError("PROXY_REPLAY_ANCHOR_CHANGED")
                if row["scenarios"]["FLAT"]["projected_lots"] != old["scenarios"]["FLAT"]["projected_lots"]:
                    raise ValueError("EXPLICIT_EXIT_CHANGED_FLAT_CONTROL")
                row["proxy_exit_scenarios"] = old["scenarios"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--separate-carry-exit", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("CARRY_IN_ENV_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        inputs = INPUTS | ({PROXY_REPLAY: PROXY_REPLAY_SHA256} if args.separate_carry_exit else {})
        documents = {}
        for path, digest in inputs.items():
            payload = path.read_bytes()
            if sha(payload) != digest:
                raise ValueError("CARRY_IN_REFERENCE_CHANGED")
            documents[path] = json.loads(payload)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = compute(session, build_market_data_service(session),
                             documents[EXPOSURE], documents[SNAPSHOTS], documents[PREVIOUS],
                             proxy_replay=documents.get(PROXY_REPLAY))
        result["input_sha256"] = {str(path): digest for path, digest in inputs.items()}
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError):
        parser.exit(2, "CARRY_IN_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
