"""Versioned continuation of a settled, single-contract Plus Run."""

from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import count

from guiyi_quant.newow.decision_checkpoint import decode_decision_checkpoint, encode_decision_checkpoint

from .codec import digest
from .errors import BacktestError

VERSION = "plus_settled_continuation_v1"


def cost_prefix(costs, through: date) -> str:
    return digest([
        [day.isoformat(), row, costs.margin_at_settlement[day]]
        for day, row in costs.rows.items() if day <= through
    ])


def execution_identity(config: dict, packet, costs) -> str:
    first = next(iter(packet.days))
    return digest({
        "version": VERSION, "config": {key: value for key, value in config.items() if key != "end"},
        "first_market_day": packet.prefix_by_day[first], "first_cost_day": cost_prefix(costs, first),
    })


@dataclass(frozen=True, slots=True)
class Continuation:
    run_id: str
    through: date
    settled_at: datetime
    checkpoint: dict
    result: dict

    @classmethod
    def verify(cls, source, packet, costs, identity):
        try:
            checkpoint, result, run_id = source["checkpoint"], source["result"], source["run_id"]
            through = date.fromisoformat(checkpoint["through"])
            settled_at = datetime.fromisoformat(checkpoint["settled_at"])
            settlement = result["report"]["native_settlements"][-1]
            if (
                checkpoint["version"] != VERSION or through.isoformat() != settlement["trading_day"]
                or settled_at.utcoffset() is None or checkpoint["settled_at"] != settlement["at"]
                or result["equity"][-1]["trading_day"] != through.isoformat()
            ):
                raise ValueError
            if (
                through not in packet.prefix_by_day
                or packet.prefix_by_day[through] != checkpoint["market_prefix"]
                or cost_prefix(costs, through) != checkpoint["cost_prefix"]
                or identity != checkpoint["execution_identity"]
            ):
                raise BacktestError("BACKTEST_INCREMENTAL_PREFIX_CHANGED")
            following = next((session for session in packet.sessions if session.day > through), None)
            if following is None:
                raise BacktestError("BACKTEST_INCREMENTAL_NO_NEW_TRADING_DAY")
            if following.start <= settled_at:
                raise ValueError
            return cls(run_id, through, settled_at, checkpoint, result)
        except BacktestError:
            raise
        except (KeyError, TypeError, ValueError, IndexError):
            raise BacktestError("BACKTEST_CHECKPOINT_INVALID") from None

    def restore(self, run) -> None:
        from rqalpha.model.order import Order
        from rqalpha.model.trade import Trade

        state, result = self.checkpoint, self.result
        _restore_native(run, state["native"], self.settled_at)
        try:
            run.state = decode_decision_checkpoint(state["decision"])
            boundary_session = next(s for s in reversed(run.packet.sessions) if s.day == self.through)
            if run.state.physical_contract != run.contract or run.state.computed_through != boundary_session.end:
                raise ValueError
            run.fills_hash = state["fills_hash"]
            run.account_as_of = datetime.fromisoformat(state["account_as_of"])
            report = result["report"]
            run.first_evaluation_state = report["first_evaluation_state"]
            run.fills = list(report["native_fills"])
            run.attempts = list(report["attempts"])
            run.settlements = list(report["native_settlements"])
            run.bars, run.markers, run.equity = (list(result[k]) for k in ("bars", "markers", "equity"))
            run.peak = max(run.config.initial_capital, *(Decimal(row["equity"]) for row in run.equity))
            run.witness.trades = [row for row in result["trades"] if row["status"] == "CLOSED"]
            run.witness.cash_basis = Decimal(state["cash_basis"])
            if (entry := state["open_fill_id"]) is not None:
                old = next(row for row in run.fills if row["native_trade_id"] == entry)
                run.witness.open_fill = {
                    **old, "economic_price": Decimal(state["open_price"]), "economic_fee": Decimal(state["open_fee"]),
                    "day": date.fromisoformat(old["trading_day"]),
                }
                run.witness.settlement_basis = Decimal(state["settlement_basis"])
            positions = [pos for pos in run.account.get_positions() if pos.quantity]
            if [(p.order_book_id, p.direction.name, p.quantity) for p in positions] != (
                [(run.contract, "LONG", 1)] if run.witness.open_fill else []
            ):
                raise ValueError
            # Position.get_state omits its last quote. Use the already reconciled
            # settlement, before native PRE_BEFORE_TRADING measures the base
            # for the next day's return. The opening quote is not yet known.
            prior = run.packet.days[self.through]
            for position in positions:
                position.update_last_price(float(prior.settlement))
            run.cost_data_source.begin_settlement(self.through, run.instrument)
            restored, equity = run.witness.account(
                run.account, self.through, prior.settlement,
                run.costs.settlement_long_margin(self.through), settled=True,
            )
            if restored != run.settlements[-1]["after"] or equity != Decimal(run.equity[-1]["equity"]):
                raise BacktestError("BACKTEST_INCREMENTAL_ENGINE_STATE_INVALID")
            # The native generators are process-local. Keep genuine callback IDs
            # while preventing a same-second restart from reusing a prefix ID.
            max_order = max((int(row["native_order_id"]) for row in run.attempts if row.get("native_order_id")), default=0)
            max_trade = max((int(row["native_trade_id"]) for row in run.fills), default=0)
            Order.order_id_gen = count(max(next(Order.order_id_gen), max_order + 1))
            Trade.trade_id_gen = count(max(next(Trade.trade_id_gen), max_trade + 1))
        except BacktestError:
            raise
        except (KeyError, TypeError, ValueError, ArithmeticError, StopIteration):
            raise BacktestError("BACKTEST_CHECKPOINT_INVALID") from None

    def public(self, packet) -> dict:
        return {
            "source_run_id": self.run_id, "through": self.through.isoformat(),
            "appended_trading_days": [day.isoformat() for day in packet.days if day > self.through],
            "executed_minutes": sum(row.session.day > self.through for row in packet.minutes.values()),
        }


def _native_objects(run):
    return {
        "portfolio": run.env.portfolio, "broker": run.env.broker,
        "analyser": run.env.mod_dict["sys_analyser"],
    }


def _restore_native(run, native, settled_at):
    # Only a worker-authenticated checkpoint reaches this adapter. Native
    # serializers are version locked and may decode vendor Python objects.
    try:
        objects = _native_objects(run)
        if not isinstance(native, dict) or native.keys() != objects.keys():
            raise ValueError
        boundary = settled_at.replace(tzinfo=None)
        run.env.update_time(boundary, boundary)
        for key, obj in objects.items():
            obj.set_state(b64decode(native[key], validate=True))
        if run.env.broker.get_open_orders():
            raise ValueError
    except Exception:
        raise BacktestError("BACKTEST_INCREMENTAL_ENGINE_STATE_INVALID") from None


def capture_native(run) -> dict:
    try:
        if run.env.broker.get_open_orders():
            raise ValueError
        return {key: b64encode(obj.get_state()).decode("ascii") for key, obj in _native_objects(run).items()}
    except Exception:
        raise BacktestError("BACKTEST_INCREMENTAL_ENGINE_STATE_INVALID") from None


def checkpoint(run, native: dict) -> dict:
    witness = run.witness
    through = next(reversed(run.packet.days))
    if (run.pending is not None or run.rows or run.outstanding is not None
            or run.awaiting_submission is not None or run.pre_settlement_account is not None):
        raise BacktestError("BACKTEST_INCREMENTAL_ENGINE_STATE_INVALID")
    entry = witness.open_fill
    return {
        "version": VERSION, "through": through.isoformat(), "settled_at": run.settlements[-1]["at"],
        "execution_identity": run.execution_identity, "market_prefix": run.packet.prefix_by_day[through],
        "cost_prefix": cost_prefix(run.costs, through), "native": native, "instrument": run.instrument_identity,
        "decision": encode_decision_checkpoint(run.state), "fills_hash": run.fills_hash,
        "account_as_of": run.account_as_of.isoformat(), "cash_basis": str(witness.cash_basis),
        "open_fill_id": entry["native_trade_id"] if entry else None,
        "open_price": str(entry["economic_price"]) if entry else None,
        "open_fee": str(entry["economic_fee"]) if entry else None,
        "settlement_basis": str(witness.settlement_basis) if entry else None,
    }
