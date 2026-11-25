"""Run a sealed P3 input in the pinned offline engine environment."""

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json

from app.reference_trading.json_spool import decode_product_bar
from guiyi_quant.newow.decision_adapter import (
    CompletedMarketPayload,
    ExecutionContext,
    MarketSource,
    V2Strategy,
    seed_decision_state,
    step_completed,
)
from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint

from frozen_market import ASIA_SHANGHAI, DailyFacts, FrozenMarket, Minute, Session
from runner import Signal, run_proof


def _market(raw: dict) -> FrozenMarket:
    return FrozenMarket(
        raw["contract"], raw["exchange"], date.fromisoformat(raw["window_start"]),
        date.fromisoformat(raw["window_end"]), Decimal(raw["tick"]), raw["multiplier"],
        tuple(Session(date.fromisoformat(day), datetime.fromisoformat(start), datetime.fromisoformat(end))
              for day, start, end in raw["sessions"]),
        tuple(Minute(date.fromisoformat(day), datetime.fromisoformat(end), *map(Decimal, values))
              for day, end, *values in raw["minutes"]),
        tuple(DailyFacts(date.fromisoformat(row["day"]), Decimal(row["prev_settlement"]), Decimal(row["settlement"]),
                         Decimal(row["limit_down"]), Decimal(row["limit_up"]), row["fee_type"],
                         Decimal(row["open_fee"]), Decimal(row["close_fee"]), Decimal(row["close_today_fee"]),
                         Decimal(row["long_margin"]), Decimal(row["short_margin"])) for row in raw["daily"]),
        listed_date=date.fromisoformat(raw["listed_date"]), expired_date=date.fromisoformat(raw["expired_date"]),
    )


def _action(decision, frozen_bar):
    return {
        "decision_id": decision.decision_id, "input_ref": decision.input_ref,
        "previous_state_ref": decision.previous_state_ref, "state_ref": decision.state_ref,
        "execution_context_ref": decision.execution_context_ref,
        "owner_segment_id": decision.owner_segment_id, "calculation_segment_id": decision.calculation_segment_id,
        "strategy": decision.strategy.value, "version": decision.version, "frequency": decision.frequency.value,
        "formula_versions": list(decision.formula_versions), "profiles": list(decision.profiles),
        "state": decision.state.value, "action": decision.main_action.value,
        "reason": decision.reason, "execution_candidate": decision.execution_candidate,
        "signal_bar_end": decision.bar_end.astimezone(ASIA_SHANGHAI).isoformat(),
        "signal_available_at": decision.decision_at.astimezone(ASIA_SHANGHAI).isoformat(),
        "source_actions": [{"id": source.signal_id, "related_build_id": source.related_build_id}
                           for source in decision.source_actions],
        "bar": frozen_bar,
    }


def replay(packet: dict, run_id: str) -> dict:
    market = _market(packet["market"])
    state = seed_decision_state()
    strategy = V2Strategy(packet.get("strategy", "trend"))
    frequency = packet.get("frequency", "5m")
    reference_only = packet.get("result_kind") == "reference_only"
    if (frequency in ("1d", "1w")) != reference_only:
        raise ValueError("BACKTEST_EXECUTION_POLICY_UNAVAILABLE")
    base_context = {"scope_id": run_id, "config_revision": packet["execution_profile"],
                    "strategies": (strategy,), "execution_strategy": None if reference_only else strategy}
    completed = []
    decisions = {}
    opens = {}
    for raw in packet["completed"]:
        bar = decode_product_bar(raw["bar"])
        payload = CompletedMarketPayload(
            bar, MarketSource.CANONICAL, packet["market_revision"], raw["source_ref"], raw["owner_ref"],
            tuple(datetime.fromisoformat(value) for value in raw["session"]),
            datetime.fromisoformat(raw["available_at"]), raw["availability_policy"], raw["quality_policy"],
            verified_lifecycle=raw["verified_lifecycle"],
        )
        item = payload.completed_input()
        if (item.fingerprint != raw["fingerprint"] or item.physical_contract != market.contract
                or bar.frequency.value != frequency):
            raise ValueError("P3_COMPLETED_INPUT_MISMATCH")
        if not bar.bar.observation_eligible:
            if completed:
                raise ValueError("P3_WARMUP_AFTER_EXECUTION_WINDOW")
            state, _ = step_completed(state, item, ExecutionContext(**base_context))
            continue
        completed.append((item, raw["bar"]))
        candidate = raw["candidate_open_at"]
        opens[payload.available_at] = datetime.fromisoformat(candidate) if candidate is not None else None
    if not completed or state.computed_through is None:
        raise ValueError("P3_WARMUP_OR_EXECUTION_INPUT_MISSING")

    if reference_only:
        context = ExecutionContext(**base_context)
        actions = []
        for item, raw in completed:
            state, (decision,) = step_completed(state, item, context)
            if decision.main_action is not None:
                actions.append(_action(decision, raw))
        return {"summary": {"result_kind": "reference_only", "decisions": actions,
                            "cutoff_trading_day": completed[-1][0].trading_day.isoformat(),
                            "execution_status": "BACKTEST_EXECUTION_POLICY_UNAVAILABLE"},
                "trades": [], "equity": []}

    pending = iter(completed)
    following = next(pending, None)
    first_open = market.sessions[0].start

    def decide(at, positions, fills):
        nonlocal state, following
        signals = []
        while following is not None and following[0].payload.available_at <= at:
            item, frozen_bar = following
            available = item.payload.available_at
            account_as_of = fills[-1]["native_event_at"] if fills else first_open
            if account_as_of > available or any(
                pos.order_book_id != market.contract or pos.direction.name != "LONG" or pos.quantity != 1
                for pos in positions
            ) or len(positions) > 1:
                raise ValueError("P3_ACCOUNT_PREFIX_INVALID")
            fill_prefix = strategy_input_fingerprint({"fills": [
                {field: row[field] for field in ("signal_id", "side", "quantity", "price", "fee", "native_event_at")}
                for row in fills
            ]})
            position = Decimal(len(positions))
            context = ExecutionContext(
                **base_context, account_as_of=account_as_of, position=position, position_contract=market.contract,
                account_ref=strategy_input_fingerprint({
                    "contract": market.contract, "as_of": account_as_of,
                    "position": position, "fill_prefix": fill_prefix,
                }),
                fill_prefix_ref=fill_prefix,
            )
            state, (decision,) = step_completed(state, item, context)
            if decision.main_action is not None:
                decisions[decision.decision_id] = _action(decision, frozen_bar)
            if decision.execution_candidate:
                signals.append(Signal(decision.decision_id, market.contract, decision.trading_day,
                                      decision.bar_end, decision.main_action.value, available_at=decision.decision_at,
                                      frequency=decision.frequency.value))
            following = next(pending, None)
        return signals

    raw = run_proof(
        market, (), Decimal(packet["initial_equity"]), decide=decide,
        minute_selector=lambda available, _: opens[available],
    )
    if following is not None:
        raise ValueError("P3_COMPLETED_INPUT_NOT_CONSUMED")
    from reconcile import reconcile

    result = reconcile(raw, decisions=decisions)
    result["summary"]["decisions"] = list(decisions.values())
    result["summary"]["engine_version"] = raw["engine_version"]
    result["summary"]["engine_config"] = raw["native"]["config"]
    return result


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("sha256")
    parser.add_argument("run_id")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    body = args.packet.read_bytes()
    if sha256(body).hexdigest() != args.sha256:
        raise ValueError("P3_INPUT_HASH_MISMATCH")
    try:
        report = replay(json.loads(body), args.run_id)
    except (ValueError, RuntimeError) as exc:
        code = getattr(exc, "code", str(exc))
        audit = {key: getattr(exc, key) for key in ("field", "expected", "observed") if hasattr(exc, key)}
        with args.result.open("x") as stream:
            json.dump({"error": code, "audit": audit or None}, stream, default=str)
        raise SystemExit(1) from None
    with args.result.open("x") as stream:
        json.dump({"run_id": args.run_id, "input_sha256": args.sha256, **report}, stream, allow_nan=False)


if __name__ == "__main__":
    main()
