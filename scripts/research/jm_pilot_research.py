"""Read-only, fixed-window JM 5m retrospective causal research evidence."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

if TYPE_CHECKING:
    from app.market_data.newow.jm_pilot_research import JMPilotInput
    from guiyi_quant.newow.research_backtest import ResearchBacktestResult


SINCE = date(2025, 10, 11)
REQUESTED_THROUGH = date(2026, 10, 10)
AS_OF = datetime(2026, 10, 11, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _summary(result: ResearchBacktestResult) -> dict[str, object]:
    summary = result.summary
    return {
        "closed_trades": summary.closed_trade_count,
        "wins": summary.win_count,
        "losses": summary.loss_count,
        "breakevens": summary.breakeven_count,
        "compounded_net_return_pct": str(summary.compounded_net_return_pct),
        "closed_trade_drawdown_pct": str(summary.closed_trade_max_drawdown_pct),
        "rejected_fills": len(result.rejected_fills),
        "roll_exclusions": sum(
            item.reason == "DOMINANT_ROLL_EXCLUDED"
            for item in result.incomplete_positions
        ),
        "end_exclusions": sum(
            item.reason == "END_OF_SAMPLE_EXCLUDED"
            for item in result.incomplete_positions
        ),
        "cancelled_intents": result.cancelled_intent_count,
        "ignored_intents": result.ignored_intent_count,
    }


def _prefix_parity(source: JMPilotInput) -> dict[str, object]:
    from guiyi_quant.newow.research_backtest import (
        NewowStrategyReplaySegment,
        ResearchStrategy,
        build_strategy_intents_from_replay_segments,
    )

    full, versions = build_strategy_intents_from_replay_segments(
        source.replay_segments, ResearchStrategy.DUAL_FUSION
    )
    individually = tuple(
        intent
        for segment in source.replay_segments
        for intent in build_strategy_intents_from_replay_segments(
            (segment,), ResearchStrategy.DUAL_FUSION
        )[0]
    )
    if individually != full:
        raise ValueError("JM_PILOT_SEGMENT_BATCH_PARITY_FAILED")
    checkpoints = []
    for segment in source.replay_segments:
        eligible_indices = [
            index for index, bar in enumerate(segment.bars) if bar.observation_eligible
        ]
        for selected in (len(eligible_indices) // 2, len(eligible_indices) - 1):
            last = eligible_indices[selected]
            partial = NewowStrategyReplaySegment(segment.bars[: last + 1])
            prefix, _ = build_strategy_intents_from_replay_segments(
                (partial,), ResearchStrategy.DUAL_FUSION
            )
            eligible_ends = {
                bar.bar_end for bar in segment.bars[: last + 1]
                if bar.observation_eligible
            }
            expected = tuple(
                intent for intent in full
                if intent.signal_bar_end in eligible_ends
            )
            if prefix != expected:
                raise ValueError("JM_PILOT_PREFIX_INVARIANCE_FAILED")
            checkpoints.append({
                "physical_contract": segment.bars[0].physical_contract,
                "through": segment.bars[last].bar_end.isoformat(),
                "intent_count": len(prefix),
            })
    restarted, restarted_versions = build_strategy_intents_from_replay_segments(
        tuple(NewowStrategyReplaySegment(tuple(item.bars)) for item in source.replay_segments),
        ResearchStrategy.DUAL_FUSION,
    )
    if restarted != full or restarted_versions != versions:
        raise ValueError("JM_PILOT_DETERMINISTIC_REPLAY_FAILED")
    return {
        "status": "PASS",
        "source_formula_versions": list(versions),
        "intent_count": len(full),
        "prefix_checkpoints": checkpoints,
        "segment_batch_parity": True,
        "deterministic_restart_replay": True,
        "scope_note": "Pure research replay; no daemon or Paper persistence restart tested here.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.canonical_root.is_dir() or not args.env_file.is_file():
        raise SystemExit("JM_PILOT_SOURCE_CONFIG_MISSING")
    load_dotenv(args.env_file, override=False)
    os.environ["GUIYI_CANONICAL_DATA_ROOT"] = str(args.canonical_root.resolve())

    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import (
        build_database_coverage_source,
        build_market_data_service,
    )
    from app.market_data.newow.jm_pilot_research import (
        adapt_jm_execution_facts,
        load_jm_pilot_input,
        run_jm_pilot_research,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_release import candidate_input_quality_policy
    from app.market_data.operational_universe import load_active_products
    from guiyi_quant.newow.product_contracts import ProductFrequency
    from guiyi_quant.newow.research_backtest import (
        ResearchStrategy,
        build_strategy_intents_from_replay_segments,
        run_causal_long_only_backtest,
    )
    from guiyi_quant.newow.research_evidence import (
        CostStressScenario,
        stress_cost_snapshots,
    )

    facts_bytes = args.facts.read_bytes()
    facts = json.loads(facts_bytes)
    amendment = facts.get("tick_amendment")
    if amendment is not None:
        original = args.facts.with_name("execution-facts.json")
        if not original.is_file() or sha256(original.read_bytes()).hexdigest() != amendment.get("original_sha256"):
            raise SystemExit("JM_PILOT_TICK_AMENDMENT_MISMATCH")
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=600):
        market = build_market_data_service(session)
        reader = NewowProductReader(
            market,
            coverage=build_database_coverage_source(session),
            active_products=load_active_products(),
            input_quality_policy=candidate_input_quality_policy(
                "jm", ProductFrequency.FIVE_MINUTE, candidate_weekly=False
            ),
        )
        window = reader.resolve_performance_window(
            "jm", ProductFrequency.FIVE_MINUTE, SINCE, REQUESTED_THROUGH, AS_OF
        )
        source = load_jm_pilot_input(
            market, since=SINCE, actual_through=window.actual_through
        )
        snapshots, constraints, fact_hash = adapt_jm_execution_facts(source, facts)
        research = run_jm_pilot_research(
            source, cost_snapshots=snapshots, execution_constraints=constraints
        )
        parity = _prefix_parity(source)
        all_intents, versions = build_strategy_intents_from_replay_segments(
            source.replay_segments, ResearchStrategy.DUAL_FUSION
        )
        ends = {bar.bar_end for bar in source.bars}
        scored_intents = tuple(
            intent for intent in all_intents if intent.signal_bar_end in ends
        )
        full_stress = {}
        for scenario in CostStressScenario:
            result = run_causal_long_only_backtest(
                source.bars, scored_intents,
                cost_snapshots=stress_cost_snapshots(snapshots, scenario),
                execution_constraints=constraints,
                require_execution_facts=True, require_offset_fees=True,
                strategy=ResearchStrategy.DUAL_FUSION,
                signal_formula_versions=versions,
            )
            full_stress[scenario.value] = _summary(result)
        fold_stress = {
            scenario.value: [
                {
                    "name": fold.fold.name,
                    "train_since": fold.fold.train_since.isoformat(),
                    "train_through": fold.fold.train_through.isoformat(),
                    "test_since": fold.fold.test_since.isoformat(),
                    "test_through": fold.fold.test_through.isoformat(),
                    "warmup_bars": fold.warmup_bar_count,
                    "test_bars": fold.test_bar_count,
                    "physical_prefix_bars": fold.physical_prefix_bar_count,
                    "summary": _summary(fold.backtest),
                }
                for fold in validation.folds
            ]
            for scenario, validation in research.walk_forward_by_scenario
        }
        evidence = {
            "status": "RESEARCH_COMPLETE_NOT_PROMOTED",
            "product": "jm", "frequency": "5m",
            "requested_since": SINCE.isoformat(),
            "requested_through": REQUESTED_THROUGH.isoformat(),
            "as_of": AS_OF.isoformat(),
            "actual_completed_through": window.actual_through.isoformat(),
            "completed_cutoff": window.cutoff.isoformat(),
            "window_complete": window.complete,
            "window_reason": window.reason_code,
            "scored_bar_count": len(source.bars),
            "physical_segments": [
                {
                    "contract": segment.bars[0].physical_contract,
                    "replay_bar_count": len(segment.bars),
                    "eligible_bar_count": sum(bar.observation_eligible for bar in segment.bars),
                    "first_replay_trading_day": segment.bars[0].trading_day.isoformat(),
                    "last_replay_trading_day": segment.bars[-1].trading_day.isoformat(),
                }
                for segment in source.replay_segments
            ],
            "input_sha256": source.input_sha256,
            "facts_file_sha256": sha256(facts_bytes).hexdigest(),
            "facts_canonical_sha256": fact_hash,
            "facts_plan_hash": facts["plan_hash"],
            "facts_captured_at": facts["captured_at"],
            "facts_composed_at": max(
                snapshot.captured_at for snapshot in snapshots
            ).isoformat(),
            "tick_amendment_original_sha256": (
                amendment["original_sha256"] if amendment is not None else None
            ),
            "fee_offsets": ["OPEN", "CLOSE_TODAY", "CLOSE_YESTERDAY"],
            "slippage_assumption": "one adverse tick per fill; double_slippage uses two",
            "retrospective_execution_facts": True,
            "selection_overlap": True,
            "selection_note": "The page ranking used this same historical year; folds are diagnostic, not an independent unseen OOS acceptance.",
            "account_semantics": False,
            "formula_versions": list(versions),
            "research_formula_version": research.full_sample.formula_version,
            "baseline": _summary(research.full_sample),
            "full_sample_cost_stress": full_stress,
            "walk_forward_cost_stress": fold_stress,
            "causal_parity": parity,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.out)
    print(f"RESEARCH_COMPLETE_NOT_PROMOTED {args.out}")


if __name__ == "__main__":
    main()
