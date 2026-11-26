"""Separate the short's risk boundary from an opposing keybar's regime exit."""

from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, load_specs, lot_profile, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows
from lms405_portfolio_replay import input_sources
from lms405_portfolio_task_policy import REGIME_REVERSAL_EXIT, replay_scoped_policy
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms405_range_exit_portfolio import STARTS, compatibility_changes
from lms405_replay import display
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest
from lms405_v_ta_case import identity
from lms_near405_replay import encoded

CONTRACT = "I2701"
FROZEN = (Path("output/lms405-range-exit-portfolio-20261126/final-a.json"),
          "00ffb053035f4062b8ac60e584fc69740a69d5a6172be1c9d5521e65a7c522d6")
PLANS = (
    ("A5356507058536457", "RANGE", "RANGE_DIVIDER_UPPER", "686.5"),
    ("A5356884629782554", "SHORT_TREND", "EXTREME_M_UPPER", "685.5"),
    ("A5357264059367516", "RANGE_SHORT_STRONG", "EXTREME_M_UPPER", "685.5"),
    ("A5358325549629506", "RANGE_SHORT_STRONG", "EXTREME_M_UPPER", "685.5"),
    ("A5358686423089344", "RANGE", "EXTREME_M_UPPER", "685.5"),
)


def evidence_gate(plans, *, allow_price_proxy):
    def decide(book, shape, bar, evaluated_at):
        if book.contract != CONTRACT or book.direction != "SHORT":
            return dict(admitted=True, reason="OUTSIDE_IRON_SHORT_SCOPE")
        if shape.contract != book.contract or bar.contract != book.contract:
            raise ValueError("IRON_EXIT_CONTRACT_MISMATCH")
        current = next((plan for plan in reversed(plans) if plan["known_at"] < evaluated_at), None)
        if current is None:
            return dict(admitted=False, reason="NO_SCOPED_CONTEMPORARY_EXIT_EVIDENCE")
        details = dict(revision=current["revision"], published_plan_state=current["state"],
                       known_at=current["known_at"], role=current["role"], edge=current["edge"], close=bar.close)
        if not allow_price_proxy:
            return details | dict(admitted=False, reason="EXPLICIT_ORIGINAL_EXIT_NOT_DISCLOSED")
        if shape.start <= current["known_at"]:
            return details | dict(admitted=False, reason="SHAPE_PRECEDES_PUBLISHED_REFERENCE")
        return details | dict(admitted=bar.close > current["edge"], reason="ADVERSE_UPPER_EDGE_SENSITIVITY")
    return decide


def summarize_exit_tape(actions, blocked):
    return dict(
        risk_exits=[row for row in actions if row.get("research_exit_reason") == "RISK_INVALID"],
        reversal_exits=[row for row in actions if row.get("research_exit_reason") == REGIME_REVERSAL_EXIT],
        pending_reversals=[row | dict(minute_end=display(row["at"])) for row in blocked
                           if "reversal_evidence" in row],
    )


def study(session, market):
    baseline = verified_json(*FROZEN)
    cutoff = datetime.fromisoformat(baseline["as_of"])
    index = input_sources()
    plans = []
    for revision, state, role, edge in PLANS:
        source = load_source(index, revision)
        # The source supplies only a displayed minute and no historical revision certificate.
        known = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
        plans.append(dict(revision=revision, state=state, role=role, edge=Decimal(edge), known_at=known, source=source))
    if sorted({plan["known_at"] for plan in plans}) != [plan["known_at"] for plan in plans]:
        raise ValueError("IRON_EXIT_SOURCE_TIMELINE_CHANGED")

    raw, series = read_pair(session, market, CONTRACT, tuple(day for day in ALL_DAYS if day >= STARTS[0]))
    spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
    unit_lots = lot_profile(verified_json(SIZE, SIZE_SHA))[CONTRACT]
    results = {}
    for start in STARTS:
        frozen = baseline["contracts"][CONTRACT][start.isoformat()]
        minutes = [bar for bar in raw[1] if bar.trading_day >= start]
        fives = [bar for native, bar in zip(raw[5], series[5], strict=True)
                 if native.trading_day >= start and bar.end + US <= cutoff]
        if identity(minutes) != frozen["market"]["1m"] or digest(fives) != frozen["market"]["5m_prefix_sha256"]:
            raise ValueError("IRON_EXIT_MARKET_CHANGED")
        scoped = FROZEN_SCOPE | dict(range_exit_requires_confirmation=True)
        actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, **scoped)
        if json.loads(encoded((actions, blocked))) != [frozen["actions"], frozen["blocked"]]:
            raise ValueError("IRON_EXIT_CONTROL_CHANGED")
        cases = {}
        for mode, allow_price_proxy in (("require_disclosed_exit", False), ("published_edge_proxy", True)):
            check = evidence_gate(plans, allow_price_proxy=allow_price_proxy)
            actions, blocked, *_ = replay_scoped_policy(
                fives, minutes, cutoff, index, **scoped, original_reversal_evidence=check,
            )
            comparisons = compare_rows(CONTRACT, frozen["comparisons"], "replay", actions, minutes,
                                       unit_lots, None, spec["tick"])
            totals = summarize({CONTRACT: comparisons})[CONTRACT]
            cases[mode] = dict(
                actions=actions, blocked=blocked, exit_tape=summarize_exit_tape(actions, blocked),
                comparisons=comparisons, strict=totals["strict_replay"],
                changed_quotes=compatibility_changes(frozen["comparisons"], comparisons),
            )
        results[start.isoformat()] = dict(control=frozen["strict_replay"], comparisons=cases,
                                           market=frozen["market"])
    return dict(
        study="I2701_ORIGINAL_SHORT_REGIME_EXIT_EVIDENCE", contract=CONTRACT, plans=plans, as_of=cutoff,
        windows=results, reference_sha256=FROZEN[1], risk_gate_unchanged=True,
        published_upper_edge_is_sensitivity=True, snapshots_used_as_inputs=False,
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("IRON_EXIT_")
                        else "IRON_EXIT_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
