"""Apply one attributed-position policy to archived nine-contract research episodes."""

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as near
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, VERSION, Book, Intent, assess
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_leg_audit import study as audit_legs
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded

TIMELINE = (Path("output/lms405-portfolio-role-replay-20261126/reviewed-a.json"),
            "da5be560603b94445b642043d345c5a34c076292dc400a096a1fc89a6612093f")
AUDIT = (Path("output/lms405-portfolio-leg-audit-20261125/verified.json"),
         "93ddfe102a19d99cb5ec939b85f0dba82f7035b34a15d985a6564e1e070cb1cc")
VARIANT = "scoped_without_external_conditions"
UNIT = Decimal(1)
EARLY_PROTECTION_CASES = {"FG2701:EARLY", "SA:EARLY_PROTECTION_FIXTURE", "SH:PROTECT_NEW"}


def local_clock(value):
    return datetime.fromisoformat(value)


def project_fixture(book, operation, quantity, clock, *, plan):
    request = Intent(book, operation, quantity, plan, clock + ONE)
    facts = tuple(Condition(name, request.scope, book.contract, True, clock - 2 * US, clock - US,
                            f"TEST_FIXTURE:{plan}", "EVENT_TIME") for name in REQUIRED[operation])
    approval = HandoffConfirmation(request.confirmation_scope(facts), f"TEST_FIXTURE:{request.scope}",
                                   True, clock, clock, "TEST_FIXTURE")
    public = assess(book, request, (), as_of=clock + US)
    before = assess(book, request, facts, approval=approval, as_of=clock)
    result = assess(book, request, facts, approval=approval, as_of=clock + US, allow_test_fixture=True)
    if public["after"] is not None or before["after"] is not None or result["after"] is None:
        raise ValueError("PORTFOLIO_TASK_POLICY_PROJECTION_MISMATCH")
    return dict(at=clock + US, operation=operation, fixture_plan_identity=plan, quantity=quantity, before=book,
                public=public, without_visible_approval=before, fixture=result)


def source_steps(timeline):
    episodes = defaultdict(list)
    for row in timeline:
        if row["mode"] == "TEST_FIXTURE" and row.get("changed") and row["operation"] in (
            "PROTECT_ADD", "PROTECT_WITHDRAW",
        ):
            episodes[row["episode"]].append(row)
    return episodes


def project_tape(steps):
    # These inputs are the separately scoped case seeds from the prior report.
    first = steps[0]
    contract = first["contract"]
    prior = first["before"]
    book = Book(contract, first["episode"], "SHORT", local_clock(prior["at"]),
                Decimal(prior["position"]["short"]), Decimal(prior["protected_long"]), attempt=1)
    rows = []
    for row in steps:
        new_protection = Decimal(row["after"]["protected_long"])
        if row["operation"] == "PROTECT_WITHDRAW":
            operation, qty = "RECOVER_ORIGINAL", book.protection
        else:
            operation = ("PROTECT_EARLY" if row["id"] in EARLY_PROTECTION_CASES
                         else "PROTECT_TOPUP" if book.protection else "PROTECT_REGULAR")
            qty = new_protection - book.protection
        plan = row["conditions"]["observed_publication_revision"] or row["id"]
        event = project_fixture(book, operation, qty, local_clock(row["at"]), plan=plan)
        book = event["fixture"]["after"]
        if asdict(book.visible) != (row["after"]["position"] | dict(
            long=Decimal(row["after"]["position"]["long"]), short=Decimal(row["after"]["position"]["short"]),
        )):
            raise ValueError("PORTFOLIO_TASK_POLICY_TAPE_DIVERGED")
        rows.append(event)
    return rows


def project_oil(timeline):
    exits = [row for row in timeline if row["mode"] == "OI_TEST_ROLE_EXIT"]
    result = {}
    for row in exits:
        old = row["result"]
        qty = Decimal(old["qty"])
        operation = "RECOVER_ORIGINAL" if old["purpose"] == "RESUME_TREND" else "EXIT_COUNTER_M"
        before = old["before"]
        clock = local_clock(row["at"])
        book = Book(row["contract"], row["episode"], "SHORT", clock - 4 * US,
                    Decimal(before["trend"]["short"]), Decimal(before["trend"]["long"]),
                    Decimal(before["counter_m"]["long"]), attempt=1)
        event = project_fixture(book, operation, qty, clock, plan=row["source"])
        after = event["fixture"]["after"].visible
        expected = old["after"]["aggregate"]
        if (after.long, after.short) != (Decimal(expected["long"]), Decimal(expected["short"])):
            raise ValueError("PORTFOLIO_TASK_POLICY_OIL_DIVERGED")
        result[row["episode"]] = [event]
    return result


def gated_replay(bars, cutoff):
    """Keep old directional suggestions while requiring independent management evidence."""
    if not bars:
        return [], []
    state, book, transitions, blocked = near.initial_state(bars), None, [], []
    for index, bar in enumerate(bars):
        if not bar.end + US < cutoff:
            break
        proposal = near.evaluate(state, bars, index, managed_lifecycle=True)["proposal"]
        if proposal is None:
            continue
        action = proposal["action"]
        plan = proposal["plan_id"]
        clock = local_clock(proposal["generated_at"]) + 3 * US
        evaluated_at = clock + US
        if not evaluated_at < cutoff:
            break
        if action == "LOCK":
            intent = Intent(book, "PROTECT_REGULAR", book.original, plan, clock + ONE)
            result = assess(book, intent, (), as_of=evaluated_at)
            blocked.append(dict(at=evaluated_at, underlying_signal_at=proposal["generated_at"],
                                operation=intent.operation, unknown=result["unknown"]))
            continue
        if action.startswith("ENTER_"):
            book = Book(bar.contract, plan, proposal["plan"]["side"], local_clock(state["known_at"]))
            operation, qty = "ENTER_TREND", UNIT
        elif action == "CLEAR" and book is not None:
            operation, qty = "CLEAR_TREND", book.original
        else:
            raise ValueError("PORTFOLIO_TASK_POLICY_UNEXPECTED_DIRECTIONAL_ACTION")
        projected = project_fixture(book, operation, qty, clock, plan=plan)["fixture"]["after"]
        if projected is None or projected.known_at != evaluated_at:
            raise ValueError("PORTFOLIO_TASK_POLICY_EVALUATION_CLOCK_MISMATCH")
        old, new = book.visible, projected.visible
        candidate_state = near._apply(state, proposal, evaluated_at, None)
        if (candidate_state["long"], candidate_state["short"]) != tuple(map(str, (new.long, new.short))):
            raise ValueError("PORTFOLIO_TASK_POLICY_DIRECTIONAL_ADAPTER_DIVERGED")
        state, book = candidate_state, projected
        transitions.append(dict(at=evaluated_at.isoformat(), action=action,
                                before=list(map(str, (old.long, old.short))),
                                after=list(map(str, (new.long, new.short)))))
    return transitions, blocked


def rolling_comparison(session, market, frozen):
    gates = {}

    def challenger(bars, cutoff):
        actions, blocked = gated_replay(bars, cutoff)
        for split in (bars[0].end, bars[len(bars) // 2].end, cutoff):
            prefix = [b for b in bars if b.end + US < split]
            replayed = gated_replay(prefix, split)
            expected = (
                [item for item in actions if local_clock(item["at"]) < split],
                [item for item in blocked if item["at"] < split],
            )
            if replayed != expected or replayed != gated_replay(bars, split):
                raise ValueError("PORTFOLIO_TASK_POLICY_PREFIX_DIVERGED")
        gates[bars[0].contract] = dict(directional_actions=len(actions), blocked_locks=blocked)
        return VARIANT, actions

    result = audit_legs(session, market, extra_variant=challenger)
    stats = result["classifications"]
    if set(result["contracts"]) != set(frozen["contracts"]):
        raise ValueError("PORTFOLIO_TASK_POLICY_AUDIT_CONTRACTS_CHANGED")
    for contract, rows in result["contracts"].items():
        matched = [{**r, "by_variant": {k: v for k, v in r["by_variant"].items() if k != VARIANT}}
                   if "by_variant" in r else r for r in rows]
        if json.loads(encoded(matched)) != frozen["contracts"][contract]:
            raise ValueError("PORTFOLIO_TASK_POLICY_BASELINE_AUDIT_CHANGED")
    return dict(variant=VARIANT, classifications=stats, gates=gates, contracts=result["contracts"],
                external_management_conditions_supplied=0, directional_approvals_are_fixtures=True,
                screenshot_positions_used_as_inputs=False)


def study():
    previous, audit = verified_json(*TIMELINE), verified_json(*AUDIT)
    timeline = previous["timeline"]
    coverage = {c: [] for c in previous["contracts"]}
    episodes = {key: project_tape(steps) for key, steps in source_steps(timeline).items()}
    (soda,) = (row for row in timeline if row["mode"] == "SA_RETROSPECTIVE_CONDITIONAL_REPLAY")
    action = soda["scenario"]["fixture"][-1]
    # Evaluate its historical subcase within the retrospective envelope.
    soda_rows = project_tape([action])
    episodes[soda["episode"]] = [dict(disclosed_at=soda["at"], historical_subcase=event)
                                  for event in soda_rows]
    episodes.update(project_oil(timeline))
    for episode in episodes:
        coverage[episode.partition(":")[0]].append(episode)
    counts = {}
    for variant in ("baseline", "managed"):
        counts[variant] = {key: sum(row[variant].get(key, 0) for row in audit["classifications"].values())
                           for key in ("VISIBLE_LEGS_CHECKED", "AT_LEAST_ONE_QUOTE_COMPATIBLE",
                                       "TWO_VISIBLE_LEGS_CHECKED", "BOTH_LEGS_COMPATIBLE_AT_SAME_QUOTE")}
    return dict(version=VERSION, episodes=episodes, scope=coverage, frozen_benchmark=counts,
                rolling_nine_contract_comparison=None, conditional_episodes_source_conditioned=True,
                references=dict(timeline=TIMELINE[1], audit=AUDIT[1]),
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PORTFOLIO_TASK_POLICY_OUTPUT_EXISTS")
    try:
        report = study()
        if args.env_file:
            if not args.env_file.is_file():
                raise ValueError("PORTFOLIO_TASK_POLICY_ENV_FILE_MISSING")
            from dotenv import load_dotenv
            load_dotenv(args.env_file, override=False)
            from app.db.readonly import readonly_transaction
            from app.db.session import SessionLocal
            from app.market_data.composition import build_market_data_service
            from app.market_data.market_data_service import MarketDataError
            from sqlalchemy.exc import OperationalError

            try:
                with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
                    report["rolling_nine_contract_comparison"] = rolling_comparison(
                        session, build_market_data_service(session), verified_json(*AUDIT),
                    )
            except MarketDataError as exc:
                parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
            except OperationalError:
                parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
        result = encoded(report)
        with args.output.open("x", encoding="utf-8") as target:
            target.write(result)
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.isidentifier() and code.startswith('PORTFOLIO_TASK_') else 'PORTFOLIO_TASK_POLICY_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
