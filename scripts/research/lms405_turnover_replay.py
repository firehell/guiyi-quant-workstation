"""Check frozen LMS candidates against the conditional SH/JM screenshot chains."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms_near405 import CarryInSeed, replay
from lms405_carry_in_study import keybar_events, project
from lms405_counter_m_lot_roles import RETENTION, RETENTION_SHA
from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE, US
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

TURNOVER = Path("output/lms405-task-turnover-20261126/final-a.json")
TURNOVER_SHA = "057abdfc12cd517d8a30a7f596c1e1ab43d1a736767c9c926cd0297958c881e8"
SIDES = ("long", "short")


def quantities(row):
    return {side: Decimal(row[side]) for side in SIDES}


def state_at(seed, steps, cutoff):
    prior = [step for step in steps if step["at"] < cutoff]
    return quantities(prior[-1]["after"]) if prior else seed


def interval_check(before, steps, constraints):
    closes = {side: Decimal(0) for side in SIDES}
    opens = closes.copy()
    state = before
    for step in steps:
        if quantities(step["before"]) != state:
            raise ValueError("TURNOVER_REPLAY_TAPE_DISCONTINUITY")
        after = quantities(step["after"])
        for side in SIDES:
            delta = after[side] - state[side]
            if delta and min(after[side], state[side]) > 0:
                raise ValueError("TURNOVER_REPLAY_PARTIAL_LEG_UNSUPPORTED")
            opens[side] += max(delta, 0)
            closes[side] += max(-delta, 0)
        state = after
    failures = []
    for side in SIDES:
        constraint = constraints[side]
        # Each frozen candidate opens and closes whole modeled legs. If a
        # derivative changes that premise, this origin test must be extended.
        emptied = any(quantities(step["after"])[side] == 0 for step in steps)
        retained = 0 if emptied else before[side]
        for name, passes in (
            ("RETAINED", constraint["retained_min"] <= retained <= constraint["retained_max"]),
            ("CLOSE", closes[side] >= constraint["minimum_close"]),
            ("OPEN", opens[side] >= constraint["minimum_open"]),
        ):
            if not passes:
                failures.append(f"{side.upper()}_{name}")
    return failures


def compare_tape(seed, steps, seed_at, checkpoints):
    """Keep only chronologically reachable screenshot alignments."""
    action_minutes = [step["at"].replace(second=0, microsecond=0) for step in steps]
    if action_minutes != sorted(set(action_minutes)):
        raise ValueError("TURNOVER_REPLAY_INTRAMINUTE_SEQUENCE_UNSUPPORTED")
    last = seed_at
    for point in checkpoints:
        if last >= point["cuts"][0]:
            raise ValueError("TURNOVER_REPLAY_OVERLAPPING_CAPTURE_WINDOWS")
        last = point["cuts"][-1]
    possible = [seed_at]
    rows = []
    for point in checkpoints:
        source = point["source"]
        feasible, states, local_rejections = [], [], set()
        for cut in point["cuts"]:
            current = state_at(seed, steps, cut)
            visible = all(current[k] == v for k, v in point["visible"].items())
            quantity = current == point["conditional"]
            if quantity:
                for earlier in possible:
                    if earlier >= cut:
                        continue
                    interval = [step for step in steps if earlier <= step["at"] < cut]
                    failed = interval_check(state_at(seed, steps, earlier), interval, point["bounds"])
                    local_rejections.update(failed)
                    if not failed:
                        feasible.append(cut)
                        break
            prior = [step for step in steps if step["at"] < cut]
            states.append(dict(cutoff=cut, lots=current, visible_legs_match=visible,
                               conditional_quantities_match=quantity,
                               last_transition=prior[-1] if prior else None))
        rows.append(dict(
            source=source, capture_scope=point["scope"], checkpoints=states,
            any_visible_quantity_match=any(row["visible_legs_match"] for row in states),
            any_conditional_quantity_match=any(row["conditional_quantities_match"] for row in states),
            cumulative_quantity_and_turnover_match=bool(feasible),
            feasible_checkpoints=sorted(set(feasible)), rejected_interval_fields=sorted(local_rejections),
        ))
        possible = feasible
    first = next((row for row in rows if not row["cumulative_quantity_and_turnover_match"]), None)
    return dict(
        rows=rows, full_chain_match=bool(possible), first_conflict=first["source"] if first else None,
        first_conflict_kind=(("TURNOVER_OR_SEQUENCE" if first["any_conditional_quantity_match"]
                              else "QUANTITY") if first else None),
    )


def candidate_steps(contract, raw, bars, seed_at, through, lots, source, first_checkpoint):
    position = Position(contract, lots, lots)
    seed = CarryInSeed(contract, seed_at, "SHORT", True, source)
    tapes = {"HOLD_BOTH": []}
    price_events = keybar_events(bars[5], raw[1], seed_at, through)
    for name, events in price_events.items():
        tapes[name] = [step for step in project(position, seed_at, events) if step["action"]]
    for name, options in (
        ("LOCKED_PROXY_EXIT", {}),
        ("LOCKED_SEPARATE_EXIT", {"carry_exit_evidence": ()}),
    ):
        simulation = replay(bars[5], as_of=through, timely_fixture=True, carry_in=seed, **options)
        prefix = replay(bars[5], as_of=seed_at, carry_in=seed, **options)
        if quantities(prefix["current_state"]) != {"long": 1, "short": 1}:
            raise ValueError("TURNOVER_REPLAY_SEED_UNAVAILABLE")
        clipped = [bar for bar in bars[5] if bar.end + US <= first_checkpoint]
        earlier = replay(clipped, as_of=first_checkpoint, timely_fixture=True, carry_in=seed, **options)
        if earlier["transitions"] != [row for row in simulation["transitions"]
                                     if datetime.fromisoformat(row["known_at"]) < first_checkpoint]:
            raise ValueError("TURNOVER_REPLAY_PREFIX_DIVERGED")
        tapes[name] = [
            dict(at=datetime.fromisoformat(row["known_at"]), action=row["action"], reason=row["reason"],
                 before={side: Decimal(row["before"][side]) * lots for side in SIDES},
                 after={side: Decimal(row["after"][side]) * lots for side in SIDES})
            for row in simulation["transitions"]
        ]
    return tapes


def capture_cuts(raw_minutes, capture, quote):
    first, last = (datetime.fromisoformat(capture[key]) for key in ("earliest", "latest"))
    eligible = {row.bar_end: row for row in raw_minutes
                if str(row.trading_day) == capture["day"] and first <= row.bar_end <= last}
    if first not in eligible or last not in eligible:
        raise ValueError("TURNOVER_REPLAY_CAPTURE_MISSING")
    if capture["scope"] == "JOINT_QUOTE_ANCHOR":
        return [first]
    minutes = list(eligible)
    if capture["scope"] == "SINGLE_ROW_QUOTE_MINUTE_ENVELOPE":
        minutes = sorted(datetime.fromisoformat(end) for end in quote["contains"])
        mark = Decimal(quote["mark"])
        if (minutes[0] != first or minutes[-1] != last
                or any(end not in eligible or not eligible[end].low <= mark <= eligible[end].high for end in minutes)):
            raise ValueError("TURNOVER_REPLAY_CAPTURE_PRICE_CHANGED")
    # The minute display carries no event order. Check both boundary states.
    return sorted(set(minutes) | {end - ONE for end in minutes})


def study(session, market, turnover, retention, *, reprotection=None):
    scenarios, markets = {}, {}
    quotes = scoped_input_quotes()
    for name, case in turnover["cases"].items():
        contract = case["contract"]
        if reprotection is not None and contract != "SH2701":
            continue
        refs = retention["contracts"][contract]
        sources = [turnover["sources"][key] for key in case["sources"]]
        days = tuple(sorted({date.fromisoformat(row["trading_day"]) for row in sources}))
        raw, bars = read_pair(session, market, contract, days)
        by_day = {day.isoformat(): [bar for bar in raw[1] if bar.trading_day == day] for day in days}
        for day, rows in by_day.items():
            if refs["market"][day] != dict(count=len(rows), sha256=bars_sha(rows)):
                raise ValueError("TURNOVER_REPLAY_MARKET_CHANGED")
        markets[name] = {f"{period}m": dict(count=len(rows), sha256=bars_sha(rows)) for period, rows in raw.items()}
        first, *later = case["sources"]
        seed_at = datetime.fromisoformat(sources[0]["published_at"]) + ONE
        seed = quantities(case["conditional_exposure"][0])
        if seed["long"] != seed["short"] or not seed["short"]:
            raise ValueError("TURNOVER_REPLAY_LOCKED_SEED_REQUIRED")
        points = []
        for source, displayed, exposure, transition in zip(
            later, case["displayed_legs"][1:], case["conditional_exposure"][1:],
            case["conditional_transitions"], strict=True,
        ):
            capture = refs["capture_scopes"][source]
            cuts = capture_cuts(raw[1], capture, quotes.get((source, contract)))
            if cuts[0] <= seed_at:
                raise ValueError("TURNOVER_REPLAY_CAPTURE_PRECEDES_SEED")
            points.append(dict(source=source, cuts=cuts, scope=capture["scope"],
                               displayed_legs=displayed,
                               visible={side: Decimal(row["quantity"]) for side, row in displayed.items()},
                               conditional=quantities(exposure), bounds=transition["sides"]))
        through = max(point["cuts"][-1] for point in points)
        tapes = (
            candidate_steps(contract, raw, bars, seed_at, through, seed["short"], first, points[0]["cuts"][0])
            if reprotection is None
            else reprotection(raw, bars, seed_at, through, seed, points)
        )
        scenarios[name] = dict(
            contract=contract, seed_source=first, seed_at=seed_at, seed=seed,
            tapes=tapes, comparisons={key: compare_tape(seed, tape, seed_at, points)
                                      for key, tape in tapes.items()},
        )
    return dict(
        version="lms405-conditional-turnover-replay-v1", scenarios=scenarios, market=markets,
        fixture_only=True, capture_counts_are_quote_checkpoints=True,
        assumptions=[*turnover["conditional_assumptions"], "SAME_SEED_LEGS_PERSIST_UNTIL_POST_MINUTE_END"],
        references=dict(turnover=TURNOVER_SHA, retention=RETENTION_SHA),
        admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.env_file.is_file():
        parser.error("TURNOVER_REPLAY_OUTPUT_EXISTS_OR_ENV_MISSING")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        turnover = verified_json(TURNOVER, TURNOVER_SHA)
        retention = verified_json(RETENTION, RETENTION_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), turnover, retention)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "TURNOVER_REPLAY_LOCAL_MDS_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('TURNOVER_REPLAY_') and code.isidentifier() else 'TURNOVER_REPLAY_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
