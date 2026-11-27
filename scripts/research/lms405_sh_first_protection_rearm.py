"""Bound SH2701's first protection after the early shape loses its low."""

from argparse import ArgumentParser
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405.portfolio_tasks import REQUIRED, Book, Intent
from guiyi_quant.lms405.public_conditions import Condition
from lms405_first_night_confirmation_clocks import DAY, POST, START
from lms405_first_night_shape_cross import PHOTO, breaches
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_quantity_stages import compatible_allocations
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

CONTRACT, PLAN = "SH2701", "A5356884885635211"
FROZEN = Path("output/lms405-first-night-shape-cross-20261126/final-a.json")
FROZEN_SHA = "4db4187de74921b82541804d27af1072578179402f71ab8fef0da8ae4ade6877"
QUOTE = at("2026-10-22T22:08")
NEAR, FAR = Decimal(1610), Decimal(1632)
TICK = Decimal(1)


def reclaim_tape(minutes, *, edge, required):
    """Pair every minute with any prior, still-active qualifying close sequence."""
    count, known, previous = 0, None, None
    observations, eligible = [], []
    for bar in minutes:
        if previous is not None and bar.start != previous.end:
            count, known = 0, None
        previous = bar
        if known is not None and known < bar.end:
            eligible.append((bar, known))
        if bar.close <= edge:
            count, known = 0, None
        else:
            count += 1
            if count == required:
                known = bar.end + US
                observations.append((bar.end, bar.close))
    return observations, eligible


def stage_allocations(earlier, later, quote_end, *, lots, totals):
    """Assign lots to early protection, later pre-quote bars, or the quote minute."""
    stages = (earlier, [bar for bar in later if bar.end < quote_end], [bar for bar in later if bar.end == quote_end])
    bounds = tuple(tick_bounds(rows, TICK) for rows in stages)
    allocations = compatible_allocations(lots, totals, bounds)
    return dict(
        stage_price_ticks=bounds,
        eligible_ends=[[display(bar.end) for bar in rows] for rows in stages],
        allocations=allocations,
        early_only=(lots, 0, 0) in allocations,
        late_only=any(early == 0 for early, _, _ in allocations),
        both=any(early and (middle or quote) for early, middle, quote in allocations),
        without_quote_minute=any(quote == 0 for _, _, quote in allocations),
    )


def first_close_reset(minutes, breach, quote_end, *, lots, totals):
    """Compare protection windows after the first intraminute breach closes back inside."""
    breach_end, edge = breach["breach_end"], breach["boundary"]
    before = [bar for bar in minutes if bar.end <= breach_end]
    after = [bar for bar in minutes if breach_end <= bar.start and bar.end <= quote_end]
    if not before or before[-1].end != breach_end or before[-1].close > edge:
        raise ValueError("SH_FIRST_CLOSE_RESET_NOT_OBSERVED")
    # The whole range of each proven recross is an optimistic price allowance.
    # Only a recross after a completed close on the inactive side can rearm this path.
    recrosses = [bar for prior, bar in zip([before[-1], *after], after)
                 if prior.end == bar.start and prior.close <= edge < bar.high
                 and (bar.open <= edge or bar.low <= edge < bar.close)]
    result = {
        "no_rearm": stage_allocations(before, (), quote_end, lots=lots, totals=totals),
        "fresh_intraminute_recross_minutes_only": stage_allocations(before, recrosses, quote_end,
                                                                    lots=lots, totals=totals),
    }
    for required in (1, 2):
        observations, eligible = reclaim_tape(after, edge=edge, required=required)
        for overlap in (False, True):
            rows = [bar for bar, known in eligible if overlap or known < bar.start]
            key = f"{required}_close_rearm_{'overlap' if overlap else 'complete_minutes_only'}"
            result[key] = stage_allocations(before, rows, quote_end, lots=lots, totals=totals) | dict(
                rearm_closes=observations,
            )
    return dict(edge=edge, breach_close=before[-1].close, reset_end=breach_end,
                witnessed_recross_minute_ends=[bar.end for bar in recrosses], allocations=result)


def conditional_topup(series, controls, source):
    """Test a separately authorized top-up from an explicitly hypothetical partial position."""
    from lms405_plan_driven_replay import (
        EXTERNAL_FIXTURE_PREFIX,
        INPUT_VERSION,
        PlanRevision,
        replay_input,
        revision_digest,
        revision_record,
    )

    reset = controls["reset_end"]
    cutoff = QUOTE
    original, partial = 20, 10
    seed = Book(CONTRACT, "SH2701:2026-10-22:HYPOTHETICAL_PARTIAL_PROTECTION", "SHORT", reset + US,
                Decimal(original), Decimal(partial), attempt=1)
    metadata_time = datetime.fromisoformat(source["published_at"])
    plan = PlanRevision(CONTRACT, f"{PLAN}:CONDITIONAL_TOPUP", metadata_time, metadata_time + ONE, source["source_url"],
                        frozenset({"PROTECT_TOPUP"}))
    baseline = {}
    for shape, confirm in VARIANTS:
        events = signals(series, shape, confirm, start=seed.known_at + US, cut=cutoff, side="LONG")
        baseline[f"{shape}m_to_{confirm}m"] = [row for row in events if NEAR <= row["close"] <= FAR]
    visible_minutes = completed(series[1], reset, cutoff)
    clock_rows = {}
    for n in (1, 2):
        closes, _ = reclaim_tape(visible_minutes, edge=controls["edge"], required=n)
        if not closes:
            clock_rows[str(n)] = dict(candidate_close_at=None, status="NO_VISIBLE_RECROSS_CONFIRMATION")
            continue
        clock, close = closes[0]
        if not seed.known_at < clock or not NEAR <= close <= FAR:
            raise ValueError("SH_TOPUP_SCOPE_CHANGED")
        request = Intent(seed, "PROTECT_TOPUP", Decimal(original - partial), plan.id, clock + ONE + US)
        source_id = (f"{EXTERNAL_FIXTURE_PREFIX}{revision_digest(plan)}:"
                     + sha(encoded((controls["edge"], reset, n, clock, close)).encode()))
        facts = tuple(Condition(name, request.scope, CONTRACT, True, clock, clock + US, source_id, "EVENT_TIME")
                      for name in REQUIRED[request.operation])
        evaluation_at = clock + 4 * US
        approval = dict(scope=request.confirmation_scope(facts), id=f"TEST_FIXTURE:SH_TOPUP:{n}", accepted=True,
                        decided_at=clock + 2 * US, known_at=clock + 3 * US, record_kind="TEST_FIXTURE")
        evidence = dict(**asdict(request), at=evaluation_at, facts=[asdict(fact) for fact in facts])
        tape = dict(version=INPUT_VERSION, cutoff=cutoff, seed=asdict(seed), revisions=[revision_record(plan)])

        def replay_case(changes, *, fixture=True):
            inputs = json.loads(encoded(tape | {"evaluations": [evidence | changes]}))
            return replay_input(**inputs, allow_test_fixture=fixture)

        public = replay_case({"facts": []}, fixture=False)
        signal_only = replay_case({})
        approved = replay_case({"approval": approval})
        at_same_clock = replay_case({"at": approval["known_at"], "approval": approval})
        statuses = [row["events"][0]["status"] for row in (public, signal_only, approved, at_same_clock)]
        positions = [row["final"]["protection"] for row in (public, signal_only, approved, at_same_clock)]
        if (statuses != ["INDETERMINATE", "INDETERMINATE", "CONDITIONAL_ACTION", "INDETERMINATE"]
                or positions != [partial, partial, original, partial] or approved["final"]["original"] != original):
            raise ValueError("SH_TOPUP_PERMISSION_CHANGED")
        strict = controls["allocations"][f"{n}_close_rearm_complete_minutes_only"]
        overlap = controls["allocations"][f"{n}_close_rearm_overlap"]
        clock_rows[str(n)] = dict(
            candidate_close_at=clock, candidate_close=close, public_input=public, fixture_without_approval=signal_only,
            fixture_at_approval_visibility=at_same_clock, approved_fixture=approved,
            partial_seed_quantity_price_compatible={
                name: any(row[0] == partial and sum(row) == original for row in result["allocations"])
                for name, result in (("whole_minutes_only", strict), ("allow_overlap", overlap))
            },
        )
    return dict(partial_seed=asdict(seed), default_fresh_in_band_candidates=baseline,
                explicit_test_fixture_clocks=clock_rows, historical_plan_revision_verified=False)


def study(session, market, *, reset_at_first_close=False, include_topup=False):
    reference = verified_json(FROZEN, FROZEN_SHA)
    case = reference["cases"][CONTRACT]
    index = input_sources()
    source = load_source(index, PLAN)
    photo = reference["photo"]
    if (source != case["plan"] or datetime.fromisoformat(source["published_at"]) >= START
            or load_source(index, PHOTO) != reference["photo_source"]
            or sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]):
        raise ValueError("SH_REARM_SOURCE_CHANGED")
    series = read_window(session, market, CONTRACT, DAY)
    if {f"{p}m": digest(rows) for p, rows in series.items()} != case["market"]:
        raise ValueError("SH_REARM_MARKET_CHANGED")
    minutes = completed(series[1], START, POST)
    mark = Decimal(case["quote_mark"])
    if [b.end for b in minutes if b.low <= mark <= b.high] != [QUOTE]:
        raise ValueError("SH_REARM_QUOTE_CHANGED")
    (breach,) = breaches(series[5], minutes, START, QUOTE)
    known, high = breach["observation_known_at"], breach["boundary"]
    if (breach["shape_ohlc"][2] != NEAR or tuple(map(Decimal, case["protection_band"])) != (NEAR, FAR)
            or not breach["within_minute_upward_cross_proven"]):
        raise ValueError("SH_REARM_PRICE_ROLE_CHANGED")
    frozen = case["by_quote_minute"][display(QUOTE)]
    if encoded(breach) != encoded(frozen["first_observed_breach"]):
        raise ValueError("SH_REARM_BREACH_CHANGED")
    prefix = [bar for bar in minutes if bar.end <= QUOTE]
    lots = case["visible_long"]["today_quantity"]
    totals = displayed_tick_totals(Decimal(case["visible_long"]["opening_average"]), lots, TICK)
    if reset_at_first_close or include_topup:
        controls = first_close_reset(prefix, breach, QUOTE, lots=lots, totals=totals)
        output = dict(
            study="SH2701_FIRST_PROTECTION_BREACH_CLOSE_RESET", snapshot=reference["photo_source"],
            photo=photo, plan=source, reference_sha256=FROZEN_SHA, market=case["market"], shape_breach=breach,
            quote_end=QUOTE, quote_mark=mark, quote_ohlc=ohlc(prefix[-1]), visible_long=case["visible_long"],
            controls=controls, author_action_samples=0, author_match_rate=None, actual_quote_time=None,
            executable=False, fills=None, pnl=None,
        )
        if include_topup:
            output["conditional_topup"] = conditional_topup(series, controls, source)
        return output
    loss = next(bar for bar in prefix if bar.start >= known and bar.close < NEAR)
    if loss.end != datetime.fromisoformat(frozen["bounds"]["first_later_close_below_shape_low"]):
        raise ValueError("SH_REARM_LOSS_CHANGED")
    remaining = [bar for bar in prefix if bar.start >= loss.end]
    # A new shape must start after the failure was observable. The quote minute only brackets price.
    fresh = {f"{a}m_to_{b}m": signals(series, a, b, start=loss.end + US, cut=QUOTE, side="LONG")
             for a, b in VARIANTS}
    results = {}
    checks = 0
    for name, (edge, required) in {
        "published_near_one_close": (NEAR, 1), "published_near_two_closes": (NEAR, 2),
        "prior_shape_high_one_close": (high, 1), "prior_shape_high_two_closes": (high, 2),
    }.items():
        observations, eligible = reclaim_tape(remaining, edge=edge, required=required)
        for i in range(len(remaining) + 1):
            short = remaining[:i]
            end = short[-1].end if short else loss.end
            expected = ([row for row in observations if row[0] <= end],
                        [pair for pair in eligible if pair[0].end <= end])
            if reclaim_tape(short, edge=edge, required=required) != expected:
                raise ValueError("SH_REARM_PREFIX_DIVERGED")
            checks += 1
        results[name] = dict(edge=edge, required=required, observations=observations, eligible=eligible)
    output = {}
    for mode in ("whole_minutes_after_knowledge", "allow_knowledge_overlap"):
        overlap = mode == "allow_knowledge_overlap"
        earlier = [b for b in prefix if (b.end if overlap else b.start) > known and b.end <= loss.end]
        paths = {
            "old_permission_continues": remaining,
            "old_permission_ends_no_new_permission": (),
            **{name: [bar for bar, timestamp in route["eligible"] if overlap or timestamp < bar.start]
               for name, route in results.items()},
        }
        output[mode] = {name: stage_allocations(earlier, rows, QUOTE, lots=lots, totals=totals)
                        for name, rows in paths.items()}
    return dict(
        study="SH2701_FIRST_PROTECTION_REARM_PRICE_SENSITIVITIES",
        snapshot=reference["photo_source"], photo=photo, plan=source, reference_sha256=FROZEN_SHA,
        market=case["market"], shape_breach=breach, loss_end=loss.end, loss_ohlc=ohlc(loss),
        quote_end=QUOTE, quote_ohlc=ohlc(prefix[-1]), quote_mark=mark, visible_long=case["visible_long"],
        fresh_completed_shapes_before_quote_end=fresh, prefix_checks=checks,
        reclaims={name: {key: val for key, val in fields.items() if key != "eligible"}
                  for name, fields in results.items()},
        price_allocations=output, historical_plan_revision_verified=False, actual_quote_time=None,
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    batch = parser.add_mutually_exclusive_group()
    batch.add_argument("--reset-at-first-close", action="store_true")
    batch.add_argument("--conditional-topup", action="store_true")
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
            report = study(session, build_market_data_service(session), reset_at_first_close=args.reset_at_first_close,
                           include_topup=args.conditional_topup)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("SH_REARM_")
                        else "SH_REARM_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
