"""Apply one attributed-position policy to archived nine-contract research episodes."""

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as near
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.portfolio_tasks import REQUIRED, VERSION, Book, Intent, assess
from guiyi_quant.lms405.protection_band import active_band, visible_bands
from guiyi_quant.lms405.public_conditions import Condition
from lms405_portfolio_leg_audit import study as audit_legs
from lms405_portfolio_left_entry import (
    MODES as LEFT_MODES, assess_left_proposal, assumed_carry_comparison, left_signals, scope_for,
)
from lms405_portfolio_protection_gate import advance_due, plan_rows, price_admission
from lms405_portfolio_replay import input_sources
from lms405_portfolio_right_entry import active_branch, assess_entry, branches, entry_events
from lms405_protection_lot_timing import verified_json
from lms405_protection_signal_lifetime import lifetime
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import signals
from lms_near405_replay import encoded, sha

TIMELINE = (Path("output/lms405-portfolio-role-replay-20261126/reviewed-a.json"),
            "da5be560603b94445b642043d345c5a34c076292dc400a096a1fc89a6612093f")
AUDIT = (Path("output/lms405-portfolio-leg-audit-20261125/verified.json"),
         "93ddfe102a19d99cb5ec939b85f0dba82f7035b34a15d985a6564e1e070cb1cc")
VARIANT = "scoped_without_external_conditions"
PLAN_VARIANT = "published_band_protection_candidate"
RIGHT_VARIANT = "published_protection_and_right_entry_candidate"
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


def deferred_protection_touch(series, band, signal, period, cutoff):
    """Keep an advance candidate only until first contact in its own segment."""
    known = signal["available_at"]
    previous_end = signal["confirmed_at"]
    for bar in series[1]:
        if bar.end <= previous_end:
            continue
        if bar.start != previous_end or bar.end + US >= cutoff or bar.low > band.upper:
            return None
        if bar.low <= band.upper and band.lower <= bar.high:
            if bar.start <= known:
                return None
            (shape,) = [candidate for candidate in series[period] if candidate.end == signal["shape_end"]]
            audit = lifetime(series, signal | {"shape_low": shape.low}, period, 1,
                             as_of=bar.end + 2 * US, revision_at=None)
            return bar if audit["no_failure_observed_in_completed_prefix"] else None
        previous_end = bar.end
    return None


def published_protection_events(series, bands, cutoff, *, advance_at_touch=False):
    if not series[1]:
        return []
    contract = series[1][0].contract
    quotes = {bar.end: bar for bar in series[1]}
    events = []
    for period in (1, 5):
        for shape in signals(series, period, 1, side="LONG", start=series[1][0].start, cut=cutoff):
            known = shape["available_at"]
            ready_at = known + 5 * US
            if not ready_at < cutoff:
                continue
            band, _ = active_band(visible_bands(bands, contract, known), known, "SHORT")
            if band is None:
                continue
            step = period * ONE
            price = price_admission(series[1], band, shape, shape_step=step)
            regular = price["ordinary_due_at"] is not None
            if not regular and advance_due(quotes[shape["confirmed_at"]], band, price) is None:
                continue
            touch = None
            if advance_at_touch and not regular:
                touch = deferred_protection_touch(series, band, shape, period, cutoff)
                if touch is None:
                    continue
                ready_at = touch.end + 6 * US
            latest, _ = active_band(visible_bands(bands, contract, ready_at), ready_at, "SHORT")
            if latest != band or ready_at >= cutoff:
                continue
            events.append(dict(
                at=ready_at, known_at=known, shape_start=shape["shape_end"] - step,
                band=band, period=period, signal=shape,
                operation="PROTECT_REGULAR" if regular else "PROTECT_EARLY",
            ) | ({"touch_known_at": touch.end + US} if touch is not None else {}))
    return sorted(events, key=lambda row: (row["at"], row["period"]))


def gated_replay(bars, cutoff, protection_events=(), *, minutes=(), right_branches=(), right_events=(),
                 left_scope=None, left_mode=None, left_events=()):
    """Keep old directional suggestions while requiring independent management evidence."""
    if not bars:
        return [], []
    state, book, transitions, blocked = near.initial_state(bars), None, [], []
    queue = [(bar.end + 5 * US, 0, index) for index, bar in enumerate(bars)]
    queue.extend((row["at"], 1, index) for index, row in enumerate(protection_events))
    right_by_time = defaultdict(list)
    for row in right_events:
        right_by_time[row["at"]].append(row)
    queue.extend((instant, 2, 0) for instant in right_by_time)
    latest_five = None
    for evaluated_at, source, index in sorted(queue):
        if evaluated_at >= cutoff:
            break
        clock = evaluated_at - US
        entry_context = protection_context = left_context = None
        if source == 2:
            slot = sorted(right_by_time[evaluated_at], key=lambda row: row["clock"])
            directions = set()
            for row in slot:
                branch = row["branch"]
                direction = branch.case.direction
                if active_branch(right_branches, state["contract"], direction, evaluated_at) != branch:
                    raise ValueError("PORTFOLIO_TASK_POLICY_RIGHT_SCOPE_MISMATCH")
                directions.add(direction)
            if len(directions) != 1:
                blocked.append(dict(at=evaluated_at, operation="ENTER_RIGHT", reason="SAME_TIME_DIRECTION_CONFLICT"))
                continue
            if len(slot) > 1:
                blocked.append(dict(at=evaluated_at, operation="ENTER_RIGHT", reason="SAME_TIME_CONFIRMATIONS",
                                    selected_clock=slot[0]["clock"], duplicate_clocks=[r["clock"] for r in slot[1:]]))
            event = slot[0]
            branch = event["branch"]
            public = assess_entry(state["contract"], state, event)
            fixture = assess_entry(state["contract"], state, event, fixture=True)
            if public["permit"]:
                raise ValueError("PORTFOLIO_TASK_POLICY_UNAUTHORIZED_RIGHT_ENTRY")
            entry_context = dict(public=public, fixture=fixture, kind="TEST_FIXTURE")
            if not fixture["permit"] or latest_five is None:
                blocked.append(dict(at=evaluated_at, operation="ENTER_RIGHT", **entry_context))
                continue
            direction = branch.case.direction
            action, operation, qty = f"ENTER_{direction}", "ENTER_TREND", UNIT
            plan = sha(encoded([event | dict(branch=asdict(branch)), state]).encode())
            low, high = ((event["edge"], event["reference"]) if direction == "LONG" else
                         (event["reference"], Decimal(branch.case.opposite_invalidation)))
            # Reuse the managed exit proxy once the scope-bound research entry has happened.
            region = dict(plan_id=plan, side=direction, lower=str(low), upper=str(high), environment="RANGE",
                          created_index=latest_five, created_at=event["signal_known_at"].isoformat())
            proposal = dict(action=action, version=near.MANAGEMENT_VERSION, proposal_id=plan,
                            index=latest_five, plan=region)
            book = Book(state["contract"], plan, direction, local_clock(state["known_at"]))
        elif source == 1:
            event = protection_events[index]
            area = event["band"]
            if (book is None or book.direction != "SHORT" or not book.original or book.protection
                    or not book.known_at < event["shape_start"]
                    or (event["operation"] == "PROTECT_EARLY" and not book.known_at < area.effective_after)):
                continue
            if event["operation"] == "PROTECT_REGULAR":
                scoped_price = price_admission(minutes, area, event["signal"], position_since=book.known_at,
                                               shape_step=event["period"] * ONE)
                if scoped_price["ordinary_due_at"] is None:
                    continue
            proposal = dict(action="LOCK", plan=state["plan"])
            action, operation, qty = "LOCK", event["operation"], book.original
            plan = f"{state['plan']['plan_id']}:{area.scope}"
            protection_context = dict(revision=area.revision, url=area.source, band=[area.lower, area.upper],
                                      signal_known_at=event["known_at"], shape_start=event["shape_start"],
                                      confirmation_close=event["signal"]["close"], shape_period=event["period"],
                                      confirmation_period=1, operation=operation, approval_kind="TEST_FIXTURE")
            if "touch_known_at" in event:
                protection_context["deferred_until_touch_known_at"] = event["touch_known_at"]
        else:
            bar = bars[index]
            latest_five = index
            proposal = near.evaluate(state, bars, index, managed_lifecycle=True)["proposal"]
            if proposal is None:
                continue
            action = proposal["action"]
            plan = proposal["plan_id"]
        if not source and (action == "LOCK" or action.startswith("UNLOCK_")):
            operation = "PROTECT_REGULAR" if action == "LOCK" else "RECOVER_ORIGINAL"
            qty = book.original if action == "LOCK" else book.protection
            intent = Intent(book, operation, qty, plan, clock + ONE)
            result = assess(book, intent, (), as_of=evaluated_at)
            blocked.append(dict(at=evaluated_at, underlying_signal_at=proposal["generated_at"],
                                operation=intent.operation, unknown=result["unknown"]))
            continue
        if not source and action.startswith("ENTER_"):
            branch = active_branch(right_branches, bar.contract, proposal["plan"]["side"], evaluated_at)
            if branch is not None:
                blocked.append(dict(at=evaluated_at, operation="ENTRY_REPLACED_BY_RIGHT_BRANCH", action=action,
                                    source=branch.case.source, reason="REQUIRES_SEPARATE_PRICE_PATH_AND_SIGNAL"))
                continue
            if left_scope is not None and action == "ENTER_LONG" and left_scope.active(bar.contract, evaluated_at):
                left_context = assess_left_proposal(left_scope, left_events, left_mode, proposal, evaluated_at)
                if not left_context["can_project_fixture"]:
                    blocked.append(dict(at=evaluated_at, operation="ENTER_LEFT", action=action, left_entry=left_context))
                    continue
            book = Book(bar.contract, plan, proposal["plan"]["side"], local_clock(state["known_at"]))
            operation, qty = "ENTER_TREND", UNIT
        elif not source and action == "CLEAR" and book is not None:
            operation, qty = "CLEAR_TREND", book.original + book.protection
        elif not source:
            raise ValueError("PORTFOLIO_TASK_POLICY_UNEXPECTED_DIRECTIONAL_ACTION")
        projected = project_fixture(book, operation, qty, clock, plan=plan)["fixture"]["after"]
        if projected is None or projected.known_at != evaluated_at:
            raise ValueError("PORTFOLIO_TASK_POLICY_EVALUATION_CLOCK_MISMATCH")
        old, new = book.visible, projected.visible
        candidate_state = near._apply(state, proposal, evaluated_at, None)
        if (candidate_state["long"], candidate_state["short"]) != tuple(map(str, (new.long, new.short))):
            raise ValueError("PORTFOLIO_TASK_POLICY_DIRECTIONAL_ADAPTER_DIVERGED")
        state, book = candidate_state, projected
        row = dict(at=evaluated_at.isoformat(), action=action,
                   before=list(map(str, (old.long, old.short))), after=list(map(str, (new.long, new.short))))
        if protection_context is not None:
            row["protection"] = protection_context
        if entry_context is not None:
            row["right_entry"] = entry_context
        if left_context is not None:
            row["left_entry"] = left_context
        transitions.append(row)
    return transitions, blocked


def replay_scoped_policy(bars, raw_minutes, cutoff, index, *, published_bands, right_entries, left_mode,
                         advance_at_touch):
    """Evaluate the same scoped policy across different completed history windows."""
    symbol = bars[0].contract
    series = {1: [Bar(symbol, bar.bar_end, *ohlc(bar), start=bar.bar_end - ONE) for bar in raw_minutes],
              5: bars}
    plans, _, sources = plan_rows(index, symbol) if published_bands else ((), {}, {})
    scoped = branches(index, symbol) if right_entries else ()
    left_scope = scope_for(index, symbol) if left_mode is not None else None
    events = published_protection_events(series, plans, cutoff, advance_at_touch=advance_at_touch) if published_bands else []
    entries = entry_events(series, scoped, cutoff)
    left = left_signals(series, left_scope, cutoff)
    left_args = dict(left_scope=left_scope, left_mode=left_mode)
    actions, blocked = gated_replay(bars, cutoff, events, minutes=series[1],
                                   right_branches=scoped, right_events=entries, left_events=left, **left_args)
    for split in (bars[0].end, bars[len(bars) // 2].end, cutoff):
        prefix = [b for b in bars if b.end + US < split]
        sliced = {period: [b for b in candles if b.end + US < split] for period, candles in series.items()}
        available = published_protection_events(sliced, plans, split,
                                                 advance_at_touch=advance_at_touch) if published_bands else []
        if [e for e in events if e["at"] < split] != [e for e in available if e["at"] < split]:
            raise ValueError("PORTFOLIO_TASK_POLICY_SIGNAL_PREFIX_DIVERGED")
        right_prefix = entry_events(sliced, scoped, split)
        if right_prefix != [e for e in entries if e["at"] < split]:
            raise ValueError("PORTFOLIO_TASK_POLICY_RIGHT_PREFIX_DIVERGED")
        left_prefix = left_signals(sliced, left_scope, split)
        if left_prefix != [e for e in left if e["signal_known_at"] < split]:
            raise ValueError("PORTFOLIO_TASK_POLICY_LEFT_PREFIX_DIVERGED")
        replayed = gated_replay(prefix, split, available, minutes=sliced[1], right_branches=scoped,
                               right_events=right_prefix, left_events=left_prefix, **left_args)
        expected = (
            [item for item in actions if local_clock(item["at"]) < split],
            [item for item in blocked if item["at"] < split],
        )
        if replayed != expected or replayed != gated_replay(bars, split, events, minutes=series[1],
                                                           right_branches=scoped, right_events=entries,
                                                           left_events=left, **left_args):
            raise ValueError("PORTFOLIO_TASK_POLICY_PREFIX_DIVERGED")
    return actions, blocked, sources, scoped, events, entries, left_scope, left


def rolling_comparison(session, market, frozen, *, published_bands=False, right_entries=False, left_mode=None,
                       advance_at_touch=False):
    if left_mode is not None and (left_mode not in LEFT_MODES or not (published_bands and right_entries)):
        raise ValueError("PORTFOLIO_TASK_POLICY_LEFT_REQUIRES_PUBLISHED_ENTRIES")
    if advance_at_touch and not published_bands:
        raise ValueError("PORTFOLIO_TASK_POLICY_TOUCH_REQUIRES_PUBLISHED_BANDS")
    gates = {}
    left_minutes = {}
    index = input_sources() if published_bands else {}

    def challenger(bars, raw_minutes, cutoff):
        symbol = bars[0].contract
        actions, blocked, sources, scoped, events, entries, left_scope, left = replay_scoped_policy(
            bars, raw_minutes, cutoff, index, published_bands=published_bands, right_entries=right_entries,
            left_mode=left_mode, advance_at_touch=advance_at_touch,
        )
        gates[symbol] = dict(directional_actions=sum(row["action"] != "LOCK" for row in actions),
                             blocked_locks=blocked)
        if published_bands:
            gates[symbol].update(protections=[row for row in actions if row["action"] == "LOCK"],
                                 plan_sources=sources, historical_plan_revisions_verified=False)
        if advance_at_touch:
            gates[symbol]["deferred_market_candidates"] = [
                row | {"band": asdict(row["band"])} for row in events if "touch_known_at" in row
            ]
        if right_entries:
            gate = gates[symbol]
            gate.update(scoped_right_branches=[asdict(branch) for branch in scoped],
                        right_proposals=len(entries), accepted_right_entries=[r for r in actions if "right_entry" in r],
                        blocked_right_entries=[r for r in blocked if r["operation"] in (
                            "ENTER_RIGHT", "ENTRY_REPLACED_BY_RIGHT_BRANCH",
                        )])
            gate["isolated_flat_right_checks"] = [
                dict(assumed_flat_since=e["branch"].start, fixture=assess_entry(symbol, {
                    "contract": symbol, "long": "0", "short": "0", "cycle_id": None,
                    "known_at": e["branch"].start.isoformat(),
                }, e, fixture=True)) for e in entries
            ]
            gate["blocked_locks"] = [r for r in blocked if r not in gate["blocked_right_entries"]]
        if left_scope is not None:
            gate = gates[symbol]
            gate.update(scoped_left_branch=asdict(left_scope), left_market_geometry=left,
                        accepted_left_entries=[r for r in actions if "left_entry" in r],
                        blocked_left_entries=[r for r in blocked if r["operation"] == "ENTER_LEFT"])
            gate["blocked_locks"] = [r for r in gate["blocked_locks"] if r["operation"] != "ENTER_LEFT"]
            left_minutes[symbol] = raw_minutes
        return variant, actions

    variant = RIGHT_VARIANT if right_entries else PLAN_VARIANT if published_bands else VARIANT
    if left_mode is not None:
        variant = f"published_entries_left_{left_mode.replace('-', '_')}"
    if advance_at_touch:
        variant += "_advance_waits_first_touch"
    result = audit_legs(session, market, extra_variant=challenger)
    for symbol, minutes in left_minutes.items():
        gate = gates[symbol]
        gate["left_assumed_carry_comparison"] = assumed_carry_comparison(
            gate["left_market_geometry"], result["contracts"][symbol], minutes, variant,
        )
    stats = result["classifications"]
    if set(result["contracts"]) != set(frozen["contracts"]):
        raise ValueError("PORTFOLIO_TASK_POLICY_AUDIT_CONTRACTS_CHANGED")
    for contract, rows in result["contracts"].items():
        matched = [{**r, "by_variant": {k: v for k, v in r["by_variant"].items() if k != variant}}
                   if "by_variant" in r else r for r in rows]
        if json.loads(encoded(matched)) != frozen["contracts"][contract]:
            raise ValueError("PORTFOLIO_TASK_POLICY_BASELINE_AUDIT_CHANGED")
    result = dict(variant=variant, classifications=stats, gates=gates, contracts=result["contracts"],
                  external_management_conditions_supplied=0, directional_approvals_are_fixtures=True,
                  screenshot_positions_used_as_inputs=False)
    if published_bands:
        result.update(protection_source="PUBLISHED_REFERENCE_AND_COMPLETED_GEOMETRY",
                      protection_approvals_are_fixtures=True, source_revision_history_verified=False,
                      author_permissions_supplied=0)
    if right_entries:
        result["right_entries_are_conditional_test_fixtures"] = True
    if left_mode is not None:
        result.update(left_entry_mode=left_mode, left_entry_approvals_are_fixtures=True,
                      left_entry_clock="ONLY_EXISTING_5M_TO_5M_PROPOSALS")
    if advance_at_touch:
        result["advance_protection_clock"] = "SAME_SEGMENT_FIRST_TOUCH_AFTER_LIVE_CANDIDATE"
    return result


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
    parser.add_argument("--published-bands", action="store_true")
    parser.add_argument("--right-entries", action="store_true")
    parser.add_argument("--left-entries", choices=LEFT_MODES)
    parser.add_argument("--advance-at-touch", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PORTFOLIO_TASK_POLICY_OUTPUT_EXISTS")
    if (args.published_bands or args.right_entries or args.left_entries or args.advance_at_touch) and args.env_file is None:
        parser.error("PORTFOLIO_TASK_POLICY_ENV_FILE_MISSING")
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
                right_entries = args.right_entries or args.left_entries is not None
                with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
                    report["rolling_nine_contract_comparison"] = rolling_comparison(
                        session, build_market_data_service(session), verified_json(*AUDIT),
                        published_bands=args.published_bands or right_entries or args.advance_at_touch,
                        right_entries=right_entries, left_mode=args.left_entries, advance_at_touch=args.advance_at_touch,
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
